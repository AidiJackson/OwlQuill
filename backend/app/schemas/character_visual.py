"""Schemas for character visual endpoints (identity pack + moment generation)."""
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

from app.schemas.character_dna import CharacterDNARead
from app.schemas.character_image import CharacterImageRead

# Accepted style values — unknown values silently coerce to "realistic".
_VALID_STYLES = {"realistic", "anime", "cartoon", "illustration", "comic", "pixel"}


# ── Identity Pack Generate ───────────────────────────────────────────

class IdentityPackTweaks(BaseModel):
    """Optional tweaks applied when generating an identity pack preview."""
    age_band: Optional[str] = None
    facial_structure: Optional[str] = None
    skin_texture: Optional[str] = None
    hair: Optional[str] = None
    expression: Optional[str] = None
    signature_feature: Optional[str] = None


class IdentityPackGenerateRequest(BaseModel):
    """Request body for POST /identity-pack/generate."""
    tweaks: Optional[IdentityPackTweaks] = None
    prompt_vibe: Optional[str] = Field(None, max_length=250)
    style: str = "realistic"

    @field_validator("style")
    @classmethod
    def _coerce_style(cls, v: str) -> str:
        normed = v.strip().lower()
        return normed if normed in _VALID_STYLES else "realistic"


class IdentityPackGenerateResponse(BaseModel):
    """Response from generating an identity pack preview."""
    pack_id: str
    images: list[CharacterImageRead]
    tier_used: Literal["A", "B", "C", "stub"] = "stub"
    rewrite_applied: bool = False
    blocked_roles: list[str] = Field(default_factory=list)


# ── Identity Pack Accept ─────────────────────────────────────────────

class IdentityPackAcceptRequest(BaseModel):
    """Request body for POST /identity-pack/accept."""
    pack_id: str


class IdentityPackAcceptResponse(BaseModel):
    """Response from accepting an identity pack."""
    anchors: list[CharacterImageRead]
    dna: Optional[CharacterDNARead] = None


# ── Moment (Post-Lock) Image Generation ──────────────────────────────

class MomentGenerateRequest(BaseModel):
    """Request body for POST /images/generate (post-lock moments)."""
    outfit: Optional[str] = None
    mood: Optional[str] = None
    environment: Optional[str] = None
    hair: Optional[str] = None
    facial_hair: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)
