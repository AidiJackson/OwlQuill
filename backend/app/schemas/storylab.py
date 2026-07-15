"""Schemas for the StoryLab generate + state + chapter endpoints."""
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    short = "short"    # ~500 words target
    medium = "medium"  # ~900 words target
    long = "long"      # ~1500 words target


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
    # Resolved story-path model slug for this generation. Surfaced so the active
    # story model is visible to clients and cannot silently drift unnoticed.
    story_model: str = ""


class StoryLabStateResponse(BaseModel):
    story_id: str
    story_summary: str
    state_json: dict[str, Any]
    updated_at: str


# ── chapter schemas ────────────────────────────────────────────────────────────

class ChapterGenerateRequest(BaseModel):
    prompt: str = Field("", description="User guidance for this chapter (beats, notes, prose)")
    mode: Literal["roleplay", "duet", "play", "solo"] = Field("roleplay", description="Generation mode: roleplay, duet, play, or solo")
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


# ── RP Reply schemas ──────────────────────────────────────────────────────────

class RPReplyResponseLength(str, Enum):
    short = "short"
    match = "match"
    long = "long"
    novella = "novella"


class RPReplyStyleMatch(str, Enum):
    off = "off"
    soft = "soft"
    strong = "strong"


class RPReplyPerspective(str, Enum):
    first_person = "first_person"
    third_person_limited = "third_person_limited"


class RPReplyFormatting(str, Enum):
    plain = "plain"
    roleplay_bars = "roleplay_bars"


class RPReplyIntensity(str, Enum):
    standard = "standard"
    mature = "mature"
    explicit = "explicit"   # maps to inferno heat via intensity_to_heat()


_VALID_HEAT_LEVELS = frozenset({"embers", "flame", "inferno"})


class RPReplyGenerateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    partner_reply: str = Field(..., min_length=1, max_length=20_000, description="The partner's RP reply text")
    instructions: Optional[str] = Field(None, max_length=2_000)
    character_id: Optional[int] = None
    story_id: Optional[str] = None
    response_length: RPReplyResponseLength = RPReplyResponseLength.match
    style_match: RPReplyStyleMatch = RPReplyStyleMatch.soft
    perspective: RPReplyPerspective = RPReplyPerspective.third_person_limited
    formatting: RPReplyFormatting = RPReplyFormatting.plain
    intensity: RPReplyIntensity = RPReplyIntensity.standard
    heat_level: str = Field("flame", description="Content heat level: embers / flame / inferno")
    model_profile: Optional[str] = Field(
        None,
        description="Internal model profile for bake-off testing. Default: None (uses default model).",
    )
    style_archetype: Optional[str] = Field(
        None,
        description=(
            "Internal prose style archetype. "
            "One of: cinematic_dark_romance, gothic_obsession, slow_burn_tension, "
            "dangerous_devotion, primal_restraint. Default: cinematic_dark_romance."
        ),
    )

    @field_validator("heat_level")
    @classmethod
    def validate_heat_level(cls, v: str) -> str:
        if v not in _VALID_HEAT_LEVELS:
            return "flame"
        return v

    partner_character_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Name of the partner character. When provided, enables name-anchored godmod detection.",
    )

    @field_validator("style_archetype")
    @classmethod
    def validate_style_archetype(cls, v: Optional[str]) -> Optional[str]:
        _VALID_ARCHETYPES = frozenset({
            "cinematic_dark_romance", "gothic_obsession", "slow_burn_tension",
            "dangerous_devotion", "primal_restraint",
        })
        if v and v not in _VALID_ARCHETYPES:
            return None
        return v


class RPReplyGenerateResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    reply: str
    warnings: list[str] = Field(default_factory=list)
    model_used: str = Field("", description="Actual model slug used for generation")
    generation_time_ms: int = Field(0, description="Wall-clock generation time in milliseconds")
    detected_stage: str = Field("", description="Scene stage detected in the reply")
    continuation_score: float = Field(0.0, description="Collaborative continuation score 0–1")
    resolution_detected: bool = Field(False, description="Whether the reply appears to resolve the scene")
    pacing_warnings: list[str] = Field(default_factory=list, description="Non-blocking escalation pacing warnings")
    style_warnings: list[str] = Field(default_factory=list, description="Prose cadence / repetition warnings from style engine")
    # Scene beat engine fields (internal dev mode)
    next_scene_goal: str = Field("", description="Recommended next scene beat from the beat engine")
    repetition_score: float = Field(0.0, description="Repetition/regression score 0–1 for the reply")
    progression_success: bool = Field(False, description="True if the reply advances the scene rather than stalling")
    # Beat planner diagnostics (internal dev mode)
    multi_beat_detected: bool = Field(False, description="True if multi-beat instruction sequence was detected")
    requested_beats: list[str] = Field(default_factory=list, description="Ordered beat labels extracted from instructions")
    # Length profile diagnostics (internal dev mode)
    resolved_length_profile: str = Field("", description="Human-readable label for the resolved length profile")
    max_tokens_used: int = Field(0, description="Max token cap sent to the model for this request")
    requested_beat_count: int = Field(0, description="Number of named beats extracted from instructions")
    beat_completion_mode: str = Field("single", description="Beat execution mode: single / multi_beat / full_sequence")
    # Narrative engine diagnostics (internal dev mode)
    progression_density: float = Field(0.0, description="Action/movement event density in the reply, 0–1")
    floating_scene_risk: float = Field(0.0, description="Risk of floating dialogue with no movement/environment, 0–1")
    static_scene_risk: float = Field(0.0, description="Risk of low-progression static scene, 0–1")
    recursive_emotion_risk: float = Field(0.0, description="Risk of emotional loop without forward progression, 0–1")
    progression_event_count: int = Field(0, description="Count of distinct progression events detected in the reply")
    paragraph_monotony: float = Field(0.0, description="Paragraph purpose monotony score, 0–1 (1 = all same type)")
    environment_usage_density: float = Field(0.0, description="Environment object reference density in the reply, 0–1")
    # Godmod output gate diagnostics
    godmod_detected: bool = Field(False, description="True if a hard godmod violation was detected in the final output")
    godmod_severity: str = Field("none", description="Godmod severity: none | soft | hard")
    godmod_warnings: list[str] = Field(default_factory=list, description="Excerpts / reasons for any godmod violations found")
    # Orchestration diagnostics (internal dev mode)
    ai_cadence_risk: bool = Field(False, description="True if the reply shows AI prose-cadence patterns")
    spatial_position: str = Field("", description="Detected spatial position of the characters in the scene")
    spatial_dominance: str = Field("neutral", description="Detected dominance dynamic: neutral | dominant | submissive")
    resolved_heat: str = Field("", description="Effective heat level after intensity-floor enforcement")
