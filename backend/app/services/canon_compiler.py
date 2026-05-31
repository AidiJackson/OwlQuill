"""Canon prompt compiler — Identity OS minimal prompt.

P12 architecture:

    USER PROMPT → Scene Router → Canon Card Selection → Provider

Identity truth (facial identity, anatomy, proportions, visible body truth,
and tattoo placement) is carried by the canon **reference cards** selected by
the scene router — NOT by prose. The provider infers identity from those
cards. This compiler therefore keeps the user's scene prompt essentially
unchanged, adding only:

  * a minimal safety directive, and
  * any removable accessory the user explicitly requested via trigger keyword.

There are intentionally NO canon paragraphs, tattoo-visibility essays,
relocation / side-lock invariants, or covered/hidden marking blocks. Those
prose systems were removed in P12 (rollback tag: pre-p12-canon-routing-simplification)
because they conflicted with, and provided no leverage over, the card truth.

The old identity_compiler.py remains for legacy characters without a canon record.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.canon_service import (
    load_accessories,
    load_body_canon,
    load_face_canon,
)

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.schemas.canon import RemovableAccessory

logger = logging.getLogger(__name__)

# ── Minimal safety directive ──────────────────────────────────────────
# The only standing prose the compiler prepends. Kept short and content-policy
# only — it carries no identity engineering.
_SAFETY_PREFIX = "adult, fully clothed, non-explicit, tasteful"

# Provider prompt cap. Prompts are now small (safety + accessories + scene), so
# this almost never triggers; retained purely as a defensive truncation guard.
_PROMPT_CAP = 2400


# ── Reference image collector ─────────────────────────────────────────
# Unchanged from P8: the canonical static priority ordering. The scene router
# (scene_router.py) selects/weights cards for routed scenes and falls back to
# this ordering when the prompt is ambiguous.

def collect_canon_reference_urls(
    canon: "CharacterIdentityCanon",
) -> list[str]:
    """Collect reference image URLs in provider-priority order.

    Priority (positions 0–5 are always sent under the 6-image provider cap):
      0. face_front            — primary face identity seed
      1. face_left_3q          — face geometry supplement
      2. face_right_3q         — face geometry supplement
      3. body_front            — body morphology + tattoo placement truth
      4. body_map              — canonical marking placement sheet
      5. final_character_card  — holistic identity grounding

    May drop under provider cap (positions 6–9):
      6. body_left             — side detail (optional)
      7. body_right            — side detail (optional)
      8. body_back             — back detail (optional)
      9. face_expression       — lowest-value face variant; always last

    Rationale: face_expression is a 4th face angle with marginal identity
    value. body_map and final_character_card carry canonical marking truth
    and must always reach the provider. Optional side/back refs may drop.
    """
    face = load_face_canon(canon)
    body = load_body_canon(canon)

    def _f(obj: object, attr: str) -> str | None:
        return getattr(obj, attr, None) if obj else None

    # Build in strict priority order — each entry is (url_or_None,).
    # Skip None entries so sparse canons produce a compact list.
    ordered = [
        _f(face, "face_front_image_url"),           # 0 — always first
        _f(face, "face_left_3q_image_url"),          # 1
        _f(face, "face_right_3q_image_url"),         # 2
        _f(body, "body_front_image_url"),            # 3 — body truth
        _f(body, "body_map_image_url"),              # 4 — marking placement
        _f(body, "final_character_card_image_url"),  # 5 — holistic grounding
        _f(body, "body_left_image_url"),             # 6 — may drop
        _f(body, "body_right_image_url"),            # 7 — may drop
        _f(body, "body_back_image_url"),             # 8 — may drop
        _f(face, "face_expression_image_url"),       # 9 — always last
    ]
    return [url for url in ordered if url]


# ── Requested removable accessories ───────────────────────────────────

def _requested_accessories(
    canon: "CharacterIdentityCanon",
    scene_lower: str,
) -> list["RemovableAccessory"]:
    """Return removable accessories whose trigger keyword appears in the scene.

    Deterministic substring match only. Accessories are never inferred — they
    appear solely when the user's prompt explicitly asks for them.
    """
    requested: list["RemovableAccessory"] = []
    for acc in load_accessories(canon):
        for kw in (acc.trigger_keywords or []):
            if kw.lower() in scene_lower:
                requested.append(acc)
                break
    return requested


# ── Main compiler ─────────────────────────────────────────────────────

def compile_canon_prompt(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
    *,
    include_accessories: bool = True,
) -> str:
    """Compile a minimal generation prompt from the user's scene.

    Output order:
      1. minimal safety directive
      2. requested removable accessories (keyword-triggered only)
      3. the user's scene prompt, essentially unchanged

    Identity is supplied by the routed canon reference cards, not by this
    prompt. No canon prose, marking essays, or relocation/side-lock invariants
    are emitted.
    """
    scene = scene_prompt.strip()
    parts: list[str] = [_SAFETY_PREFIX]

    requested: list["RemovableAccessory"] = []
    if include_accessories:
        requested = _requested_accessories(canon, scene.lower())
        if requested:
            parts.append("wearing " + "; ".join(a.description for a in requested))

    parts.append(scene)

    prompt = ", ".join(p for p in parts if p)

    if len(prompt) > _PROMPT_CAP:
        prompt = prompt[:_PROMPT_CAP]
        logger.warning(
            "canon_prompt_truncated character_id=%s len=%d",
            canon.character_id, _PROMPT_CAP,
        )

    logger.info(
        "CANON_PROMPT character_id=%s accessories=%d prompt_len=%d",
        canon.character_id, len(requested), len(prompt),
    )

    return prompt


def has_any_canon_content(canon: "CharacterIdentityCanon") -> bool:
    """Return True if the canon record has any face or body content."""
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    if face and any([
        face.face_front_image_url, face.face_description,
    ]):
        return True
    if body and any([
        body.body_front_image_url, body.body_description,
        body.permanent_body_marks,
    ]):
        return True
    return False
