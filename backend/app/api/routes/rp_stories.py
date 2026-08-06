"""RP Story Thread routes.

Routes
------
POST   /rp-stories                              Create thread from partner starter
GET    /rp-stories                              List user's threads
GET    /rp-stories/{thread_id}                  Thread + turns
POST   /rp-stories/{thread_id}/partner-turn     Add next partner reply
POST   /rp-stories/{thread_id}/generate-reply   Generate selected character reply (draft)
POST   /rp-stories/{thread_id}/save-generated-turn  Save accepted reply
PATCH  /rp-stories/{thread_id}/archive          Archive thread
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.entitlements import require_creator
from app.models.character import Character as CharacterModel
from app.models.rp_story import RPStoryThread, RPStoryTurn
from app.models.user import User
from app.schemas.rp_story import (
    AddPartnerTurnRequest,
    CreateRPStoryRequest,
    GenerateThreadReplyRequest,
    GenerateThreadReplyResponse,
    RPStoryThreadDetail,
    RPStoryThreadOut,
    RPStoryTurnOut,
    SaveGeneratedTurnRequest,
)
from app.models.provenance import Provenance
from app.services.provenance import decide_provenance, external_import, register_ai_output
from app.services.rp_story_service import (
    _auto_title,
    append_lightweight_summary,
    generate_thread_reply,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_thread_or_404(thread_id: int, user_id: int, db: Session) -> RPStoryThread:
    thread = db.query(RPStoryThread).filter(RPStoryThread.id == thread_id).first()
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if thread.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return thread


def _next_turn_index(thread_id: int, db: Session) -> int:
    last = (
        db.query(RPStoryTurn)
        .filter(RPStoryTurn.thread_id == thread_id)
        .order_by(RPStoryTurn.turn_index.desc())
        .first()
    )
    return (last.turn_index + 1) if last else 1


def _thread_to_out(thread: RPStoryThread, db: Session) -> RPStoryThreadOut:
    count = db.query(RPStoryTurn).filter(RPStoryTurn.thread_id == thread.id).count()
    out = RPStoryThreadOut.model_validate(thread)
    out.turn_count = count
    return out


# ── create thread ─────────────────────────────────────────────────────────────

@router.post("", response_model=RPStoryThreadDetail, status_code=201, dependencies=[Depends(require_creator)])
def create_rp_story(
    req: CreateRPStoryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RPStoryThreadDetail:
    """Create a new RP Story Thread from a partner starter."""
    # Verify character ownership if provided
    if req.selected_character_id is not None:
        char = db.query(CharacterModel).filter(CharacterModel.id == req.selected_character_id).first()
        if char is None or char.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Character not found or not owned by you")

    title = req.title or _auto_title(req.partner_starter)
    now = datetime.utcnow()

    thread = RPStoryThread(
        user_id=current_user.id,
        selected_character_id=req.selected_character_id,
        title=title,
        partner_label=req.partner_label,
        partner_pov=req.partner_pov,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(thread)
    db.flush()  # get thread.id

    turn = RPStoryTurn(
        thread_id=thread.id,
        turn_index=1,
        author_type="partner",
        content=req.partner_starter,
        generated=False,
        created_at=now,
    )
    # A partner starter is pasted in from another platform by definition — not
    # written here by anyone, so it is never user-written.
    turn.apply_provenance(external_import("rp_partner"))
    db.add(turn)
    db.commit()
    db.refresh(thread)

    turns = db.query(RPStoryTurn).filter(RPStoryTurn.thread_id == thread.id).order_by(RPStoryTurn.turn_index).all()
    detail = RPStoryThreadDetail.model_validate(thread)
    detail.turn_count = len(turns)
    detail.turns = [RPStoryTurnOut.model_validate(t) for t in turns]
    return detail


# ── list threads ──────────────────────────────────────────────────────────────

@router.get("", response_model=list[RPStoryThreadOut])
def list_rp_stories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RPStoryThreadOut]:
    threads = (
        db.query(RPStoryThread)
        .filter(RPStoryThread.user_id == current_user.id)
        .order_by(RPStoryThread.updated_at.desc())
        .all()
    )
    return [_thread_to_out(t, db) for t in threads]


# ── get thread detail ─────────────────────────────────────────────────────────

@router.get("/{thread_id}", response_model=RPStoryThreadDetail)
def get_rp_story(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RPStoryThreadDetail:
    thread = _get_thread_or_404(thread_id, current_user.id, db)
    turns = (
        db.query(RPStoryTurn)
        .filter(RPStoryTurn.thread_id == thread.id)
        .order_by(RPStoryTurn.turn_index)
        .all()
    )
    detail = RPStoryThreadDetail.model_validate(thread)
    detail.turn_count = len(turns)
    detail.turns = [RPStoryTurnOut.model_validate(t) for t in turns]
    return detail


# ── add partner turn ──────────────────────────────────────────────────────────

@router.post("/{thread_id}/partner-turn", response_model=RPStoryTurnOut, status_code=201)
def add_partner_turn(
    thread_id: int,
    req: AddPartnerTurnRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RPStoryTurnOut:
    """Record the partner's next reply in the thread."""
    thread = _get_thread_or_404(thread_id, current_user.id, db)

    idx = _next_turn_index(thread_id, db)
    turn = RPStoryTurn(
        thread_id=thread.id,
        turn_index=idx,
        author_type="partner",
        content=req.content,
        generated=False,
        created_at=datetime.utcnow(),
    )
    turn.apply_provenance(external_import("rp_partner"))
    db.add(turn)
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(turn)
    return RPStoryTurnOut.model_validate(turn)


