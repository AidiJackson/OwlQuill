"""Character schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.character import VisibilityEnum


class CharacterBase(BaseModel):
    """Base character schema."""
    name: str = Field(..., min_length=1, max_length=100)
    alias: Optional[str] = None
    age: Optional[str] = None
    species: Optional[str] = None
    role: Optional[str] = None
    era: Optional[str] = None
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    cover_position_y: Optional[float] = 0.5
    cover_position_x: Optional[float] = 0.5
    cover_scale: Optional[float] = 1.0
    avatar_position_x: Optional[float] = 0.5
    avatar_position_y: Optional[float] = 0.5
    avatar_scale: Optional[float] = 1.0
    portrait_url: Optional[str] = None
    tags: Optional[str] = None
    visibility: VisibilityEnum = VisibilityEnum.PUBLIC


class CharacterCreate(CharacterBase):
    """Character creation schema."""
    pass


class CharacterUpdate(BaseModel):
    """Character update schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    alias: Optional[str] = None
    age: Optional[str] = None
    species: Optional[str] = None
    role: Optional[str] = None
    era: Optional[str] = None
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    cover_position_y: Optional[float] = None
    cover_position_x: Optional[float] = None
    cover_scale: Optional[float] = None
    avatar_position_x: Optional[float] = None
    avatar_position_y: Optional[float] = None
    avatar_scale: Optional[float] = None
    portrait_url: Optional[str] = None
    tags: Optional[str] = None
    visibility: Optional[VisibilityEnum] = None


class Character(CharacterBase):
    """Character schema."""
    id: int
    owner_id: int
    owner_username: Optional[str] = None
    visual_locked: bool = False
    # True when the character has a generated identity canon (a face_front image
    # exists), even if it has not been locked yet. Used by the character list to
    # route existing characters to their detail page instead of the creation flow
    # (S24AR). Populated by the route layer; defaults False elsewhere.
    has_identity_canon: bool = False
    identity_anchor_json: Optional[str] = None
    identity_health: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CharacterSearchResult(BaseModel):
    """Lightweight schema returned from character search."""
    id: int
    name: str
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    cover_position_y: Optional[float] = 0.5
    cover_position_x: Optional[float] = 0.5
    cover_scale: Optional[float] = 1.0
    avatar_position_x: Optional[float] = 0.5
    avatar_position_y: Optional[float] = 0.5
    avatar_scale: Optional[float] = 1.0
    short_bio: Optional[str] = None
    species: Optional[str] = None
    visibility: VisibilityEnum = VisibilityEnum.PUBLIC

    model_config = {"from_attributes": True}
