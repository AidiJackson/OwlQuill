"""Body Identity References — canonical source of truth for body/marking generation.

get_body_identity_references(character) is the single entry point for scene
generation to resolve which body identity images are available for a character.

GENERATION CONTRACT (image generation priority order when include_character=True):
  1. Face identity refs   — front, three_quarter  (loaded by _prioritise_face_anchors)
  2. Body identity refs   — returned by this module, in priority order below
  3. Support refs         — accessories, etc.
  4. Prompt text          — FALLBACK ONLY, not source of truth for body markings

Body identity ref priority order:
  1. body_front           PRIMARY — required when markings exist
  2. body_left_detail     left-side crop (high-fidelity marking ref)
  3. body_right_detail    right-side crop
  4. body_back            back view
  5. body_map             canonical placement sheet (falls back to tattoo_layout)
  6. final_character_card SUPPORT ONLY — always last, never overrides above

All refs come from identity_anchor_json["body_slots"][<key>] with status="locked".
final_character_card is also checked at identity_anchor_json["final_character_card"]
for backward compatibility with existing characters.
"""
import json
import logging
from dataclasses import dataclass, field

from app.models.character import Character as CharacterModel
from app.services.body_canon import load_markings

logger = logging.getLogger(__name__)

# ── Priority order ─────────────────────────────────────────────────────
# Ordered list of slots get_body_identity_references will return refs for.
# final_character_card is always last — it is support only.
BODY_IDENTITY_REF_PRIORITY = (
    "body_front",
    "body_left_detail",
    "body_right_detail",
    "body_back",
    "body_map",
    "final_character_card",
)

# Legacy slot that falls back to body_map position when body_map absent.
_BODY_MAP_LEGACY_FALLBACK = "tattoo_layout"

# Type strings used in _reorder_anchor_refs bucketing.
# These are passed as anchor_types entries in image_generator.py.
BODY_IDENTITY_REF_TYPES: dict[str, str] = {
    "body_front":            "body_identity:body_front",
    "body_left_detail":      "body_identity:body_left_detail",
    "body_right_detail":     "body_identity:body_right_detail",
    "body_back":             "body_identity:body_back",
    "body_map":              "body_identity:body_map",
    "tattoo_layout":         "body_identity:body_map",      # legacy maps to same type
    "final_character_card":  "final_character_card",        # support bucket
}


@dataclass
class BodyIdentityRef:
    """A single resolved body identity reference."""
    slot: str       # e.g. "body_front"
    url: str
    source: str     # where it was found: "body_slots_locked" | "legacy_final_card"
    ref_type: str   # anchor_types string: "body_identity:body_front" etc.


@dataclass
class BodyIdentityRefs:
    """Result of get_body_identity_references().

    refs:                   Ordered list of available locked refs. Empty when no markings
                            and no body identity pack exists.
    missing_required:       True when body markings exist but body_front is not locked.
                            Drives BODY_IDENTITY_MISSING warning in scene generation.
    body_identity_complete: True when body_front is present (minimum viable pack).
                            A complete pack has body_front locked; detail slots are bonus.
    has_markings:           True when the character has body markings (tattoos/scars/etc.)
    body_front_slot_status: Raw status string of body_front slot ("locked"|"generated"|"missing")
    """
    refs: list[BodyIdentityRef] = field(default_factory=list)
    missing_required: bool = False
    body_identity_complete: bool = False
    has_markings: bool = False
    body_front_slot_status: str = "missing"


def get_body_identity_references(character: CharacterModel) -> BodyIdentityRefs:
    """Return ordered body identity refs for scene generation.

    Reads identity_anchor_json["body_slots"] for locked slots.
    Checks identity_anchor_json["final_character_card"] as legacy fallback.

    Always logs BODY_IDENTITY_STATE with the resolved state.
    """
    char_id = getattr(character, "id", "?")
    markings = load_markings(character)
    has_markings = bool(markings)

    # Parse identity_anchor_json
    anchor_data: dict = {}
    if character.identity_anchor_json:
        try:
            anchor_data = json.loads(character.identity_anchor_json)
        except (ValueError, TypeError):
            anchor_data = {}

    body_slots: dict = anchor_data.get("body_slots") or {}

    # No markings, no body slots, and no legacy final_card → clean empty result
    _legacy_fc = anchor_data.get("final_character_card") or {}
    _has_any_refs = bool(body_slots) or (
        _legacy_fc.get("status") == "locked" and _legacy_fc.get("url")
    )
    if not has_markings and not _has_any_refs:
        logger.info(
            "BODY_IDENTITY_STATE character_id=%s has_markings=False "
            "body_slots_empty=True complete=False refs_found=0",
            char_id,
        )
        return BodyIdentityRefs(has_markings=False)

    refs: list[BodyIdentityRef] = []
    body_front_status = "missing"
    body_front_loaded = False

    # Walk priority order
    for slot in BODY_IDENTITY_REF_PRIORITY:
        if slot == "final_character_card":
            # Check body_slots first, then legacy top-level key
            entry = (body_slots.get("final_character_card") or
                     anchor_data.get("final_character_card") or {})
            source = (
                "body_slots_locked" if body_slots.get("final_character_card")
                else "legacy_final_card"
            )
        else:
            entry = body_slots.get(slot) or {}
            source = "body_slots_locked"

        if slot == "body_front":
            body_front_status = entry.get("status", "missing")

        if entry.get("status") == "locked" and entry.get("url"):
            ref_type = BODY_IDENTITY_REF_TYPES.get(slot, f"body_identity:{slot}")
            refs.append(BodyIdentityRef(
                slot=slot,
                url=entry["url"],
                source=source,
                ref_type=ref_type,
            ))
            if slot == "body_front":
                body_front_loaded = True

    # body_map fallback: if body_map absent, check legacy tattoo_layout
    has_body_map = any(r.slot == "body_map" for r in refs)
    if not has_body_map:
        tl_entry = body_slots.get(_BODY_MAP_LEGACY_FALLBACK) or {}
        if tl_entry.get("status") == "locked" and tl_entry.get("url"):
            refs.append(BodyIdentityRef(
                slot="tattoo_layout",
                url=tl_entry["url"],
                source="body_slots_locked",
                ref_type=BODY_IDENTITY_REF_TYPES["tattoo_layout"],
            ))

    # Determine completeness
    missing_required = has_markings and not body_front_loaded
    body_identity_complete = body_front_loaded

    logger.info(
        "BODY_IDENTITY_STATE character_id=%s has_markings=%s "
        "body_front_status=%s body_identity_complete=%s missing_required=%s "
        "refs_found=%d ref_slots=%s",
        char_id,
        has_markings,
        body_front_status,
        body_identity_complete,
        missing_required,
        len(refs),
        [r.slot for r in refs],
    )

    return BodyIdentityRefs(
        refs=refs,
        missing_required=missing_required,
        body_identity_complete=body_identity_complete,
        has_markings=has_markings,
        body_front_slot_status=body_front_status,
    )
