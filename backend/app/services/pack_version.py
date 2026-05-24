"""Pack version tracking and identity health computation.

pack_version lives in identity_anchor_json["pack_version"] and is incremented
whenever identity canon changes (identity_spec mutation, body_canon mutation,
permanent style element mutation). It defaults to 1 if absent for backwards
compatibility — legacy characters without a pack_version are never false-positive.

Every anchor and body slot entry generated after this module was introduced
carries a "pack_version" key. Entries without that key are treated as current.
"""
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.character import Character as CharacterModel

logger = logging.getLogger(__name__)


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


def compute_identity_health(character: "CharacterModel") -> dict:
    """Compute identity health for face, body, and tattoo slots.

    Returns:
        {"face": "current"|"stale", "body": "current"|"stale", "tattoos": "current"|"stale"}

    Only entries that carry an explicit pack_version are staleness-checked.
    Missing pack_version (legacy entries) → treated as current, never stale.
    """
    _healthy = {"face": "current", "body": "current", "tattoos": "current"}

    if not character.identity_anchor_json:
        return _healthy

    try:
        data = json.loads(character.identity_anchor_json)
    except (ValueError, TypeError):
        return _healthy

    current_version = int(data.get("pack_version") or 1)

    # ── FACE: face anchors (front + three_quarter) ────────────────────
    anchors = data.get("anchors") or {}
    face_stale = False
    for key in ("front", "three_quarter"):
        entry = anchors.get(key) or {}
        anchor_version = entry.get("pack_version")
        # Only stale if pack_version is explicitly present and older than current
        if anchor_version is not None and int(anchor_version) < current_version:
            face_stale = True
            break

    # ── BODY: body slots (locked only) ───────────────────────────────
    body_slots = data.get("body_slots") or {}
    body_stale = False
    for key in ("body_front", "body_three_quarter", "body_back"):
        entry = body_slots.get(key) or {}
        if entry.get("status") == "locked":
            slot_version = entry.get("pack_version")
            if slot_version is not None and int(slot_version) < current_version:
                body_stale = True
                break

    # ── TATTOOS: tattoo_layout and body_front (both show markings) ────
    tattoo_stale = False
    for key in ("tattoo_layout", "body_front"):
        entry = body_slots.get(key) or {}
        if entry.get("status") == "locked":
            slot_version = entry.get("pack_version")
            if slot_version is not None and int(slot_version) < current_version:
                tattoo_stale = True
                break

    return {
        "face": "stale" if face_stale else "current",
        "body": "stale" if body_stale else "current",
        "tattoos": "stale" if tattoo_stale else "current",
    }
