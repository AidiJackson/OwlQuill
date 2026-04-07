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
    beat_type: Optional[str] = Field(None, description="Structured beat direction (continue/escalate/reveal/shift/slow/end)")


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


# ── story schemas ──────────────────────────────────────────────────────────────

_VALID_GENRES = {
    "literary", "romance", "fantasy", "thriller",
    "horror", "adventure", "sci-fi", "mystery", "other",
}

_COVER_COLORS = [
    "#1a1a2e", "#16213e", "#0f3460", "#1b1b2f",
    "#2c1810", "#1a2a1a", "#2a1a2e", "#1e2a1e",
]


class StoryCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    genre: Optional[str] = Field(None, max_length=50)
    premise: Optional[str] = Field(None, max_length=1000)
    realm_id: Optional[int] = None
    character_ids: list[int] = Field(default_factory=list)
    cover_color: str = Field("#1a1a2e", max_length=20)


class StoryResponse(BaseModel):
    id: str
    user_id: int
    title: str
    genre: Optional[str]
    premise: Optional[str]
    realm_id: Optional[int]
    character_ids: list[int]
    cover_color: str
    created_at: str
    updated_at: str
