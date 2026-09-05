"""
Candidate slot replacement service — Identity Evolution Phase 2.

Provides create / validate / promote / reject operations for proposed
slot image replacements. Promotion always takes a snapshot first, then
writes the new url into identity_anchor_json["anchors"][slot] while
preserving accessories and all other anchor slots.
"""
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.storage import load_image_bytes, save_image
from app.models.candidate_slot import CandidateSlot, VALID_SLOTS
from app.models.character import Character
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.services.identity_evolution import (
    IMMUTABLE_CANON_FIELDS,
    take_snapshot,
)

logger = logging.getLogger(__name__)

# Hair fields that become stale after a visual slot promotion.
# Clearing them lets the new anchor images drive hairstyle; color is preserved.
_STALE_HAIR_FIELDS = frozenset({"hair_length", "hair_style", "hair_texture", "hairline_type"})


# ── Create ────────────────────────────────────────────────────────────────────

def create_candidate(
    db: Session,
    character: Character,
    slot: str,
    image_url: str,
) -> CandidateSlot:
    candidate = CandidateSlot(
        character_id=character.id,
        slot=slot,
        image_url=image_url,
        status="candidate",
        validation_status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


# ── Validate ──────────────────────────────────────────────────────────────────

def validate_candidate(
    db: Session,
    character: Character,
    candidate: CandidateSlot,
) -> CandidateSlot:
    """
    Run v1 validation checks against the candidate.

    Checks:
    1. Character must be locked (guard enforced upstream, but double-checked).
    2. Candidate must have an image_url.
    3. Slot name must be valid.
    4. Compare immutable text/spec fields if identity_spec_json is present.
    5. Placeholder hook for face embedding similarity (Phase 3).
    6. Warn if candidate slot has no matching anchor in existing identity_anchor_json.

    Sets validation_status and validation_notes on the candidate, then commits.
    """
    notes: list[str] = []
    ok = True

    # 1. Character lock (upstream guard guarantees this, but belt-and-suspenders)
    if not character.visual_locked:
        candidate.validation_status = "invalid"
        candidate.validation_notes = "Character is not locked."
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
        return candidate

    # 2. Image URL present
    if not candidate.image_url:
        notes.append("No candidate image URL provided.")
        ok = False

    # 3. Slot validity
    if candidate.slot not in VALID_SLOTS:
        notes.append(f"Unknown slot '{candidate.slot}'. Must be one of {sorted(VALID_SLOTS)}.")
        ok = False

    # 4. Spec immutable field check — warn if spec available and a mutable field changed
    if character.identity_spec_json:
        try:
            spec = json.loads(character.identity_spec_json)
            immutable_present = [
                f for f in IMMUTABLE_CANON_FIELDS
                if _resolve_field(spec, f) is not None
            ]
            if immutable_present:
                notes.append(
                    f"Immutable spec fields present ({len(immutable_present)} fields). "
                    "Promotion will not alter them — only the slot image URL is replaced."
                )
        except (json.JSONDecodeError, TypeError):
            notes.append("identity_spec_json is present but could not be parsed.")

    # 5. Face embedding similarity placeholder
    notes.append(
        "Face embedding similarity check: not yet implemented (Phase 3). "
        "Manual review recommended."
    )

    # 6. Slot presence in existing anchor
    existing_slot_url = _get_existing_slot_url(character.identity_anchor_json, candidate.slot)
    if existing_slot_url is None:
        notes.append(
            f"Slot '{candidate.slot}' has no existing anchor image. "
            "Promotion will create it for the first time."
        )

    # Determine final validation_status
    if not ok:
        validation_status = "invalid"
    elif any("not yet implemented" in n or "recommended" in n for n in notes):
        validation_status = "warning"
    else:
        validation_status = "valid"

    candidate.validation_status = validation_status
    candidate.validation_notes = "; ".join(notes) if notes else None
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


# ── Promote ───────────────────────────────────────────────────────────────────

def promote_candidate(
    db: Session,
    character: Character,
    candidate: CandidateSlot,
):
    """
    Promote a candidate slot replacement into the character's live identity_anchor_json.

    Steps:
    1. Reject if candidate is not in 'candidate' status.
    2. Reject if validation_status is 'invalid'.
    3. Take a snapshot (reason="pre_evolution").
    4. Parse identity_anchor_json.
    5. Replace only anchors[slot].url — preserve accessories and all other slots.
    6. Persist updated identity_anchor_json.
    7. Set candidate status="promoted".

    Returns (snapshot, updated_candidate).
    """
    if candidate.status != "candidate":
        raise ValueError(f"Candidate is already {candidate.status}.")
    if candidate.validation_status == "invalid":
        raise ValueError("Cannot promote an invalid candidate. Run validation first.")

    # Snapshot before any mutation
    snapshot = take_snapshot(db, character, reason="pre_evolution")

    # Parse and mutate anchor JSON
    anchor_data = _parse_anchor_json(character.identity_anchor_json)
    anchors = anchor_data.setdefault("anchors", {})
    existing = anchors.get(candidate.slot) or {}
    existing["url"] = candidate.image_url
    anchors[candidate.slot] = existing
    anchor_data["anchors"] = anchors

    # Recompile identity text canon so stale hair descriptors no longer drive generation.
    # Best-effort: failure leaves anchor_data unchanged rather than blocking promotion.
    _recompile_identity_canon(character, anchor_data)

    character.identity_anchor_json = json.dumps(anchor_data)
    character.updated_at = datetime.utcnow()
    db.add(character)

    candidate.status = "promoted"
    db.add(candidate)

    db.commit()
    db.refresh(candidate)

    # Refresh the face-reference crop when the front anchor is replaced.
    # Best-effort: failure is logged but does not roll back the promotion.
    if candidate.slot == "front":
        try:
            _refresh_face_ref(db, character, candidate)
            db.commit()
        except Exception as _exc:
            db.rollback()
            logger.warning(
                "promote_candidate: face_ref refresh failed character_id=%s error=%s",
                character.id, _exc,
            )

    return snapshot, candidate


# ── Reject ────────────────────────────────────────────────────────────────────

def reject_candidate(
    db: Session,
    candidate: CandidateSlot,
) -> CandidateSlot:
    if candidate.status != "candidate":
        raise ValueError(f"Candidate is already {candidate.status}.")
    candidate.status = "rejected"
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


# ── Promotion helpers ─────────────────────────────────────────────────────────

def _recompile_identity_canon(character: Character, anchor_data: dict) -> None:
    """Clear stale hair fields from identity_spec_json and recompile the lock string.

    Called after a slot URL is updated so the text canon matches the new visuals.
    Mutates character.identity_spec_json and anchor_data in-place.
    """
    if not character.identity_spec_json:
        return
    try:
        spec_dict = json.loads(character.identity_spec_json)
    except (json.JSONDecodeError, TypeError):
        return

    # Remove stale hair fields at both spec root and nested identity sub-object
    for _f in _STALE_HAIR_FIELDS:
        spec_dict.pop(_f, None)
        if isinstance(spec_dict.get("identity"), dict):
            spec_dict["identity"].pop(_f, None)
    character.identity_spec_json = json.dumps(spec_dict)

    try:
        from app.schemas.character_visual import CharacterIdentitySpec
        from app.services.identity_compiler import (
            compile_identity_lock_string,
            identity_prompt_hash as _compute_hash,
        )
        spec_obj = CharacterIdentitySpec(**spec_dict)
        anchor_data["identity_lock_string"] = compile_identity_lock_string(spec_obj)
        anchor_data["identity_prompt_hash"] = _compute_hash(spec_obj)
    except Exception as _exc:
        logger.warning(
            "_recompile_identity_canon: lock string recompile failed character_id=%s error=%s",
            character.id, _exc,
        )


def _refresh_face_ref(db: Session, character: Character, candidate: CandidateSlot) -> None:
    """Archive the stale IDENTITY_FACE_REF and create a new one from the promoted front anchor."""
    old_refs = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character.id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )
    for ref in old_refs:
        ref.status = ImageStatusEnum.ARCHIVED
        db.add(ref)

    raw_bytes = load_image_bytes(candidate.image_url)
    cropped = _crop_face_ref(raw_bytes)
    face_ref_path = save_image(cropped)

    db.add(CharacterImage(
        character_id=character.id,
        # Service-level writer: the owner is derived once, here, from the
        # character this function was handed. No requester is in scope and none
        # is wanted — ownership is not "who triggered the promotion".
        user_id=character.owner_id,
        kind=ImageKindEnum.IDENTITY_FACE_REF,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        prompt_summary="face reference crop",
        metadata_json={
            "source": "evolution_promote",
            "candidate_id": candidate.id,
            "is_temp": False,
        },
        file_path=face_ref_path,
    ))
    logger.info(
        "promote_candidate: face_ref refreshed character_id=%s candidate_id=%s",
        character.id, candidate.id,
    )


def _crop_face_ref(png_bytes: bytes) -> bytes:
    """Crop a tight face region (x=20-80%, y=5-60%) resized to 512×512."""
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(png_bytes)) as img:
            w, h = img.size
            left, right = int(w * 0.20), int(w * 0.80)
            top, bottom = int(h * 0.05), int(h * 0.60)
            if right <= left or bottom <= top:
                return png_bytes
            resized = img.crop((left, top, right, bottom)).resize((512, 512), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return png_bytes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_anchor_json(identity_anchor_json) -> dict:
    if identity_anchor_json:
        try:
            return json.loads(identity_anchor_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _get_existing_slot_url(identity_anchor_json, slot: str):
    data = _parse_anchor_json(identity_anchor_json)
    anchors = data.get("anchors") or {}
    entry = anchors.get(slot)
    if entry and entry.get("url"):
        return entry["url"]
    return None


def _resolve_field(spec: dict, key: str):
    if key in spec:
        return spec[key]
    identity = spec.get("identity", {})
    if isinstance(identity, dict) and key in identity:
        return identity[key]
    return None
