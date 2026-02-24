"""StoryLab backend loop — state management + provider-routed generation.

Routes
------
GET  /storylab/state?story_id=...    Return (or create) story state.
POST /storylab/generate              Generate continuation + update state.

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
from app.models.storylab import GenerationLog, StoryState
from app.schemas.storylab import (
    Boundary,
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
    extract_ending_phrase,
    generate_storylab_continuation,
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
