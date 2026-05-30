"""Canon prompt compiler — clean strict hierarchy.

Compiles a generation prompt from CharacterIdentityCanon in exact order:
  1. FACE CANON
  2. BODY CANON
  3. PERMANENT BODY MARKS
  4. REQUESTED REMOVABLE ACCESSORIES (trigger-keyword matched)
  5. USER SCENE PROMPT
  6. LOCKED CANON CLAUSE

No other source of identity truth is consulted here.
The old identity_compiler.py remains for legacy characters without a canon record.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from app.schemas.canon import BodyCanonData, FaceCanonData, RemovableAccessory
from app.services.canon_service import (
    load_accessories,
    load_body_canon,
    load_face_canon,
)

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon

logger = logging.getLogger(__name__)

# ── Hard invariants ───────────────────────────────────────────────────

LOCKED_CANON_CLAUSE = (
    "The character's locked face, body, proportions, scars, tattoos, birthmarks, "
    "and permanent body markings are canon. "
    "Do not redesign, relocate, resize, mirror, reinterpret, remove, or replace them. "
    "Scene, pose, wardrobe, lighting, and environment may change only if they do not "
    "conflict with locked canon."
)

ACCESSORY_RULE = (
    "Only include removable accessories if the user prompt explicitly requests them "
    "or includes one of their trigger keywords. "
    "Do not add accessories that are not requested."
)

SCENE_RULE = "Scene prompt is lower priority than locked character canon."

_SAFETY_PREFIX = "adult, fully clothed, non-explicit, tasteful"

_PROMPT_CAP = 1800  # characters — hard ceiling

# ── Reference image collector ─────────────────────────────────────────

def collect_canon_reference_urls(
    canon: "CharacterIdentityCanon",
) -> list[str]:
    """Collect all locked reference image URLs from canon in priority order.

    Order: face_front → face_3q → body_front → body_left → body_right
           → body_back → body_map → final_card

    Returns empty list if no canon images are set.
    """
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    urls: list[str] = []

    if face:
        for attr in (
            "face_front_image_url",
            "face_left_3q_image_url",
            "face_right_3q_image_url",
            "face_expression_image_url",
        ):
            url = getattr(face, attr, None)
            if url:
                urls.append(url)

    if body:
        for attr in (
            "body_front_image_url",
            "body_left_image_url",
            "body_right_image_url",
            "body_back_image_url",
            "body_map_image_url",
            "final_character_card_image_url",
        ):
            url = getattr(body, attr, None)
            if url:
                urls.append(url)

    return urls


# ── Main compiler ─────────────────────────────────────────────────────

def compile_canon_prompt(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
    *,
    include_accessories: bool = True,
) -> str:
    """Compile a scene prompt from the character's locked canon.

    Always in this order:
      1. Safety prefix
      2. FACE CANON (description)
      3. BODY CANON (anatomy description)
      4. PERMANENT BODY MARKS (locked anatomical truth)
      5. REMOVABLE ACCESSORIES (only if trigger-keyword matched)
      6. USER SCENE PROMPT
      7. LOCKED CANON CLAUSE (if face or body is locked)

    Returns a prompt string capped at _PROMPT_CAP characters.
    """
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    accessories = load_accessories(canon) if include_accessories else []
    has_locked = (face and face.locked) or (body and body.locked)

    parts: list[str] = [_SAFETY_PREFIX]

    # ── 1. FACE CANON ─────────────────────────────────────────────
    if face:
        if face.face_description:
            parts.append(f"FACE CANON: {face.face_description}")

    # ── 2. BODY CANON (anatomy) ───────────────────────────────────
    if body:
        body_parts: list[str] = []
        if body.body_description:
            body_parts.append(body.body_description)
        morphology: list[str] = []
        if body.height:
            morphology.append(body.height)
        if body.build:
            morphology.append(f"{body.build} build")
        if body.proportions:
            morphology.append(body.proportions)
        if body.skin_tone:
            morphology.append(f"{body.skin_tone} skin")
        if morphology:
            body_parts.append(", ".join(morphology))
        if body_parts:
            parts.append("BODY CANON: " + ". ".join(body_parts))

    # ── 3. PERMANENT BODY MARKS ───────────────────────────────────
    if body and body.permanent_body_marks:
        mark_tokens: list[str] = []
        for m in body.permanent_body_marks:
            side_str = m.side if m.side in ("centre", "bilateral") else f"{m.side} side"
            mark_tokens.append(
                f"{m.type} on {m.body_region} ({side_str}): {m.description}"
            )
        parts.append("PERMANENT BODY MARKS: " + "; ".join(mark_tokens))

    # ── 4. REMOVABLE ACCESSORIES ──────────────────────────────────
    if accessories and include_accessories:
        scene_lower = scene_prompt.lower()
        requested: list[RemovableAccessory] = []
        for acc in accessories:
            for kw in (acc.trigger_keywords or []):
                if kw.lower() in scene_lower:
                    requested.append(acc)
                    break
        if requested:
            acc_tokens = [acc.description for acc in requested]
            parts.append("ACCESSORIES (requested): " + "; ".join(acc_tokens))
        else:
            parts.append(ACCESSORY_RULE)

    # ── 5. USER SCENE PROMPT ──────────────────────────────────────
    parts.append(scene_prompt.strip())

    # ── 6. LOCKED CANON CLAUSE ────────────────────────────────────
    if has_locked:
        parts.append(LOCKED_CANON_CLAUSE)

    prompt = ", ".join(p for p in parts if p)

    if len(prompt) > _PROMPT_CAP:
        prompt = prompt[:_PROMPT_CAP]
        logger.warning(
            "canon_prompt_truncated character_id=%s len=%d",
            canon.character_id, _PROMPT_CAP,
        )

    logger.info(
        "CANON_PROMPT character_id=%s face_locked=%s body_locked=%s "
        "marks=%d accs=%d prompt_len=%d",
        canon.character_id,
        face.locked if face else False,
        body.locked if body else False,
        len(body.permanent_body_marks) if body else 0,
        len(accessories),
        len(prompt),
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
