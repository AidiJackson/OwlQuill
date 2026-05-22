"""Body canon service — persistent anatomical markings injected into identity lock."""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.models.character import Character as CharacterModel
from app.schemas.body_canon import (
    BodyCanonRead,
    BodyMarking,
    BodyMarkingCreate,
    BodyMarkingRead,
)

logger = logging.getLogger(__name__)

# ── Placement → compact spatial phrase ───────────────────────────────
_PLACEMENT_PHRASE: dict[str, str] = {
    "left_upper_arm": "on left upper arm",
    "left_forearm": "on left forearm",
    "left_full_arm": "covering full left arm",
    "right_upper_arm": "on right upper arm",
    "right_forearm": "on right forearm",
    "right_full_arm": "covering full right arm",
    "chest": "on chest",
    "upper_back": "on upper back",
    "lower_back": "on lower back",
    "full_back": "covering full back",
    "side": "along the side",
    "ribs": "along the ribs",
    "abdomen": "on abdomen",
    "neck": "on neck",
    "throat": "on throat",
    "right_cheek": "on right cheek",
    "left_cheek": "on left cheek",
    "forehead": "on forehead",
    "chin": "on chin",
    "jaw": "along the jaw",
    "left_hand": "on left hand",
    "right_hand": "on right hand",
    "knuckles": "across knuckles",
    "left_thigh": "on left thigh",
    "right_thigh": "on right thigh",
    "left_calf": "on left calf",
    "right_calf": "on right calf",
}


def build_compact_token(marking: BodyMarking) -> str:
    """Build a compact spatial token: '{size} {style} {placement_phrase}'.

    E.g. "full sleeve black serpent tattoo covering full left arm"
         "medium diagonal scar on right cheek"
         "large flame burn on left forearm"
    """
    placement_phrase = _PLACEMENT_PHRASE.get(
        marking.placement, f"on {marking.placement.replace('_', ' ')}"
    )
    size_str = marking.size.replace("_", " ")
    return f"{size_str} {marking.style} {placement_phrase}"


def build_body_canon_lock_string(markings: list[BodyMarking]) -> str:
    """Compile all markings into the identity lock contribution.

    Returns empty string when no markings are present.
    Format: "BODY MARKINGS: {token1}; {token2}; ..."
    """
    if not markings:
        return ""
    tokens = [build_compact_token(m) for m in markings]
    return "BODY MARKINGS: " + "; ".join(tokens)


# ── Persistence helpers ───────────────────────────────────────────────

def load_markings(character: CharacterModel) -> list[BodyMarking]:
    """Deserialise body_canon_json → list of BodyMarking objects."""
    if not character.body_canon_json:
        return []
    try:
        raw = json.loads(character.body_canon_json)
        return [BodyMarking(**m) for m in raw.get("markings", [])]
    except (ValueError, TypeError, KeyError):
        logger.warning("body_canon_load_failed character_id=%s", character.id)
        return []


def _save_markings(character: CharacterModel, markings: list[BodyMarking]) -> None:
    character.body_canon_json = json.dumps(
        {"markings": [m.model_dump() for m in markings]}
    )


def add_marking(
    character: CharacterModel,
    payload: BodyMarkingCreate,
) -> BodyMarking:
    """Add a new body marking to the character's canon. Returns the new marking."""
    markings = load_markings(character)
    new_marking = BodyMarking(**payload.model_dump())
    markings.append(new_marking)
    _save_markings(character, markings)
    logger.info(
        "body_canon_add character_id=%s marking_id=%s type=%s placement=%s",
        character.id, new_marking.id, new_marking.type, new_marking.placement,
    )
    return new_marking


def remove_marking(character: CharacterModel, marking_id: str) -> bool:
    """Remove a marking by ID. Returns True if found and removed, False if not found."""
    markings = load_markings(character)
    before = len(markings)
    markings = [m for m in markings if m.id != marking_id]
    if len(markings) == before:
        return False
    _save_markings(character, markings)
    logger.info(
        "body_canon_remove character_id=%s marking_id=%s", character.id, marking_id
    )
    return True


def to_read_list(
    character_id: int, markings: list[BodyMarking]
) -> BodyCanonRead:
    """Convert markings to the API read schema (with compact_token computed)."""
    items = [
        BodyMarkingRead(**m.model_dump(), compact_token=build_compact_token(m))
        for m in markings
    ]
    return BodyCanonRead(character_id=character_id, markings=items)
