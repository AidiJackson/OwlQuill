"""Schemas for the StoryLab generate + state + chapter endpoints."""
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class Direction(str, Enum):
    advance_plot = "advance_plot"
    add_dialogue = "add_dialogue"
    sad_moment = "sad_moment"
    argument_begins = "argument_begins"
    romantic_moment = "romantic_moment"
    sensual_scene = "sensual_scene"
    intimate_scene = "intimate_scene"
    twist_event = "twist_event"
    quiet_reflection = "quiet_reflection"
    action_sequence = "action_sequence"


class ToneIntensity(str, Enum):
    light = "light"
    moderate = "moderate"
    intense = "intense"


class Pacing(str, Enum):
    slow = "slow"
    balanced = "balanced"
    fast = "fast"


class Length(str, Enum):
    short = "short"    # ~75 words
    medium = "medium"  # ~150 words
    long = "long"      # ~250 words


class Boundary(str, Enum):
    sfw = "sfw"
    fade_to_black = "fade_to_black"
    sensual = "sensual"


class StoryLabControls(BaseModel):
    direction: Direction = Direction.advance_plot
    tone_intensity: ToneIntensity = ToneIntensity.moderate
    pacing: Pacing = Pacing.balanced
    length: Length = Length.medium
    boundary: Boundary = Boundary.sfw


class StoryLabGenerateRequest(BaseModel):
    story_id: str = Field(..., description="Unique story workspace identifier")
    text: str = Field(..., description="Current story text (max 50 000 chars)")
    cursor: Optional[int] = Field(None, description="Cursor position (char offset)")
    controls: StoryLabControls = Field(default_factory=StoryLabControls)
    context: Optional[str] = Field(None, description="Optional extra narrative context")
    variant: Literal["default", "alt"] = "default"


# ── response ──────────────────────────────────────────────────────────────────

class StateDelta(BaseModel):
    path: str
    delta: float


class StoryLabStateSnapshot(BaseModel):
    story_summary: str
    state_json: dict[str, Any]
    deltas: list[StateDelta] = Field(default_factory=list)


class SafetyInfo(BaseModel):
    blocked: bool = False
    policy_flags: list[str] = Field(default_factory=list)
    boundary: Boundary


class GeneratedText(BaseModel):
    text: str


class StoryLabGenerateResponse(BaseModel):
    request_id: str
    generated: GeneratedText
    state: StoryLabStateSnapshot
    safety: SafetyInfo


class StoryLabStateResponse(BaseModel):
    story_id: str
    story_summary: str
    state_json: dict[str, Any]
    updated_at: str


# ── chapter schemas ────────────────────────────────────────────────────────────

class ChapterGenerateRequest(BaseModel):
    prompt: str = Field("", description="User guidance for this chapter (beats, notes, prose)")
    mode: str = Field("roleplay", description="Generation mode: roleplay, duet, or play")
    controls: StoryLabControls = Field(default_factory=StoryLabControls)
    variant: Literal["default", "alt"] = "default"


class ChapterListItem(BaseModel):
    chapter_number: int
    created_at: str
    words: int
    mode: str
    boundary: str
    length: str


class ChapterDetail(BaseModel):
    chapter_number: int
    generated_text: str
    prompt_text: str
    controls: dict[str, Any]
    suggestions: list[str]
    words: int
    created_at: str


class ChapterGenerateResponse(BaseModel):
    chapter_number: int
    generated_text: str
    prompt_text: str
    suggestions: list[str]
    meta: dict[str, Any]
