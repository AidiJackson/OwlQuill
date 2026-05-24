"""Body canon service — persistent anatomical markings injected into identity lock."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from app.models.character import Character as CharacterModel
from app.schemas.body_canon import (
    AnchorStatus,
    BodyCanonRead,
    BodyMarking,
    BodyMarkingCreate,
    BodyMarkingRead,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

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


# ── Sleeve semantics ──────────────────────────────────────────────────

def is_sleeve_marking(marking: BodyMarking) -> bool:
    """Return True if this marking is a full-arm sleeve (shoulder to wrist).

    Checks coverage field first, then falls back to size and style text.
    A full sleeve is hard anatomical identity — it must appear when the arm is visible.
    """
    coverage_val = getattr(marking, "coverage", None)
    if coverage_val in ("sleeve", "full_sleeve"):
        return True
    if marking.size == "full_sleeve":
        return True
    style_lower = (marking.style or "").lower()
    return "sleeve" in style_lower


def get_arm_side(placement: str) -> Optional[str]:
    """Return 'left' or 'right' for arm placements, None for all other placements."""
    if placement in ("left_arm", "left_upper_arm", "left_forearm", "left_full_arm"):
        return "left"
    if placement in ("right_arm", "right_upper_arm", "right_forearm", "right_full_arm"):
        return "right"
    return None


def build_sleeve_enforcement_str(markings: list[BodyMarking], visible_regions: set) -> str:
    """Build hard identity text for full-sleeve tattoos on exposed arms.

    Returns compact enforcement sentences for each visible sleeve, or '' if none.
    These are injected as a separate strong-language block in the identity prompt.
    """
    parts = []
    for m in markings:
        if not is_sleeve_marking(m):
            continue
        side = get_arm_side(m.placement)
        if side == "left" and "left_arm" in visible_regions:
            parts.append(
                f"left arm: {m.style} from shoulder to wrist — "
                "must be present if left arm is visible"
            )
        elif side == "right" and "right_arm" in visible_regions:
            parts.append(
                f"right arm: {m.style} from shoulder to wrist — "
                "must be present if right arm is visible"
            )
    if not parts:
        return ""
    return "SLEEVE IDENTITY: " + "; ".join(parts)


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


def get_marking_by_id(character: CharacterModel, marking_id: str) -> Optional[BodyMarking]:
    """Return the marking with the given id, or None."""
    for m in load_markings(character):
        if m.id == marking_id:
            return m
    return None


def update_marking(
    character: CharacterModel,
    marking_id: str,
    updates: dict,
) -> Optional[BodyMarking]:
    """Patch fields on a marking by id. Returns updated marking, or None if not found."""
    markings = load_markings(character)
    for i, m in enumerate(markings):
        if m.id == marking_id:
            merged = {**m.model_dump(), **updates}
            markings[i] = BodyMarking(**merged)
            _save_markings(character, markings)
            logger.info(
                "body_canon_update character_id=%s marking_id=%s updates=%s",
                character.id, marking_id, list(updates.keys()),
            )
            return markings[i]
    return None


def upsert_marking_from_preset(
    character: CharacterModel,
    preset_slug: str,
    placement: str,
    prompt_token: str,
    marking_type: str = "tattoo",
) -> BodyMarking:
    """Create or update a body marking derived from a style shop tattoo preset.

    Matches existing markings by slug tag (stored in description as '#slug:...').
    If no match, adds a new marking. Anchor fields are preserved on update.
    """
    markings = load_markings(character)
    slug_tag = f"#slug:{preset_slug}"
    for i, m in enumerate(markings):
        if slug_tag in (m.description or ""):
            style_val = prompt_token.split(",")[0].strip()
            updated = {
                **m.model_dump(),
                "placement": placement,
                "style": style_val,
                "description": f"{prompt_token} {slug_tag}",
            }
            markings[i] = BodyMarking(**updated)
            _save_markings(character, markings)
            logger.info(
                "body_canon_upsert_from_preset character_id=%s slug=%s action=update",
                character.id, preset_slug,
            )
            return markings[i]

    # Not found — create new
    size_guess = "full_sleeve" if "sleeve" in prompt_token.lower() else "large"
    new_m = BodyMarking(
        type=marking_type,  # type: ignore[arg-type]
        placement=placement,  # type: ignore[arg-type]
        style=prompt_token.split(",")[0].strip(),
        size=size_guess,  # type: ignore[arg-type]
        description=f"{prompt_token} {slug_tag}",
    )
    markings.append(new_m)
    _save_markings(character, markings)
    logger.info(
        "body_canon_upsert_from_preset character_id=%s slug=%s action=create",
        character.id, preset_slug,
    )
    return new_m


# Maps style shop PlacementEnum value → body canon MarkingPlacement value
_STYLE_TO_BODY_PLACEMENT: dict[str, str] = {
    "right_arm": "right_full_arm",
    "left_arm": "left_full_arm",
    "chest": "chest",
    "back": "full_back",
    "neck": "neck",
    "face": "right_cheek",
    "hand": "right_hand",
}


def sync_tattoo_style_elements_to_body_canon(
    character: CharacterModel,
    db: "Session",
) -> dict:
    """Sync all active TATTOO CharacterStyleElement rows into body_canon_json.

    Idempotent — existing markings matched by slug tag are updated without
    touching their anchor fields. New markings are created for any active
    tattoo element not yet in body_canon_json.

    Returns a summary dict: {"active_tattoos": n, "created": n, "updated": n}.
    """
    from app.models.style_shop import (
        CharacterStyleElement,
        ShopTypeEnum,
        StyleElementStatusEnum,
        StylePreset,
    )

    active_tattoo_elements = (
        db.query(CharacterStyleElement)
        .join(StylePreset)
        .filter(
            CharacterStyleElement.character_id == character.id,
            CharacterStyleElement.status == StyleElementStatusEnum.ACTIVE,
            StylePreset.shop_type == ShopTypeEnum.TATTOO,
        )
        .all()
    )

    created = 0
    updated = 0

    for el in active_tattoo_elements:
        preset = el.preset
        body_placement = _STYLE_TO_BODY_PLACEMENT.get(
            el.placement.value if hasattr(el.placement, "value") else str(el.placement),
            str(el.placement),
        )
        slug_tag = f"#slug:{preset.slug}"
        existing_markings = load_markings(character)
        already_exists = any(slug_tag in (m.description or "") for m in existing_markings)

        upsert_marking_from_preset(
            character,
            preset_slug=preset.slug,
            placement=body_placement,
            prompt_token=preset.prompt_token,
            marking_type="tattoo",
        )
        if already_exists:
            updated += 1
        else:
            created += 1

    logger.info(
        "BODY-CANON-SYNC character_id=%s active_tattoos=%d created=%d updated=%d",
        character.id,
        len(active_tattoo_elements),
        created,
        updated,
    )
    return {"active_tattoos": len(active_tattoo_elements), "created": created, "updated": updated}


# ── Anchor prompt builder ─────────────────────────────────────────────

# Maps placement value → human-readable body region for anchor prompt
_ANCHOR_REGION: dict[str, str] = {
    "right_arm": "right upper arm and forearm",
    "right_upper_arm": "right upper arm",
    "right_forearm": "right forearm",
    "right_full_arm": "right upper arm and forearm",
    "left_arm": "left upper arm and forearm",
    "left_upper_arm": "left upper arm",
    "left_forearm": "left forearm",
    "left_full_arm": "left upper arm and forearm",
    "chest": "chest and upper torso",
    "upper_back": "upper back",
    "lower_back": "lower back",
    "full_back": "full back",
    "side": "left side and ribs",
    "ribs": "ribcage",
    "abdomen": "abdomen",
    "neck": "neck and throat",
    "throat": "throat",
    "right_cheek": "right cheek",
    "left_cheek": "left cheek",
    "forehead": "forehead",
    "chin": "chin and jaw",
    "jaw": "jaw",
    "left_hand": "left hand and fingers",
    "right_hand": "right hand and fingers",
    "knuckles": "knuckles",
    "left_thigh": "left thigh",
    "right_thigh": "right thigh",
    "left_calf": "left calf",
    "right_calf": "right calf",
}

# Side-note suffix for anatomical precision in anchor prompt
_ANCHOR_SIDE_NOTE: dict[str, str] = {
    "right_arm": "placed only on the right arm, not the left",
    "right_upper_arm": "placed only on the right upper arm",
    "right_forearm": "placed only on the right forearm",
    "right_full_arm": "placed only on the right arm, not the left",
    "left_arm": "placed only on the left arm, not the right",
    "left_upper_arm": "placed only on the left upper arm",
    "left_forearm": "placed only on the left forearm",
    "left_full_arm": "placed only on the left arm, not the right",
}


def build_anchor_generation_prompt(marking: BodyMarking, character_name: str = "") -> str:
    """Build a close-up body-location reference image prompt for a body marking.

    Returns a prompt that generates a clean anatomical reference card showing
    the marking in context of the correct body area.
    """
    placement = marking.placement
    region = _ANCHOR_REGION.get(placement, placement.replace("_", " "))
    side_note = _ANCHOR_SIDE_NOTE.get(placement, "")

    name_part = f"{character_name}'s " if character_name else "the character's "
    token = marking.style

    side_clause = f", {side_note}" if side_note else ""
    return (
        f"Close-up reference image of {name_part}{region}, showing {token}"
        f"{side_clause}. Clear readable design, neutral background, "
        f"no full body, no face, no complex pose. Anatomical reference card."
    )


def to_read_list(
    character_id: int, markings: list[BodyMarking]
) -> BodyCanonRead:
    """Convert markings to the API read schema (with compact_token computed)."""
    items = [
        BodyMarkingRead(**m.model_dump(), compact_token=build_compact_token(m))
        for m in markings
    ]
    return BodyCanonRead(character_id=character_id, markings=items)
