"""
Candidate Slot Replacement API — Identity Evolution Phase 2.

Endpoints for the controlled slot-replacement workflow:
  POST   /{character_id}/identity-evolution/candidate-slot          — create
  POST   /{character_id}/identity-evolution/candidate-slot/{id}/validate — validate
  POST   /{character_id}/identity-evolution/candidate-slot/{id}/promote  — promote
  POST   /{character_id}/identity-evolution/candidate-slot/{id}/reject   — reject

Promotion takes a snapshot before mutating identity_anchor_json so rollback
is always available via the existing snapshot endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.candidate_slot import CandidateSlot
from app.models.character import Character
from app.models.user import User
from app.schemas.candidate_slot import CandidateSlotCreate, CandidateSlotRead
from app.schemas.identity_snapshot import IdentitySnapshotRead
from app.services.candidate_slot import (
    create_candidate,
    validate_candidate,
    promote_candidate,
    reject_candidate,
)

router = APIRouter()


# ── Guards ────────────────────────────────────────────────────────────────────

def _require_own_locked_character(
    character_id: int,
    current_user: User,
    db: Session,
) -> Character:
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your character")
    if not character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Character identity is not locked. Lock an identity pack before using evolution features.",
        )
    return character


def _require_own_candidate(
    candidate_id: int,
    character: Character,
    db: Session,
) -> CandidateSlot:
    candidate = (
        db.query(CandidateSlot)
        .filter(
            CandidateSlot.id == candidate_id,
            CandidateSlot.character_id == character.id,
        )
        .first()
    )
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return candidate


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/{character_id}/identity-evolution/candidate-slot",
    response_model=CandidateSlotRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a candidate slot replacement",
)
def create_candidate_slot(
    character_id: int,
    payload: CandidateSlotCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSlot:
    """
    Propose an image URL as a replacement for a specific identity anchor slot.
    The candidate is created with status='candidate' and validation_status='pending'.
    Run /validate next to check it before promoting.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    return create_candidate(db, character, payload.slot, payload.image_url)


@router.post(
    "/{character_id}/identity-evolution/candidate-slot/{candidate_id}/validate",
    response_model=CandidateSlotRead,
    summary="Validate a candidate slot replacement",
)
def validate_candidate_slot(
    character_id: int,
    candidate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSlot:
    """
    Run v1 validation on the candidate:
    - Check character is locked and candidate image is present.
    - Compare immutable spec fields (text only; face embedding deferred to Phase 3).
    - Warn if slot has no existing anchor to replace.
    Sets validation_status on the candidate; does not mutate the character.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    candidate = _require_own_candidate(candidate_id, character, db)
    return validate_candidate(db, character, candidate)


@router.post(
    "/{character_id}/identity-evolution/candidate-slot/{candidate_id}/promote",
    summary="Promote a candidate into the live identity anchor",
)
def promote_candidate_slot(
    character_id: int,
    candidate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Promote the candidate to canon:
    1. Takes an automatic snapshot (rollback always available).
    2. Replaces only the selected slot's URL in identity_anchor_json.
    3. Preserves accessories and all other anchor slots.
    4. Marks candidate as promoted.

    Returns the snapshot record and the updated candidate.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    candidate = _require_own_candidate(candidate_id, character, db)

    try:
        snapshot, updated_candidate = promote_candidate(db, character, candidate)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return {
        "snapshot": IdentitySnapshotRead.model_validate(snapshot),
        "candidate": CandidateSlotRead.model_validate(updated_candidate),
    }


@router.post(
    "/{character_id}/identity-evolution/candidate-slot/{candidate_id}/reject",
    response_model=CandidateSlotRead,
    summary="Reject a candidate slot replacement",
)
def reject_candidate_slot(
    character_id: int,
    candidate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSlot:
    """Mark the candidate as rejected. No changes are made to the character."""
    character = _require_own_locked_character(character_id, current_user, db)
    candidate = _require_own_candidate(candidate_id, character, db)

    try:
        return reject_candidate(db, candidate)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
