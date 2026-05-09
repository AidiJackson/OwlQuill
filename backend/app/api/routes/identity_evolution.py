"""
Identity Evolution API — Phase 1 scaffolding.

Provides snapshot, list, rollback, and validation endpoints.
No generation is triggered here — this is the non-destructive foundation
layer that Phase 2 (live refresh generation) will build on top of.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.character import Character
from app.models.identity_snapshot import IdentitySnapshot
from app.models.user import User
from app.schemas.identity_snapshot import IdentitySnapshotRead
from app.services.identity_evolution import (
    take_snapshot,
    rollback_to_snapshot,
    validate_evolution_spec,
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/{character_id}/identity-evolution/snapshots",
    response_model=List[IdentitySnapshotRead],
    summary="List identity snapshots",
)
def list_snapshots(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[IdentitySnapshot]:
    """List all identity snapshots for this character, newest first."""
    character = _require_own_locked_character(character_id, current_user, db)
    return (
        db.query(IdentitySnapshot)
        .filter(IdentitySnapshot.character_id == character.id)
        .order_by(IdentitySnapshot.created_at.desc())
        .all()
    )


@router.post(
    "/{character_id}/identity-evolution/snapshot",
    response_model=IdentitySnapshotRead,
    status_code=status.HTTP_201_CREATED,
    summary="Take a manual identity snapshot",
)
def create_snapshot(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IdentitySnapshot:
    """Manually capture the current identity state for safekeeping."""
    character = _require_own_locked_character(character_id, current_user, db)
    return take_snapshot(db, character, reason="manual_backup")


@router.post(
    "/{character_id}/identity-evolution/rollback/{snapshot_id}",
    response_model=IdentitySnapshotRead,
    summary="Rollback to a prior identity snapshot",
)
def rollback_identity(
    character_id: int,
    snapshot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IdentitySnapshot:
    """
    Restore identity_anchor_json and identity_spec_json from a snapshot.
    Does not touch visual_locked or CharacterImage records.
    Image history is preserved — the character retains all prior images.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    snapshot = (
        db.query(IdentitySnapshot)
        .filter(
            IdentitySnapshot.id == snapshot_id,
            IdentitySnapshot.character_id == character.id,
        )
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    rollback_to_snapshot(db, character, snapshot)
    return snapshot


@router.post(
    "/{character_id}/identity-evolution/validate",
    summary="Validate a proposed evolution spec (Phase 1: dry-run only)",
)
def validate_evolution(
    character_id: int,
    proposed_spec: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Check whether a proposed spec change would violate immutable canon fields.
    Returns validation result only — no generation is triggered.

    Phase 2 will chain this gate into the actual refresh pipeline before
    any images are generated.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    result = validate_evolution_spec(character.identity_spec_json, proposed_spec)
    return {
        "ok": result.ok,
        "immutable_violations": result.immutable_violations,
        "mutable_changes": result.mutable_changes,
        "message": result.message,
    }
