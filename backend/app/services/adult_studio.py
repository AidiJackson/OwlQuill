"""Adult Studio service — 18+ Studio pipeline helpers.

SEPARATE from Canon Studio / Identity OS / Scene Router / Canon Router. This
module READS the locked Canon Pack as source truth and builds an adult-studio
specific generation payload. It never mutates canon.

Responsibilities:
  - prompt safety gate (block minors / illegal terms)
  - build a manifest of canon source images for a character
  - load manifest reference image bytes for the provider
  - build the adult-studio-specific prompt framing
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.core.storage import load_image_bytes
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services import canon_service as cs

logger = logging.getLogger(__name__)

# Hard cap on reference images forwarded to the provider.
MAX_ADULT_STUDIO_REFS = 6


# ── Safety gate ────────────────────────────────────────────────────────
#
# Minimal, not-overbuilt. Blocks the unambiguous illegal/minor categories.
# Matched on word boundaries against the lowercased prompt. This is NOT a
# full moderation system — it is the floor required before any generation.
_BLOCKED_TERMS = [
    "minor", "minors", "underage", "under-age", "under age",
    "teen", "teens", "teenage", "teenager", "tween",
    "child", "children", "kid", "kids", "toddler", "infant", "baby",
    "schoolgirl", "schoolboy", "school girl", "school boy",
    "preteen", "pre-teen", "pubescent", "prepubescent",
    "loli", "lolita", "shota", "jailbait",
    "incest", "bestiality", "rape", "non-consensual", "nonconsensual",
]

# Phrases like "X years old" / "aged X" where X < 18 are also blocked.
_AGE_PATTERN = re.compile(r"\b(\d{1,2})\s*(?:years?\s*old|y/?o|yr?s?\s*old|-year-old)\b")
_AGED_PATTERN = re.compile(r"\baged?\s+(\d{1,2})\b")


def check_prompt_safety(prompt: str) -> Optional[str]:
    """Return a human-readable block reason, or None if the prompt is allowed.

    Adult-adjacent (bikini, lingerie, mature romance, etc.) is ALLOWED.
    Minors / illegal categories are blocked.
    """
    text = (prompt or "").lower()
    for term in _BLOCKED_TERMS:
        # word-boundary match so "kid" doesn't fire inside "kidnap"-free prose
        # but does fire as a standalone word
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text):
            return (
                "This prompt contains terms that are not permitted in 18+ Studio "
                "(minors or illegal content). Generation blocked."
            )
    for m in (*_AGE_PATTERN.finditer(text), *_AGED_PATTERN.finditer(text)):
        try:
            if int(m.group(1)) < 18:
                return (
                    "This prompt references an age under 18. 18+ Studio only "
                    "depicts adults. Generation blocked."
                )
        except (ValueError, IndexError):
            continue
    return None


# ── Manifest building ──────────────────────────────────────────────────


def build_manifest(canon: CharacterIdentityCanon) -> dict:
    """Collect canon source image URLs + marking descriptions into a manifest.

    Reads face/body canon (the locked source of truth). Returns a dict the
    Adult Studio identity record stores and the generator later consumes.
    """
    face = cs.load_face_canon(canon)
    body = cs.load_body_canon(canon)

    refs: list[dict] = []

    def _add(role: str, url: Optional[str]) -> None:
        if url:
            refs.append({"role": role, "url": url})

    if face:
        _add("face_front", face.face_front_image_url)
        _add("face_left_3q", face.face_left_3q_image_url)
        _add("face_right_3q", face.face_right_3q_image_url)

    marks: list[dict] = []
    if body:
        _add("body_front", body.body_front_image_url)
        _add("body_left", body.body_left_image_url)
        _add("body_right", body.body_right_image_url)
        _add("body_back", body.body_back_image_url)
        for m in body.permanent_body_marks:
            marks.append(
                {
                    "label": m.label,
                    "type": m.type,
                    "body_region": m.body_region,
                    "side": m.side,
                    "description": m.description,
                }
            )
            # Prefer detail crop, fall back to general reference, for marking fidelity.
            _add(f"mark:{m.body_region}", m.detail_crop_url or m.reference_image_url)

    return {
        "version": 1,
        "face_description": face.face_description if face else None,
        "body_description": body.body_description if body else None,
        "build": body.build if body else None,
        "refs": refs,
        "marks": marks,
    }


def load_manifest_refs(manifest: dict) -> tuple[list[bytes], list[str]]:
    """Load reference image bytes from a manifest, capped at MAX_ADULT_STUDIO_REFS.

    Face refs are prioritised first (identity seed), then body, then marking crops.
    Unreadable refs are skipped. Returns (bytes_list, role_list) parallel arrays.
    """
    refs = manifest.get("refs") or []

    def _priority(role: str) -> int:
        if role.startswith("face"):
            return 0
        if role.startswith("body"):
            return 1
        return 2  # mark crops

    ordered = sorted(refs, key=lambda r: _priority(r.get("role", "")))

    loaded_bytes: list[bytes] = []
    loaded_roles: list[str] = []
    for entry in ordered:
        if len(loaded_bytes) >= MAX_ADULT_STUDIO_REFS:
            break
        url = entry.get("url")
        if not url:
            continue
        try:
            loaded_bytes.append(load_image_bytes(url))
            loaded_roles.append(entry.get("role", "ref"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("adult_studio ref load failed role=%s url=%s err=%r",
                           entry.get("role"), url, str(exc))
    return loaded_bytes, loaded_roles


# ── Prompt framing ─────────────────────────────────────────────────────

_ADULT_FRAMING_PREFIX = (
    "ADULT (18+) CHARACTER PORTRAIT. The subject is an adult (18 years or older). "
    "This is a tasteful mature/adult-adjacent scene (e.g. swimwear, lingerie, "
    "beachwear, bedroom aesthetic)."
)

_ADULT_IDENTITY_LOCK = (
    "Reproduce the EXACT same person shown in the reference images: identical face "
    "shape, jaw, nose, eye shape, hair, skin tone, and body build. Do not generate a "
    "generic or different person. Preserve all permanent body markings (tattoos, "
    "scars) in their exact anatomical placement, on exposed skin only — never printed "
    "on clothing or fabric, never moved between limbs."
)


def build_adult_prompt(base_prompt: str, manifest: dict, character_name: str = "") -> str:
    """Compose the adult-studio-specific prompt.

    Scene-first, then adult framing + strict identity lock + canon descriptors.
    Distinct from Canon Studio's compile_canon_prompt — Adult Studio owns this.
    """
    parts: list[str] = [base_prompt.strip(), _ADULT_FRAMING_PREFIX]
    if character_name:
        parts.append(f"Character: {character_name} (adult).")
    parts.append(_ADULT_IDENTITY_LOCK)

    lock_bits: list[str] = []
    if manifest.get("face_description"):
        lock_bits.append(f"Face: {manifest['face_description']}")
    if manifest.get("build"):
        lock_bits.append(f"Build: {manifest['build']}")
    if manifest.get("body_description"):
        lock_bits.append(f"Body: {manifest['body_description']}")
    if lock_bits:
        parts.append(". ".join(lock_bits))

    marks = manifest.get("marks") or []
    if marks:
        mark_txt = "; ".join(
            f"{m['label']} ({m['body_region']}, {m['side']}): {m['description']}"
            for m in marks
        )
        parts.append(f"PERMANENT MARKINGS to preserve exactly where skin is exposed: {mark_txt}")

    return ". ".join(p.rstrip(". ") for p in parts if p) + "."
