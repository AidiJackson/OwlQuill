"""Schemas for RP Story Thread endpoints."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── enums as literals ─────────────────────────────────────────────────────────

PartnerPOV = Literal["first", "third", "unknown"]
ThreadStatus = Literal["active", "archived"]
AuthorType = Literal["partner", "selected_character"]


# ── turn schemas ──────────────────────────────────────────────────────────────

class RPStoryTurnOut(BaseModel):
    id: int
    thread_id: int
    turn_index: int
    author_type: AuthorType
    content: str
    generated: bool
    godmod_detected: Optional[bool] = None
    godmod_severity: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── thread schemas ────────────────────────────────────────────────────────────

class RPStoryThreadOut(BaseModel):
    id: int
    user_id: int
    selected_character_id: Optional[int] = None
    title: str
    partner_label: Optional[str] = None
    partner_pov: str
    status: str
    summary_memory: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0

    model_config = {"from_attributes": True}


class RPStoryThreadDetail(RPStoryThreadOut):
    turns: list[RPStoryTurnOut] = []


# ── request schemas ───────────────────────────────────────────────────────────

class CreateRPStoryRequest(BaseModel):
    partner_starter: str = Field(..., min_length=1, max_length=20_000, description="Partner's opening turn")
    selected_character_id: Optional[int] = Field(None, description="Character responding")
    title: Optional[str] = Field(None, max_length=200, description="Thread title; auto-generated if omitted")
    partner_label: Optional[str] = Field(None, max_length=100, description="Partner's display name")
    partner_pov: PartnerPOV = "unknown"
    # Generation controls (mirrors RPReplyRequest fields)
    response_length: str = "match"
    style_match: str = "soft"
    perspective: str = "third_person_limited"
    formatting: str = "plain"
    intensity: str = "standard"
    heat_level: str = "flame"
    style_archetype: Optional[str] = None
    instructions: Optional[str] = Field(None, max_length=2_000)


class AddPartnerTurnRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20_000, description="Partner's next reply")


class GenerateThreadReplyRequest(BaseModel):
    instructions: Optional[str] = Field(None, max_length=2_000)
    response_length: str = "match"
    style_match: str = "soft"
    perspective: str = "third_person_limited"
    formatting: str = "plain"
    intensity: str = "standard"
    heat_level: str = "flame"
    style_archetype: Optional[str] = None
    model_profile: Optional[str] = None


class SaveGeneratedTurnRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20_000, description="The final reply text to save")
    godmod_detected: Optional[bool] = None
    godmod_severity: Optional[str] = None
    godmod_warnings: Optional[list[str]] = None
    model_used: Optional[str] = None
    generation_time_ms: Optional[int] = None


# ── response schemas ──────────────────────────────────────────────────────────

class GenerateThreadReplyResponse(BaseModel):
    reply: str
    model_used: str
    generation_time_ms: int
    godmod_detected: bool
    godmod_severity: str
    godmod_warnings: list[str]
    warnings: list[str]
    continuation_score: float = 0.0
    pacing_warnings: list[str] = []
    style_warnings: list[str] = []
