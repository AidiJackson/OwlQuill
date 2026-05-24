"""Pack version tracking, slot invalidation, and identity health computation.

pack_version lives in identity_anchor_json["pack_version"] and is incremented
whenever identity canon changes (identity_spec mutation, body_canon mutation,
permanent style element mutation). It defaults to 1 if absent for backwards
compatibility — legacy characters without a pack_version are never false-positive.

Every anchor and body slot entry generated after this module was introduced
carries a "pack_version" key. Entries without that key are treated as current.

Slot invalidation (Part B):
  mark_slots_stale() sets "stale": True inside individual anchor/slot entries
  based on mutation reason. Unaffected entries are "caught up" to the current
  pack_version so they do not false-positive on the version-mismatch check.
  Only existing entries are ever touched — URLs and status are never cleared.

Health computation priority (Part B):
  1. stale=True flag (explicit invalidation) → stale. Highest priority.
  2. pack_version mismatch (entry older than root) → stale.
  3. No pack_version and no stale flag (legacy) → current.
"""
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.character import Character as CharacterModel

logger = logging.getLogger(__name__)

# ── Placement scope classification ────────────────────────────────────
# Used by mark_slots_stale to determine which identity domains a permanent
# style element affects based on where it sits on the body.

_FACE_PLACEMENTS = frozenset({"face", "lower_face", "hair", "neck", "custom"})
_BODY_PLACEMENTS = frozenset({"right_arm", "left_arm", "chest", "back", "hand", "neck", "custom"})


# ── Internal helper ───────────────────────────────────────────────────

def _entry_is_stale(entry: dict, current_version: int) -> bool:
    """True if an anchor/slot entry is considered stale.

    Priority:
    1. Explicit stale=True flag (set by mark_slots_stale) — always wins.
    2. pack_version mismatch — entry version < current root version.
    3. No pack_version and no stale flag (legacy) → treated as current.
    """
    if entry.get("stale") is True:
        return True
    slot_version = entry.get("pack_version")
    if slot_version is not None and int(slot_version) < current_version:
        return True
    return False


def _catchup(d: dict, key: str, current_version: int) -> bool:
    """Advance pack_version of an existing, non-stale entry to current_version.

    Prevents false-positive staleness on entries that were NOT affected by the
    current mutation but whose pack_version is older than the new root version.

    Returns True if any change was made.
    """
    if key not in d:
        return False
    entry = d[key]
    # Never catch up entries already explicitly marked stale by a prior mutation
    if entry.get("stale") is True:
        return False
    if entry.get("pack_version") != current_version:
        entry["pack_version"] = current_version
        return True
    return False


# ── Public API ────────────────────────────────────────────────────────

def get_pack_version(character: "CharacterModel") -> int:
    """Return the current pack_version. Defaults to 1 if absent (backwards compatible)."""
    if not character.identity_anchor_json:
        return 1
    try:
        data = json.loads(character.identity_anchor_json)
        return int(data.get("pack_version") or 1)
    except (ValueError, TypeError):
        return 1


def increment_pack_version(character: "CharacterModel", *, reason: str = "") -> int:
    """Increment pack_version in identity_anchor_json. Returns new version.

    Safe to call before identity_anchor_json is initialised — creates the root dict.
    Does NOT commit; caller must db.commit() after all mutations are complete.
    """
    if character.identity_anchor_json:
        try:
            data = json.loads(character.identity_anchor_json)
        except (ValueError, TypeError):
            data = {}
    else:
        data = {}

    current = int(data.get("pack_version") or 1)
    new_version = current + 1
    data["pack_version"] = new_version
    character.identity_anchor_json = json.dumps(data)

    logger.info(
        "PACK-VERSION character_id=%s version=%s reason=%s",
        character.id,
        new_version,
        reason,
    )
    return new_version