# ── generate reply (draft only) ───────────────────────────────────────────────

@router.post("/{thread_id}/generate-reply", response_model=GenerateThreadReplyResponse, dependencies=[Depends(require_creator)])
def generate_reply(
    thread_id: int,
    req: GenerateThreadReplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GenerateThreadReplyResponse:
    """Generate the selected character's next reply. Does NOT save to DB."""
    thread = _get_thread_or_404(thread_id, current_user.id, db)

    if thread.selected_character_id is None:
        raise HTTPException(status_code=400, detail="Thread has no selected character")

    # Verify character still owned by user
    char = db.query(CharacterModel).filter(CharacterModel.id == thread.selected_character_id).first()
    if char is None or char.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Selected character is not owned by you")

    try:
        result = generate_thread_reply(
            db=db,
            thread=thread,
            instructions=req.instructions,
            response_length=req.response_length,
            style_match=req.style_match,
            perspective=req.perspective,
            formatting=req.formatting,
            intensity=req.intensity,
            heat_level=req.heat_level,
            style_archetype=req.style_archetype,
            model_profile=req.model_profile or "default",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Fingerprint the draft even though it is not saved here: the user may well
    # paste it into a Commons post instead of accepting it into the thread, and
    # that route must still recognise it as AI output.
    try:
        register_ai_output(
            db,
            user_id=current_user.id,
            text=result.get("reply", ""),
            source_kind="rp_thread_reply",
            source_ref=str(thread.id),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning(
            "[PROVENANCE] fingerprint registration failed | thread=%s", thread.id, exc_info=True
        )

    return GenerateThreadReplyResponse(**result)


# ── save generated turn ───────────────────────────────────────────────────────

@router.post("/{thread_id}/save-generated-turn", response_model=RPStoryTurnOut, status_code=201)
def save_generated_turn(
    thread_id: int,
    req: SaveGeneratedTurnRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RPStoryTurnOut:
    """Save the user-accepted generated reply as a selected_character turn."""
    thread = _get_thread_or_404(thread_id, current_user.id, db)

    if thread.selected_character_id is None:
        raise HTTPException(status_code=400, detail="Thread has no selected character")

    char = db.query(CharacterModel).filter(CharacterModel.id == thread.selected_character_id).first()
    if char is None or char.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Selected character is not owned by you")

    idx = _next_turn_index(thread_id, db)
    metadata: dict = {}
    if req.model_used:
        metadata["model_used"] = req.model_used
    if req.generation_time_ms is not None:
        metadata["generation_time_ms"] = req.generation_time_ms
    if req.godmod_warnings:
        metadata["godmod_warnings"] = req.godmod_warnings

    now = datetime.utcnow()
    turn = RPStoryTurn(
        thread_id=thread.id,
        turn_index=idx,
        author_type="selected_character",
        content=req.content,
        generated=True,
        godmod_detected=req.godmod_detected,
        godmod_severity=req.godmod_severity,
        metadata_json=metadata if metadata else None,
        created_at=now,
    )
    # Structural: this endpoint exists to save AI output the user accepted.
    # No evidence is consulted because none is needed — the surface is the fact.
    turn.apply_provenance(
        decide_provenance(
            db,
            user_id=current_user.id,
            content=req.content,
            structural=Provenance.AI_ASSISTED,
        )
    )
    db.add(turn)

    # Lightweight summary update
    char_name = char.name or ""
    append_lightweight_summary(thread, turn, char_name)
    thread.updated_at = now
    db.commit()
    db.refresh(turn)
    return RPStoryTurnOut.model_validate(turn)


# ── archive thread ────────────────────────────────────────────────────────────

@router.patch("/{thread_id}/archive", response_model=RPStoryThreadOut)
def archive_thread(
    thread_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RPStoryThreadOut:
    thread = _get_thread_or_404(thread_id, current_user.id, db)
    thread.status = "archived"
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(thread)
    return _thread_to_out(thread, db)
