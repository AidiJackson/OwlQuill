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

import io
import json
import logging
import re
import zipfile
from typing import Optional

from sqlalchemy.orm import Session

from app.core.storage import load_image_bytes
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services import canon_service as cs

logger = logging.getLogger(__name__)

# Hard cap on reference images forwarded to the provider.
MAX_ADULT_STUDIO_REFS = 6

# Default subject phrase used in LoRA captions when the manifest gives no hint.
_DEFAULT_SUBJECT = "adult woman"


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
        # S24C: face expression is now a first-class canon role (was missing in v1/v2).
        _add("expression", face.face_expression_image_url)

    marks: list[dict] = []
    if body:
        _add("body_front", body.body_front_image_url)
        _add("body_left", body.body_left_image_url)
        _add("body_right", body.body_right_image_url)
        _add("body_back", body.body_back_image_url)
        # S24C: body map + final identity card are now first-class roles (missing in v1/v2).
        _add("body_map", body.body_map_image_url)
        _add("final_card", body.final_character_card_image_url)
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


# ── Training pack export (SDXL LoRA) ───────────────────────────────────
#
# Build an offline, self-contained training pack from the prepared manifest so a
# per-character SDXL LoRA can be trained/validated OUTSIDE Ficshon. This does NOT
# train, generate, or call any provider — it only packages the locked-canon
# source images + captions into a ZIP. Canon is read-only.

# Manifest ref roles that map to a fixed, stable filename slot.
_FIXED_ROLE_FILENAMES = {
    "face_front": "face_front.png",
    "face_left_3q": "face_left_3q.png",
    "face_right_3q": "face_right_3q.png",
    "expression": "expression.png",
    "body_front": "body_front.png",
    "body_left": "body_left.png",
    "body_right": "body_right.png",
    "body_back": "body_back.png",
    "body_map": "body_map.png",
    "final_card": "final_card.png",
}

_FACE_VIEW = {
    "face_front": "front view",
    "face_left_3q": "left three-quarter view",
    "face_right_3q": "right three-quarter view",
}
_BODY_VIEW = {
    "body_front": "front view",
    "body_left": "left side view",
    "body_right": "right side view",
    "body_back": "back view",
}


