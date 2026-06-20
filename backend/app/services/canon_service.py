"""Canon service — CRUD operations on CharacterIdentityCanon.

Single source of truth for a character's face, body, and accessory canon.
All writes go through this service. Reads are clean JSON deserialization.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import (
    AddAccessoryRequest,
    AddPermanentMarkRequest,
    BodyCanonData,
    BodyCanonUpdate,
    FaceCanonData,
    FaceCanonUpdate,
    PermanentBodyMark,
    RemovableAccessory,
    SLOT_FIELD_MAP,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Load helpers ──────────────────────────────────────────────────────

def load_face_canon(canon: CharacterIdentityCanon) -> Optional[FaceCanonData]:
    if not canon.face_canon_json:
        return None
    try:
        return FaceCanonData(**json.loads(canon.face_canon_json))
    except (ValueError, TypeError):
        logger.warning("canon_load_face_failed character_id=%s", canon.character_id)
        return None


def load_body_canon(canon: CharacterIdentityCanon) -> Optional[BodyCanonData]:
    if not canon.body_canon_json:
        return None
    try:
        return BodyCanonData(**json.loads(canon.body_canon_json))
    except (ValueError, TypeError):
        logger.warning("canon_load_body_failed character_id=%s", canon.character_id)
        return None


def load_accessories(canon: CharacterIdentityCanon) -> list[RemovableAccessory]:
    if not canon.accessories_json:
        return []
    try:
        raw = json.loads(canon.accessories_json)
        return [RemovableAccessory(**a) for a in raw]
    except (ValueError, TypeError):
        logger.warning("canon_load_accessories_failed character_id=%s", canon.character_id)
        return []


# ── Save helpers ──────────────────────────────────────────────────────

def _save_face(canon: CharacterIdentityCanon, face: FaceCanonData) -> None:
    canon.face_canon_json = json.dumps(face.model_dump())


def _save_body(canon: CharacterIdentityCanon, body: BodyCanonData) -> None:
    canon.body_canon_json = json.dumps(body.model_dump())


def _save_accessories(canon: CharacterIdentityCanon, accs: list[RemovableAccessory]) -> None:
    canon.accessories_json = json.dumps([a.model_dump() for a in accs])


# ── Get or create ─────────────────────────────────────────────────────

def get_or_create_canon(character_id: int, db: "Session") -> CharacterIdentityCanon:
    """Return the canon record for a character, creating it if absent."""
    canon = db.query(CharacterIdentityCanon).filter(
        CharacterIdentityCanon.character_id == character_id
    ).first()
    if canon is None:
        canon = CharacterIdentityCanon(character_id=character_id)
        db.add(canon)
        db.flush()
        logger.info("canon_created character_id=%s", character_id)
    return canon


# ── Face canon operations ─────────────────────────────────────────────

def update_face_canon(
    canon: CharacterIdentityCanon,
    patch: FaceCanonUpdate,
) -> FaceCanonData:
    """Apply patch fields to face canon. Returns updated FaceCanonData."""
    face = load_face_canon(canon) or FaceCanonData()
    data = patch.model_dump(exclude_none=True)
    updated = face.model_copy(update=data)
    _save_face(canon, updated)
    return updated


def lock_face_canon(canon: CharacterIdentityCanon) -> FaceCanonData:
    """Lock face canon. Requires face_front_image_url to be set."""
    face = load_face_canon(canon) or FaceCanonData()
    if not face.face_front_image_url:
        raise ValueError("face_front_image_url is required to lock face canon")
    face = face.model_copy(update={"locked": True})
    _save_face(canon, face)
    canon.face_locked = True
    canon.face_locked_at = datetime.utcnow()
    _maybe_lock_full_canon(canon)
    return face


# ── Body canon operations ─────────────────────────────────────────────

def update_body_canon(
    canon: CharacterIdentityCanon,
    patch: BodyCanonUpdate,
) -> BodyCanonData:
    """Apply patch fields to body canon anatomy. Returns updated BodyCanonData."""
    body = load_body_canon(canon) or BodyCanonData()
    data = patch.model_dump(exclude_none=True)
    updated = body.model_copy(update=data)
    _save_body(canon, updated)
    return updated


def add_permanent_mark(
    canon: CharacterIdentityCanon,
    req: AddPermanentMarkRequest,
) -> PermanentBodyMark:
    """Add a permanent body mark to body canon. Returns the new mark."""
    body = load_body_canon(canon) or BodyCanonData()
    mark = PermanentBodyMark(**req.model_dump())
    body.permanent_body_marks.append(mark)
    _save_body(canon, body)
    logger.info(
        "canon_mark_added character_id=%s mark_id=%s type=%s region=%s",
        canon.character_id, mark.id, mark.type, mark.body_region,
    )
    return mark


def remove_permanent_mark(canon: CharacterIdentityCanon, mark_id: str) -> bool:
    """Remove a permanent body mark by id. Returns True if found and removed."""
    body = load_body_canon(canon)
    if not body:
        return False
    before = len(body.permanent_body_marks)
    body.permanent_body_marks = [m for m in body.permanent_body_marks if m.id != mark_id]
    if len(body.permanent_body_marks) == before:
        return False
    _save_body(canon, body)
    logger.info("canon_mark_removed character_id=%s mark_id=%s", canon.character_id, mark_id)
    return True


def lock_body_canon(canon: CharacterIdentityCanon) -> BodyCanonData:
    """Lock body canon. Requires body_front_image_url to be set."""
    body = load_body_canon(canon) or BodyCanonData()
    if not body.body_front_image_url:
        raise ValueError("body_front_image_url is required to lock body canon")
    body = body.model_copy(update={"locked": True})
    _save_body(canon, body)
    canon.body_locked = True
    canon.body_locked_at = datetime.utcnow()
    _maybe_lock_full_canon(canon)
    return body


# ── Accessory operations ──────────────────────────────────────────────

def add_accessory(
    canon: CharacterIdentityCanon,
    req: AddAccessoryRequest,
) -> RemovableAccessory:
    """Add a removable accessory. Returns the new accessory."""
    accs = load_accessories(canon)
    acc = RemovableAccessory(**req.model_dump())
    accs.append(acc)
    _save_accessories(canon, accs)
    logger.info(
        "canon_accessory_added character_id=%s acc_id=%s type=%s",
        canon.character_id, acc.id, acc.type,
    )
    return acc


def remove_accessory(canon: CharacterIdentityCanon, acc_id: str) -> bool:
    """Remove accessory by id. Returns True if found and removed."""
    accs = load_accessories(canon)
    before = len(accs)
    accs = [a for a in accs if a.id != acc_id]
    if len(accs) == before:
        return False
    _save_accessories(canon, accs)
    logger.info("canon_accessory_removed character_id=%s acc_id=%s", canon.character_id, acc_id)
    return True


# ── Admin upload ──────────────────────────────────────────────────────

def assign_canon_slot_image(
    canon: CharacterIdentityCanon,
    slot: str,
    image_url: str,
) -> None:
    """Assign an uploaded image URL to a canon slot.

    slot must be a key in SLOT_FIELD_MAP (face_front, body_front, etc.).
    """
    if slot not in SLOT_FIELD_MAP:
        raise ValueError(f"Unknown canon slot: {slot!r}")

    section, field = SLOT_FIELD_MAP[slot]
    if section == "face":
        face = load_face_canon(canon) or FaceCanonData()
        face = face.model_copy(update={field: image_url})
        _save_face(canon, face)
    elif section == "body":
        body = load_body_canon(canon) or BodyCanonData()
        body = body.model_copy(update={field: image_url})
        _save_body(canon, body)

    logger.info(
        "canon_slot_assigned character_id=%s slot=%s url=%s",
        canon.character_id, slot, image_url,
    )


def assign_mark_reference_image(
    canon: CharacterIdentityCanon,
    mark_id: str,
    image_url: str,
) -> bool:
    """Assign a reference image to a specific permanent body mark."""
    return _assign_mark_image_field(canon, mark_id, "reference_image_url", image_url)


def assign_mark_detail_crop(
    canon: CharacterIdentityCanon,
    mark_id: str,
    image_url: str,
) -> bool:
    """Assign a high-fidelity close-up detail crop to a permanent body mark.

    The detail crop captures the mark's exact geometry/lettering and is the
    preferred fidelity reference routed when the mark's region is exposed.
    """
    return _assign_mark_image_field(canon, mark_id, "detail_crop_url", image_url)


def _assign_mark_image_field(
    canon: CharacterIdentityCanon,
    mark_id: str,
    field: str,
    image_url: str,
) -> bool:
    """Set one image-URL field on a permanent mark by id. Returns True if found."""
    body = load_body_canon(canon)
    if not body:
        return False
    for i, m in enumerate(body.permanent_body_marks):
        if m.id == mark_id:
            body.permanent_body_marks[i] = m.model_copy(update={field: image_url})
            _save_body(canon, body)
            logger.info(
                "canon_mark_image_assigned character_id=%s mark_id=%s field=%s url=%s",
                canon.character_id, mark_id, field, image_url,
            )
            return True
    return False


def assign_accessory_image(
    canon: CharacterIdentityCanon,
    acc_id: str,
    slot: str,  # "design" or "fit"
    image_url: str,
) -> bool:
    """Assign a design or fit reference image to an accessory."""
    accs = load_accessories(canon)
    field = "design_anchor_image_url" if slot == "design" else "fit_anchor_image_url"
    for i, a in enumerate(accs):
        if a.id == acc_id:
            accs[i] = a.model_copy(update={field: image_url})
            _save_accessories(canon, accs)
            logger.info(
                "canon_acc_image_assigned character_id=%s acc_id=%s slot=%s",
                canon.character_id, acc_id, slot,
            )
            return True
    return False


# ── Internal ──────────────────────────────────────────────────────────

def _maybe_lock_full_canon(canon: CharacterIdentityCanon) -> None:
    if canon.face_locked and canon.body_locked:
        canon.status = "locked"
        canon.locked_at = datetime.utcnow()
        # Compatibility flag (S24AU.2): scene/image generation guards gate on
        # Character.visual_locked, but the v2 canon lock only writes the canon
        # *_locked fields. Mirror the fully-locked canon onto the character so a
        # v2-locked character can generate scenes. Single source of truth: this
        # runs from both lock_face_canon and lock_body_canon.
        if canon.character is not None:
            canon.character.visual_locked = True
        logger.info("canon_fully_locked character_id=%s", canon.character_id)
