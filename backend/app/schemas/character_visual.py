"""Schemas for character visual endpoints (identity pack + moment generation)."""
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

from app.schemas.character_dna import CharacterDNARead
from app.schemas.character_image import CharacterImageRead

# Accepted style values — unknown values silently coerce to "realistic".
_VALID_STYLES = {"realistic", "anime", "cartoon", "illustration", "comic", "pixel"}


# ── Structured Character Identity Spec ───────────────────────────────

class IdentityCore(BaseModel):
    """Core facial/physical identity features."""
    hair_color: Optional[str] = None
    hair_length: Optional[str] = None
    eye_color: Optional[str] = None
    skin_tone: Optional[str] = None
    face_features: Optional[list[str]] = Field(default=None, max_length=2)

class IdentityBuild(BaseModel):
    """Body type and height band (no numeric height)."""
    body_type: Optional[str] = None
    height_band: Optional[str] = None  # e.g. "short", "average", "tall"

class IdentityMarksAccessories(BaseModel):
    """Distinguishing marks and identity accessories."""
    items: Optional[list[str]] = None  # e.g. ["glasses", "scar on left cheek", "sleeve tattoo"]

class WardrobeSpec(BaseModel):
    """Wardrobe preset for stable outfit generation."""
    outfit_type: Optional[str] = None    # e.g. "dress", "suit", "armor", "casual", "uniform"
    primary_color: Optional[str] = None  # e.g. "black", "red", "navy"
    secondary_color: Optional[str] = None
    footwear: Optional[str] = None       # e.g. "heels", "boots", "sneakers", "barefoot"
    accessory: Optional[str] = None      # e.g. "necklace", "watch", "belt"
    notes: Optional[str] = Field(default=None, max_length=80)

class CharacterIdentitySpec(BaseModel):
    """Structured identity specification for stable character generation.

    Replaces the free-text 'visual vibe' with typed fields that the prompt
    compiler can assemble in a deterministic order, ensuring wardrobe and
    identity features are never dropped or reordered.
    """
    style: str = "realistic"
    identity: Optional[IdentityCore] = None
    build: Optional[IdentityBuild] = None
    marks_accessories: Optional[IdentityMarksAccessories] = None
    wardrobe: Optional[WardrobeSpec] = None
    extra_notes: Optional[str] = Field(default=None, max_length=120)

    @field_validator("style", mode="before")
    @classmethod
    def _coerce_style(cls, v) -> str:
        if not isinstance(v, str) or not v.strip():
            return "realistic"
        normed = v.strip().lower()
        return normed if normed in _VALID_STYLES else "realistic"


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
    identity_spec: Optional[CharacterIdentitySpec] = None
    style: str = "realistic"

    @field_validator("style", mode="before")
    @classmethod
    def _coerce_style(cls, v) -> str:
        if not isinstance(v, str) or not v.strip():
            return "realistic"
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