def _slug(text: str) -> str:
    """Lowercase a label into a stable filesystem-safe token."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", (text or "").lower())).strip("_")


def trigger_token(character_name: str) -> str:
    """Derive a unique LoRA trigger token, e.g. 'Summer Fielding' → 'ficsummerfielding'."""
    slug = re.sub(r"[^a-z0-9]", "", (character_name or "").lower())
    return f"fic{slug}" if slug else "ficcharacter"


def _ref_filename(role: str) -> str:
    """Map a manifest ref role to a stable, readable image filename."""
    if role in _FIXED_ROLE_FILENAMES:
        return _FIXED_ROLE_FILENAMES[role]
    if role.startswith("mark:"):
        return f"mark_{_slug(role.split(':', 1)[1])}.png"
    return f"{_slug(role) or 'ref'}.png"


def _join_caption(*parts: str) -> str:
    """Join non-empty caption fragments with ', '."""
    return ", ".join(p.strip() for p in parts if p and p.strip())


def _mark_name(m: Optional[dict]) -> str:
    """Short factual tattoo name from a mark, e.g. 'butterfly floral sleeve tattoo'."""
    if not m:
        return "tattoo"
    name = (m.get("label") or m.get("type") or "tattoo").lower().strip()
    mtype = (m.get("type") or "tattoo").lower().strip()
    if mtype and mtype not in name:
        name = f"{name} {mtype}"
    return name


def _marks_body_phrase(marks: list[dict]) -> str:
    """Body-caption markings descriptor using CANON sides, e.g.
    'butterfly floral sleeve tattoo on right upper arm, ballerina tattoo on left forearm'."""
    bits: list[str] = []
    for m in marks:
        region = (m.get("body_region") or "").lower().strip().replace("_", " ")
        name = _mark_name(m)
        bits.append(f"{name} on {region}" if region else name)
    return ", ".join(bits)


# Factual per-image caption views (S24C — kohya-style, one unique trigger token).
_FACE_VIEW_CAPTION = {
    "face_front": "front face portrait",
    "face_left_3q": "left three-quarter face view",
    "face_right_3q": "right three-quarter face view",
    "expression": "expression portrait",
}
_BODY_VIEW_CAPTION = {
    "body_front": "full body front view",
    "body_left": "full body left side view",
    "body_right": "full body right side view",
    "body_back": "full body back view",
}


def _caption_for(
    role: str, manifest: dict, trigger: str, subject: str, identity_traits: str = ""
) -> str:
    """Build a simple, factual per-image caption.

    ``trigger`` is the unique LoRA token (e.g. 'smmr_v3'); ``subject`` is the noun
    (e.g. 'woman'); ``identity_traits`` is an optional caller-supplied descriptor such
    as 'blonde hair, blue eyes'. Markings use CANON side/region (the locked truth).
    """
    base = f"{trigger} {subject}".strip()
    marks = manifest.get("marks") or []
    build = (manifest.get("build") or "").strip()
    build_phrase = f"{build} body" if build else ""

    if role in _FACE_VIEW_CAPTION:
        return _join_caption(base, identity_traits, _FACE_VIEW_CAPTION[role])
    if role == "body_front":
        return _join_caption(base, _BODY_VIEW_CAPTION[role], build_phrase, _marks_body_phrase(marks))
    if role in _BODY_VIEW_CAPTION:
        return _join_caption(base, _BODY_VIEW_CAPTION[role], build_phrase)
    if role == "body_map":
        return _join_caption(base, "full anatomy body map", "body proportions", "tattoo placement")
    if role == "final_card":
        return _join_caption(base, "identity reference card", build_phrase, identity_traits)
    if role.startswith("mark:"):
        region_raw = role.split(":", 1)[1]
        m = next((x for x in marks if (x.get("body_region") or "") == region_raw), None)
        region = (region_raw or "").lower().strip().replace("_", " ")
        return _join_caption(base, f"{_mark_name(m)} {region} closeup".strip())
    return _join_caption(base, role.replace("_", " "))


def _training_readme(character_name: str, trigger: str, image_count: int) -> str:
    return (
        f"Ficshon Adult Studio — Training Pack\n"
        f"Character: {character_name}\n"
        f"Trigger token: {trigger}\n"
        f"Images: {image_count}\n"
        f"\n"
        f"Contents:\n"
        f"  manifest.json        — raw Adult Studio identity manifest (source of truth)\n"
        f"  captions.json        — {{ image_filename: caption }} map\n"
        f"  training_notes.json  — recommended model/method + provenance\n"
        f"  images/<name>.png    — locked-canon reference images\n"
        f"  images/<name>.txt    — per-image caption (kohya/SDXL LoRA layout)\n"
        f"\n"
        f"Intended use:\n"
        f"  Train a per-character SDXL character LoRA OUTSIDE Ficshon (e.g. kohya_ss /\n"
        f"  ComfyUI). Use the trigger token '{trigger}' in prompts to invoke the\n"
        f"  identity. Every image here is derived from the character's LOCKED canon\n"
        f"  pack and must be treated as identity truth — do not substitute, retouch\n"
        f"  identity features, or move permanent markings between limbs.\n"
        f"\n"
        f"This pack performs no training and contains no generated output. It is a\n"
        f"packaging of existing canon references only.\n"
    )


def build_training_pack(
    manifest: dict,
    *,
    character_id: int,
    character_name: str,
    trigger: Optional[str] = None,
    identity_traits: str = "",
) -> tuple[bytes, dict]:
    """Package the manifest's canon references into a LoRA training ZIP.

    Returns (zip_bytes, summary). Loads ALL manifest refs (not capped like the
    provider path) and gives each a stable filename + caption. Unreadable refs
    are skipped and reported in the summary — never silently dropped.

    ``trigger`` overrides the unique LoRA token (defaults to the derived ``trigger_token``);
    ``identity_traits`` is an optional factual descriptor woven into face/identity captions.
    """
    trigger = (trigger or trigger_token(character_name)).strip()
    subject = (manifest.get("subject") or _DEFAULT_SUBJECT).strip() or _DEFAULT_SUBJECT
    refs = manifest.get("refs") or []

    images: dict[str, bytes] = {}
    captions: dict[str, str] = {}
    skipped: list[dict] = []

    for entry in refs:
        role = entry.get("role", "")
        url = entry.get("url")
        if not url:
            continue
        fname = _ref_filename(role)
        # Avoid collisions if two roles slug to the same name.
        if fname in images:
            fname = f"{fname[:-4]}_{_slug(role)}.png"
        try:
            data = load_image_bytes(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("training_pack ref load failed role=%s url=%s err=%r", role, url, str(exc))
            skipped.append({"role": role, "error": str(exc)})
            continue
        images[fname] = data
        captions[fname] = _caption_for(role, manifest, trigger, subject, identity_traits)

    training_notes = {
        "character_id": character_id,
        "character_name": character_name,
        "trigger_token": trigger,
        "source": "adult_studio_manifest",
        "recommended_model": "SDXL",
        "recommended_method": "character_lora",
        "notes": (
            "All source images come from the character's LOCKED canon pack and must "
            "be treated as identity truth. Preserve face geometry, hair, body build, "
            "and all permanent markings in their exact anatomical placement. Do not "
            "substitute a different person or relocate tattoos between limbs."
        ),
        "image_count": len(images),
        "skipped_refs": skipped,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, data in images.items():
            zf.writestr(f"images/{fname}", data)
            zf.writestr(f"images/{fname[:-4]}.txt", captions[fname])
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("captions.json", json.dumps(captions, indent=2, ensure_ascii=False))
        zf.writestr("training_notes.json", json.dumps(training_notes, indent=2, ensure_ascii=False))
        zf.writestr("README.txt", _training_readme(character_name, trigger, len(images)))

    summary = {
        "trigger_token": trigger,
        "image_count": len(images),
        "skipped": skipped,
        "filenames": sorted(images.keys()),
    }
    return buf.getvalue(), summary
