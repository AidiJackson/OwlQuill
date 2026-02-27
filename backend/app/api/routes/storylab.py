"""StoryLab backend loop — state management + provider-routed generation + chapters.

Routes
------
GET  /storylab/state?story_id=...                      Return (or create) story state.
POST /storylab/generate                                 Generate continuation + update state.
GET  /storylab/chapters?story_id=...                   List all chapters for a story.
GET  /storylab/chapters/{chapter_number}?story_id=...  Get a specific chapter.
POST /storylab/chapters/generate?story_id=...          Generate a new chapter.
DELETE /storylab/chapters/{chapter_number}?story_id=... Delete a chapter.
POST /storylab/chapters/{chapter_number}/regenerate?story_id=... Overwrite chapter with new generation.

Generation is delegated to app.services.storylab_generator which routes to
the configured provider (stub / openrouter) with automatic stub fallback.
"""
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.storylab import GenerationLog, StoryChapter, StoryState
from app.schemas.storylab import (
    Boundary,
    ChapterDetail,
    ChapterGenerateRequest,
    ChapterGenerateResponse,
    ChapterListItem,
    Direction,
    SafetyInfo,
    StateDelta,
    StoryLabGenerateRequest,
    StoryLabGenerateResponse,
    StoryLabStateResponse,
    StoryLabStateSnapshot,
    GeneratedText,
)
from app.services.storylab_generator import (
    analyze_chapter_metrics,
    compute_story_progress,
    extract_ending_phrase,
    generate_chapter,
    generate_story_summary,
    generate_storylab_continuation,
    _fallback_suggestions,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_TEXT_LENGTH = 50_000

# ── default state ─────────────────────────────────────────────────────────────

_DEFAULT_STATE: dict[str, Any] = {
    "story_state": {
        "tone": "neutral",
        "pacing": "balanced",
        "stakes": 0.2,
        "scene_type": "start",
        "intimacy_level": 0,
        "tension": 0.2,
        "emotional_weight": 0.1,
    },
    "characters": [],
    "relationships": [],
}

# ── state mutation helpers ────────────────────────────────────────────────────

_BOUNDARY_INTIMACY_CAP = {
    Boundary.sfw: 2,
    Boundary.fade_to_black: 5,
    Boundary.sensual: 8,
}


def _build_deltas(
    direction: Direction,
    boundary: Boundary,
    state: dict[str, Any],
) -> tuple[dict[str, Any], list[StateDelta]]:
    """Apply conservative state mutations; return updated state + delta list."""
    s = {k: v for k, v in state.items()}
    story = dict(s.get("story_state", {}))
    deltas: list[StateDelta] = []

    def _nudge(field: str, amount: float, cap: float = 1.0, floor: float = 0.0) -> None:
        old = float(story.get(field, 0))
        new = min(cap, max(floor, old + amount))
        if abs(new - old) > 0.001:
            story[field] = round(new, 3)
            deltas.append(StateDelta(path=f"story_state.{field}", delta=round(new - old, 3)))

    if direction == Direction.sad_moment:
        _nudge("emotional_weight", 0.1, cap=1.0)
        _nudge("tension", 0.05)
    elif direction == Direction.argument_begins:
        _nudge("tension", 0.15)
    elif direction in (Direction.romantic_moment, Direction.sensual_scene, Direction.intimate_scene):
        cap = float(_BOUNDARY_INTIMACY_CAP.get(boundary, 2))
        old_il = float(story.get("intimacy_level", 0))
        new_il = min(cap, old_il + 1.0)
        if abs(new_il - old_il) > 0.001:
            story["intimacy_level"] = round(new_il, 1)
            deltas.append(StateDelta(path="story_state.intimacy_level", delta=round(new_il - old_il, 1)))
    elif direction in (Direction.advance_plot, Direction.twist_event):
        _nudge("stakes", 0.1, cap=1.0)
        _nudge("tension", 0.05)
    elif direction == Direction.action_sequence:
        _nudge("tension", 0.2)
    elif direction == Direction.quiet_reflection:
        _nudge("tension", -0.1, floor=0.0)

    s["story_state"] = story
    return s, deltas


# ── model delta merge ─────────────────────────────────────────────────────────

_ALLOWED_DELTA_KEYS: dict[str, str] = {
    "tension_delta": "tension",
    "emotional_weight_delta": "emotional_weight",
    "intimacy_delta": "intimacy_level",
    "stakes_delta": "stakes",
}
_DELTA_CLAMP = 0.2


def apply_model_deltas(
    state: dict[str, Any],
    model_deltas: dict[str, Any],
    boundary: Boundary,
) -> dict[str, Any]:
    """Merge model DELTA_SIGNALS into story_state on top of deterministic baseline.

    Each allowed key is clamped to ±0.2 before being added to the current field
    value. Results are further clamped to [0, 1] (or [0, intimacy_cap] for
    intimacy_level). Unknown keys are silently ignored.
    """
    s = dict(state)
    story = dict(s.get("story_state", {}))
    intimacy_cap = float(_BOUNDARY_INTIMACY_CAP.get(boundary, 2))

    for delta_key, field in _ALLOWED_DELTA_KEYS.items():
        raw = model_deltas.get(delta_key)
        if raw is None:
            continue
        try:
            delta = float(raw)
        except (TypeError, ValueError):
            continue
        delta = max(-_DELTA_CLAMP, min(_DELTA_CLAMP, delta))
        current = float(story.get(field, 0))
        new_val = current + delta
        if field == "intimacy_level":
            new_val = max(0.0, min(intimacy_cap, new_val))
        else:
            new_val = max(0.0, min(1.0, new_val))
        story[field] = round(new_val, 3)

    s["story_state"] = story
    return s


# ── DB helpers ────────────────────────────────────────────────────────────────

def _fetch_recent_endings(story_id: str, db: Session, n: int = 3) -> list[str]:
    """Return the last *n* ending phrases from the GenerationLog for *story_id*.

    Each entry is the final sentence/line of a past response_text, used to
    populate the prompt's anti-repetition block.
    """
    rows = (
        db.query(GenerationLog.response_text)
        .filter(GenerationLog.story_id == story_id)
        .order_by(GenerationLog.created_at.desc())
        .limit(n)
        .all()
    )
    endings: list[str] = []
    for (response_text,) in rows:
        if not response_text:
            continue
        phrase = extract_ending_phrase(response_text)
        if phrase:
            endings.append(phrase)
    return endings


def _get_or_create_state(story_id: str, db: Session) -> StoryState:
    row = db.query(StoryState).filter(StoryState.story_id == story_id).first()
    if row is None:
        row = StoryState(
            story_id=story_id,
            story_summary="",
            state_json=_DEFAULT_STATE,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/state", response_model=StoryLabStateResponse)
def get_state(
    story_id: str = Query(..., description="Story workspace identifier"),
    db: Session = Depends(get_db),
) -> StoryLabStateResponse:
    """Return the current story state, creating a default row if none exists."""
    row = _get_or_create_state(story_id, db)
    return StoryLabStateResponse(
        story_id=row.story_id,
        story_summary=row.story_summary or "",
        state_json=row.state_json or _DEFAULT_STATE,
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/generate", response_model=StoryLabGenerateResponse)
def generate(
    req: StoryLabGenerateRequest,
    db: Session = Depends(get_db),
) -> StoryLabGenerateResponse:
    """Generate a story continuation and persist updated state."""
    # ── input validation ──────────────────────────────────────────────────────
    text_stripped = req.text.strip()
    if not text_stripped:
        raise HTTPException(status_code=400, detail="text must not be empty")
    if len(req.text) > _MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"text exceeds maximum length of {_MAX_TEXT_LENGTH} characters",
        )

    # ── boundary enforcement ──────────────────────────────────────────────────
    _EXPLICIT_DIRECTIONS = {Direction.intimate_scene}
    if (
        req.controls.boundary == Boundary.sfw
        and req.controls.direction in _EXPLICIT_DIRECTIONS
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "BOUNDARY_CONFLICT",
                "message": (
                    f"Direction '{req.controls.direction}' is not permitted "
                    f"under boundary '{req.controls.boundary}'."
                ),
            },
        )

    # ── fetch/create state ────────────────────────────────────────────────────
    state_row = _get_or_create_state(req.story_id, db)
    current_state: dict[str, Any] = dict(state_row.state_json or _DEFAULT_STATE)

    # ── fetch recent endings for anti-repetition guidance ─────────────────────
    recent_endings = _fetch_recent_endings(req.story_id, db)

    # ── generate continuation (provider-routed; stub is fallback) ─────────────
    generated_text, model_deltas = generate_storylab_continuation(
        text=req.text,
        controls=req.controls,
        state_json=current_state,
        summary=state_row.story_summary or "",
        characters=current_state.get("characters", []),
        story_id=req.story_id,
        recent_endings=recent_endings,
        variant=req.variant,
    )
    word_count = len(generated_text.split())
    request_id = str(uuid.uuid4())

    # ── compute state deltas (deterministic baseline + optional model signals) ─
    new_state, deltas = _build_deltas(req.controls.direction, req.controls.boundary, current_state)
    if model_deltas:
        new_state = apply_model_deltas(new_state, model_deltas, req.controls.boundary)

    # ── persist ───────────────────────────────────────────────────────────────
    state_row.state_json = new_state
    state_row.updated_at = datetime.utcnow()
    db.add(state_row)

    log = GenerationLog(
        story_id=req.story_id,
        request_id=request_id,
        controls_json={
            "direction": req.controls.direction,
            "tone_intensity": req.controls.tone_intensity,
            "pacing": req.controls.pacing,
            "length": req.controls.length,
            "boundary": req.controls.boundary,
        },
        prompt_snapshot=None,
        response_text=generated_text,
        word_count=word_count,
        created_at=datetime.utcnow(),
    )
    db.add(log)
    db.commit()
    db.refresh(state_row)

    return StoryLabGenerateResponse(
        request_id=request_id,
        generated=GeneratedText(text=generated_text),
        state=StoryLabStateSnapshot(
            story_summary=state_row.story_summary or "",
            state_json=state_row.state_json,
            deltas=deltas,
        ),
        safety=SafetyInfo(
            blocked=False,
            policy_flags=[],
            boundary=req.controls.boundary,
        ),
    )


# ── chapter helpers ────────────────────────────────────────────────────────────

def _fetch_chapter_metrics(story_id: str, db: Session) -> list[dict[str, Any]]:
    """Return metrics_json for all chapters of *story_id* ordered by chapter_number."""
    rows = (
        db.query(StoryChapter.metrics_json)
        .filter(StoryChapter.story_id == story_id)
        .order_by(StoryChapter.chapter_number)
        .all()
    )
    return [m for (m,) in rows if m]


def _get_next_chapter_number(story_id: str, db: Session) -> int:
    """Return the next chapter_number for a story (1 if no chapters exist)."""
    from sqlalchemy import func
    result = db.query(func.max(StoryChapter.chapter_number)).filter(
        StoryChapter.story_id == story_id
    ).scalar()
    return (result or 0) + 1


def _chapter_to_list_item(ch: StoryChapter) -> ChapterListItem:
    controls = ch.controls_json or {}
    return ChapterListItem(
        chapter_number=ch.chapter_number,
        created_at=ch.created_at.isoformat(),
        words=ch.word_count,
        mode=ch.mode,
        boundary=controls.get("boundary", "sfw"),
        length=controls.get("length", "medium"),
    )


def _chapter_to_detail(ch: StoryChapter, suggestions: list[str]) -> ChapterDetail:
    return ChapterDetail(
        chapter_number=ch.chapter_number,
        generated_text=ch.generated_text,
        prompt_text=ch.prompt_text or "",
        controls=ch.controls_json or {},
        suggestions=suggestions,
        words=ch.word_count,
        created_at=ch.created_at.isoformat(),
        metrics=ch.metrics_json,
    )


def _run_chapter_generation(
    story_id: str,
    req: ChapterGenerateRequest,
    db: Session,
) -> tuple[str, list[str], dict[str, Any] | None]:
    """Shared generation logic: fetch state, get previous chapter, call generator."""
    state_row = _get_or_create_state(story_id, db)
    current_state: dict[str, Any] = dict(state_row.state_json or _DEFAULT_STATE)

    # Last chapter text for continuity context
    last_chapter = (
        db.query(StoryChapter)
        .filter(StoryChapter.story_id == story_id)
        .order_by(StoryChapter.chapter_number.desc())
        .first()
    )
    previous_text = last_chapter.generated_text if last_chapter else None

    chapter_text, suggestions, model_deltas = generate_chapter(
        prompt=req.prompt,
        controls=req.controls,
        state_json=current_state,
        summary=state_row.story_summary or "",
        characters=current_state.get("characters", []),
        previous_chapter_text=previous_text,
        story_id=story_id,
        variant=req.variant,
    )

    # Update story state
    new_state, _ = _build_deltas(req.controls.direction, req.controls.boundary, current_state)
    if model_deltas:
        new_state = apply_model_deltas(new_state, model_deltas, req.controls.boundary)
    state_row.state_json = new_state
    state_row.updated_at = datetime.utcnow()
    db.add(state_row)

    return chapter_text, suggestions, model_deltas


def _update_story_summary(
    story_id: str,
    state_row: StoryState,
    chapter_text: str,
    chapter_number: int,
    db: Session,
) -> None:
    """Generate and persist an updated story summary after a chapter is saved.

    Non-fatal: if summarisation fails the chapter is already committed and the
    summary will be regenerated on the next chapter generation.
    """
    try:
        new_summary = generate_story_summary(
            existing_summary=state_row.story_summary or "",
            chapter_text=chapter_text,
            chapter_number=chapter_number,
            story_id=story_id,
        )
        state_row.story_summary = new_summary
        state_row.updated_at = datetime.utcnow()
        db.add(state_row)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Story summary update failed for %s: %s", story_id, exc)


# ── chapter routes ─────────────────────────────────────────────────────────────

@router.get("/chapters", response_model=list[ChapterListItem])
def list_chapters(
    story_id: str = Query(..., description="Story workspace identifier"),
    db: Session = Depends(get_db),
) -> list[ChapterListItem]:
    """Return all chapters for a story, ordered by chapter_number."""
    rows = (
        db.query(StoryChapter)
        .filter(StoryChapter.story_id == story_id)
        .order_by(StoryChapter.chapter_number)
        .all()
    )
    return [_chapter_to_list_item(ch) for ch in rows]


@router.get("/chapters/{chapter_number}", response_model=ChapterDetail)
def get_chapter(
    chapter_number: int,
    story_id: str = Query(..., description="Story workspace identifier"),
    db: Session = Depends(get_db),
) -> ChapterDetail:
    """Return a specific chapter with suggestions derived from current state."""
    ch = (
        db.query(StoryChapter)
        .filter(
            StoryChapter.story_id == story_id,
            StoryChapter.chapter_number == chapter_number,
        )
        .first()
    )
    if ch is None:
        raise HTTPException(status_code=404, detail="Chapter not found")

    state_row = _get_or_create_state(story_id, db)
    suggestions = _fallback_suggestions(state_row.state_json or _DEFAULT_STATE)
    return _chapter_to_detail(ch, suggestions)


@router.post("/chapters/generate", response_model=ChapterGenerateResponse)
def generate_chapter_endpoint(
    story_id: str = Query(..., description="Story workspace identifier"),
    req: ChapterGenerateRequest = ...,
    db: Session = Depends(get_db),
) -> ChapterGenerateResponse:
    """Generate a new chapter and store it."""
    chapter_text, suggestions, model_deltas = _run_chapter_generation(story_id, req, db)
    word_count = len(chapter_text.split())
    chapter_number = _get_next_chapter_number(story_id, db)

    controls_snapshot = {
        "direction": req.controls.direction,
        "tone_intensity": req.controls.tone_intensity,
        "pacing": req.controls.pacing,
        "length": req.controls.length,
        "boundary": req.controls.boundary,
    }
    now = datetime.utcnow()
    ch = StoryChapter(
        story_id=story_id,
        chapter_number=chapter_number,
        prompt_text=req.prompt or "",
        mode=req.mode,
        controls_json=controls_snapshot,
        generated_text=chapter_text,
        word_count=word_count,
        created_at=now,
        updated_at=now,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)

    # Analyze chapter metrics and persist (non-fatal; chapter already committed)
    metrics = analyze_chapter_metrics(chapter_text, req.controls)
    ch.metrics_json = metrics
    db.add(ch)
    db.commit()

    # Compute rolling story progress over all chapters
    all_metrics = _fetch_chapter_metrics(story_id, db)
    story_progress = compute_story_progress(all_metrics)

    # Update story summary (non-fatal; chapter already committed)
    state_row = _get_or_create_state(story_id, db)
    _update_story_summary(story_id, state_row, chapter_text, chapter_number, db)

    return ChapterGenerateResponse(
        chapter_number=chapter_number,
        generated_text=chapter_text,
        prompt_text=req.prompt or "",
        suggestions=suggestions,
        meta={"words": word_count, "delta": model_deltas, "metrics": metrics, "story_progress": story_progress},
    )


@router.delete("/chapters/{chapter_number}", status_code=204)
def delete_chapter(
    chapter_number: int,
    story_id: str = Query(..., description="Story workspace identifier"),
    db: Session = Depends(get_db),
) -> None:
    """Delete a chapter. Gaps in chapter_number are preserved (no renumbering)."""
    ch = (
        db.query(StoryChapter)
        .filter(
            StoryChapter.story_id == story_id,
            StoryChapter.chapter_number == chapter_number,
        )
        .first()
    )
    if ch is None:
        raise HTTPException(status_code=404, detail="Chapter not found")
    db.delete(ch)
    db.commit()


@router.post("/chapters/{chapter_number}/regenerate", response_model=ChapterGenerateResponse)
def regenerate_chapter(
    chapter_number: int,
    story_id: str = Query(..., description="Story workspace identifier"),
    req: ChapterGenerateRequest = ...,
    db: Session = Depends(get_db),
) -> ChapterGenerateResponse:
    """Regenerate a chapter in-place, overwriting its generated_text."""
    ch = (
        db.query(StoryChapter)
        .filter(
            StoryChapter.story_id == story_id,
            StoryChapter.chapter_number == chapter_number,
        )
        .first()
    )
    if ch is None:
        raise HTTPException(status_code=404, detail="Chapter not found")

    chapter_text, suggestions, model_deltas = _run_chapter_generation(story_id, req, db)
    word_count = len(chapter_text.split())

    controls_snapshot = {
        "direction": req.controls.direction,
        "tone_intensity": req.controls.tone_intensity,
        "pacing": req.controls.pacing,
        "length": req.controls.length,
        "boundary": req.controls.boundary,
    }
    # Analyze metrics for the regenerated text
    metrics = analyze_chapter_metrics(chapter_text, req.controls)

    ch.generated_text = chapter_text
    ch.word_count = word_count
    ch.prompt_text = req.prompt or ch.prompt_text
    ch.controls_json = controls_snapshot
    ch.metrics_json = metrics
    ch.updated_at = datetime.utcnow()
    db.add(ch)
    db.commit()

    # Compute rolling story progress
    all_metrics = _fetch_chapter_metrics(story_id, db)
    story_progress = compute_story_progress(all_metrics)

    # Update story summary (non-fatal; chapter already committed)
    state_row = _get_or_create_state(story_id, db)
    _update_story_summary(story_id, state_row, chapter_text, chapter_number, db)

    return ChapterGenerateResponse(
        chapter_number=chapter_number,
        generated_text=chapter_text,
        prompt_text=req.prompt or ch.prompt_text or "",
        suggestions=suggestions,
        meta={"words": word_count, "delta": model_deltas, "metrics": metrics, "story_progress": story_progress},
    )
