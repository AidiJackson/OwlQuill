"""StoryLab backend loop v1 — deterministic stub generator (no LLM).

Routes
------
GET  /storylab/state?story_id=...    Return (or create) story state.
POST /storylab/generate              Generate a stub continuation + update state.
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
    Length,
    Pacing,
    SafetyInfo,
    StateDelta,
    StoryLabGenerateRequest,
    StoryLabGenerateResponse,
    StoryLabStateResponse,
    StoryLabStateSnapshot,
    ToneIntensity,
    GeneratedText,
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

# ── stub templates keyed by Direction ────────────────────────────────────────

_STUB_TEMPLATES: dict[str, list[str]] = {
    Direction.advance_plot: [
        "The path ahead shifted unexpectedly. New complications unfolded as events gathered momentum, pulling the story forward with quiet insistence.",
        "Something clicked into place. The threads that had been gathering finally converged, nudging the narrative into its next chapter.",
    ],
    Direction.add_dialogue: [
        '"I need to tell you something," she said, breaking the silence that had lingered too long between them.',
        '"You never asked," he replied, letting the words settle before adding anything more.',
    ],
    Direction.sad_moment: [
        "The weight of it arrived slowly — not all at once, but in the quiet moments between breaths, when there was nothing left to do but feel it.",
        "There was a particular kind of sadness in knowing. Not anger, not confusion — just a hollow ache that asked for no explanation.",
    ],
    Direction.argument_begins: [
        'The tension had been building for hours. "That\'s not what I said," came the sharp reply, and just like that, the dam broke.',
        "A single word landed wrong. The air changed instantly — thick, charged — and neither of them reached for calm.",
    ],
    Direction.romantic_moment: [
        "The moment stretched — unplanned, unhurried. Something unspoken passed between them, softer than words and twice as clear.",
        "She noticed it first: the way he looked at her when he thought she wasn't watching. Warmth gathered in the space between them.",
    ],
    Direction.sensual_scene: [
        "The evening grew warm around the edges. Words gave way to proximity, and proximity to a silence that said more than either expected.",
        "There was an awareness — heightened, careful — in every small movement. The air between them felt charged, full of quiet permission.",
    ],
    Direction.intimate_scene: [
        "The world narrowed to this room, this light, this person. Tenderness moved through the scene like a current beneath still water.",
        "It was not dramatic. It was close and honest and real — the kind of intimacy that doesn't announce itself.",
    ],
    Direction.twist_event: [
        "Everything changed in a single moment. What had seemed certain dissolved, and the story pivoted on a truth no one had seen coming.",
        "The revelation arrived quietly — but its implications were anything but. Nothing would read the same after this.",
    ],
    Direction.quiet_reflection: [
        "The character sat with their thoughts, letting the day unspool. In the stillness, something became clear that noise had been hiding.",
        "No one spoke. The silence wasn't uncomfortable — it was necessary, the kind that allows things to settle and be seen.",
    ],
    Direction.action_sequence: [
        "Movement exploded into the scene. There was no time to think — only react, each second collapsing into the next.",
        "The pace surged. Bodies in motion, decisions made in fragments of time, the world shrinking to the next three feet.",
    ],
}

# Fade-to-black override suffix
_FADE_TO_BLACK_SUFFIX = " The scene dissolved softly, drawing a discreet curtain over what followed."
_SENSUAL_SUFFIX = " The moment lingered at the edge of restraint, intimate but unhurried, its full weight implied rather than shown."

# ── state mutation helpers ────────────────────────────────────────────────────

_BOUNDARY_INTIMACY_CAP = {
    Boundary.sfw: 2,
    Boundary.fade_to_black: 5,
    Boundary.sensual: 8,
}


def _build_deltas(direction: Direction, boundary: Boundary, state: dict[str, Any]) -> tuple[dict[str, Any], list[StateDelta]]:
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


# ── tone/pacing qualifiers ────────────────────────────────────────────────────

def _qualify(text: str, tone: ToneIntensity, pacing: Pacing, length: Length) -> str:
    """Optionally expand stub text based on controls."""
    prefix = ""
    if tone == ToneIntensity.intense:
        prefix = "With sharp, unflinching clarity — "
    elif tone == ToneIntensity.light:
        prefix = "Gently, almost imperceptibly — "

    pace_suffix = ""
    if pacing == Pacing.fast:
        pace_suffix = " It happened quickly."
    elif pacing == Pacing.slow:
        pace_suffix = " Time stretched around the moment."

    result = prefix + text + pace_suffix

    if length == Length.long:
        result += (
            "\n\nThe aftermath settled like dust after movement: slowly, inevitably."
            " Whatever came next would carry the mark of this."
        )
    return result


# ── stub generator ────────────────────────────────────────────────────────────

def _generate_stub(req: StoryLabGenerateRequest) -> str:
    templates = _STUB_TEMPLATES.get(req.controls.direction, _STUB_TEMPLATES[Direction.advance_plot])
    # Deterministically pick template by hashing story_id + direction
    idx = hash(req.story_id + req.controls.direction) % len(templates)
    text = templates[idx]
    text = _qualify(text, req.controls.tone_intensity, req.controls.pacing, req.controls.length)

    # Boundary-aware suffix
    if req.controls.boundary == Boundary.fade_to_black and req.controls.direction in (
        Direction.sensual_scene,
        Direction.intimate_scene,
        Direction.romantic_moment,
    ):
        text += _FADE_TO_BLACK_SUFFIX
    elif req.controls.boundary == Boundary.sensual and req.controls.direction in (
        Direction.sensual_scene,
        Direction.intimate_scene,
    ):
        text += _SENSUAL_SUFFIX

    return text


# ── DB helpers ────────────────────────────────────────────────────────────────

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
    """Generate a deterministic stub continuation and persist updated state."""
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

    # ── generate stub ─────────────────────────────────────────────────────────
    stub_text = _generate_stub(req)
    word_count = len(stub_text.split())
    request_id = str(uuid.uuid4())

    # ── compute state deltas ──────────────────────────────────────────────────
    new_state, deltas = _build_deltas(req.controls.direction, req.controls.boundary, current_state)

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
        response_text=stub_text,
        word_count=word_count,
        created_at=datetime.utcnow(),
    )
    db.add(log)
    db.commit()
    db.refresh(state_row)

    return StoryLabGenerateResponse(
        request_id=request_id,
        generated=GeneratedText(text=stub_text),
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