def mark_slots_stale(
    character: "CharacterModel",
    reason: str,
    *,
    placement: str | None = None,
) -> list[str]:
    """Mark relevant anchor/slot entries with stale=True based on mutation reason.

    Unaffected entries are "caught up" to the new current pack_version so they
    do not false-positive on the version-mismatch check in compute_identity_health.

    Rules:
    - identity_spec_mutation: face anchors (front, three_quarter) + body_front,
      body_three_quarter marked stale. tattoo_layout caught up (unaffected).
    - body_canon_mutation: body_front + tattoo_layout marked stale.
      Face anchors caught up (unaffected).
    - permanent_style_element: scope derived from placement.
        face/lower_face/hair/neck/custom → face anchors stale.
        right_arm/left_arm/chest/back/hand/neck/custom → body_front, body_three_quarter stale.
        tattoo_layout always caught up (never affected by wearable elements).

    Only marks EXISTING entries — never creates entries or clears URLs/status.
    Catch-up never clears an entry already explicitly marked stale=True.
    Returns list of invalidated slot names for diagnostic logging.
    Does NOT commit; caller must db.commit() after all mutations are complete.
    """
    if not character.identity_anchor_json:
        return []
    try:
        data = json.loads(character.identity_anchor_json)
    except (ValueError, TypeError):
        return []

    current_version = int(data.get("pack_version") or 1)
    anchors: dict = data.get("anchors") or {}
    body_slots: dict = data.get("body_slots") or {}
    invalidated: list[str] = []
    _changed = False

    if reason == "identity_spec_mutation":
        # Hair/barber: face anchors + body references become outdated
        for key in ("front", "three_quarter"):
            if key in anchors:
                anchors[key]["stale"] = True
                invalidated.append(f"anchor:{key}")
                _changed = True
        for key in ("body_front", "body_three_quarter"):
            if key in body_slots:
                body_slots[key]["stale"] = True
                invalidated.append(key)
                _changed = True
        # Catch-up: tattoo_layout unaffected by hair mutation
        if _catchup(body_slots, "tattoo_layout", current_version):
            _changed = True

    elif reason == "body_canon_mutation":
        # Tattoo/scar: body reference and tattoo layout become outdated
        for key in ("body_front", "tattoo_layout"):
            if key in body_slots:
                body_slots[key]["stale"] = True
                invalidated.append(key)
                _changed = True
        # Catch-up: face anchors unaffected by tattoo/scar mutation
        for key in ("front", "three_quarter"):
            if _catchup(anchors, key, current_version):
                _changed = True

    elif reason == "permanent_style_element":
        placement_str = (placement or "").lower()
        face_affected = placement_str in _FACE_PLACEMENTS
        body_affected = placement_str in _BODY_PLACEMENTS

        if face_affected:
            for key in ("front", "three_quarter"):
                if key in anchors:
                    anchors[key]["stale"] = True
                    invalidated.append(f"anchor:{key}")
                    _changed = True
        else:
            for key in ("front", "three_quarter"):
                if _catchup(anchors, key, current_version):
                    _changed = True

        if body_affected:
            for key in ("body_front", "body_three_quarter"):
                if key in body_slots:
                    body_slots[key]["stale"] = True
                    invalidated.append(key)
                    _changed = True
        else:
            for key in ("body_front", "body_three_quarter"):
                if _catchup(body_slots, key, current_version):
                    _changed = True

        # tattoo_layout is never affected by wearable style elements
        if _catchup(body_slots, "tattoo_layout", current_version):
            _changed = True

    if _changed:
        data["anchors"] = anchors
        data["body_slots"] = body_slots
        character.identity_anchor_json = json.dumps(data)

    if invalidated:
        logger.info(
            "IDENTITY-STALE character_id=%s reason=%s invalidated=%s",
            character.id,
            reason,
            invalidated,
        )

    return invalidated


def compute_identity_health(character: "CharacterModel") -> dict:
    """Compute identity health for face, body, and tattoo slots.

    Returns:
        {
          "face":    "current"|"stale",
          "body":    "current"|"stale",
          "tattoos": "current"|"stale",
          "slots":   {slot_key: {"stale": bool}, ...}  # only existing slots
        }

    Staleness priority per entry:
    1. stale=True flag (explicit invalidation) — highest priority.
    2. pack_version mismatch — entry version older than root version.
    3. No pack_version and no stale flag → current (legacy compatibility).

    Only LOCKED body slots contribute to top-level body/tattoo health.
    """
    _healthy: dict = {"face": "current", "body": "current", "tattoos": "current", "slots": {}}

    if not character.identity_anchor_json:
        return _healthy

    try:
        data = json.loads(character.identity_anchor_json)
    except (ValueError, TypeError):
        return _healthy

    current_version = int(data.get("pack_version") or 1)
    anchors: dict = data.get("anchors") or {}
    body_slots: dict = data.get("body_slots") or {}
    slots_detail: dict = {}

    # ── FACE: face anchors (front + three_quarter) ────────────────────
    face_stale = False
    for key in ("front", "three_quarter"):
        entry = anchors.get(key)
        if entry is not None:
            stale = _entry_is_stale(entry, current_version)
            slots_detail[key] = {"stale": stale}
            if stale:
                face_stale = True

    # ── BODY: locked body slots ───────────────────────────────────────
    body_stale = False
    for key in ("body_front", "body_three_quarter", "body_back"):
        entry = body_slots.get(key)
        if entry is not None:
            stale = _entry_is_stale(entry, current_version)
            slots_detail[key] = {"stale": stale}
            if stale and entry.get("status") == "locked":
                body_stale = True

    # ── TATTOOS: tattoo_layout + body_front (both carry marking data) ─
    tattoo_stale = False
    tl_entry = body_slots.get("tattoo_layout")
    if tl_entry is not None:
        stale = _entry_is_stale(tl_entry, current_version)
        slots_detail["tattoo_layout"] = {"stale": stale}
        if stale and tl_entry.get("status") == "locked":
            tattoo_stale = True
    # body_front already processed above; check for tattoo domain
    if not tattoo_stale:
        bf_entry = body_slots.get("body_front")
        if bf_entry is not None and bf_entry.get("status") == "locked":
            if _entry_is_stale(bf_entry, current_version):
                tattoo_stale = True

    return {
        "face": "stale" if face_stale else "current",
        "body": "stale" if body_stale else "current",
        "tattoos": "stale" if tattoo_stale else "current",
        "slots": slots_detail,
    }
