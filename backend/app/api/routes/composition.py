"""Composition session routes — shared editor infrastructure.

Opening a session is how an editor tells the server "someone is writing here".
Provenance redeems it; autosave, revision history and writing analytics are
expected to use the same three endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.composition import (
    SessionOpenRequest,
    SessionRead,
    SessionUpdateRequest,
)
from app.services import composition as composition_service

router = APIRouter()


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def open_session(
    body: SessionOpenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    """Open a composition session for the caller."""
    if body.surface not in composition_service.KNOWN_SURFACES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown composition surface '{body.surface}'.",
        )

    session = composition_service.open_session(
        db,
        user_id=current_user.id,
        surface=body.surface,
        target_kind=body.target_kind,
        target_ref=body.target_ref,
        parent_session_id=body.continues_session_id,
    )
    db.commit()
    db.refresh(session)
    return SessionRead.from_session(session)


@router.patch("/sessions/{session_id}", response_model=SessionRead)
def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    """Report editing counters. Idempotent — last write wins.

    404 for a session the caller does not own, so session ids cannot be probed.
    """
    session = composition_service.get_owned_session(
        db, user_id=current_user.id, session_id=session_id
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    composition_service.update_metrics(db, session, body.metrics.model_dump())
    db.commit()
    db.refresh(session)
    return SessionRead.from_session(session)


@router.get("/sessions/{session_id}", response_model=SessionRead)
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    """Fetch a session the caller owns."""
    session = composition_service.get_owned_session(
        db, user_id=current_user.id, session_id=session_id
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return SessionRead.from_session(session)
