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
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    avatar_url: Optional[str] = None
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
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    avatar_url: Optional[str] = None
    tags: Optional[str] = None
    visibility: Optional[VisibilityEnum] = None


class Character(CharacterBase):
    """Character schema."""
    id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
