"""AI-related schemas."""
from typing import Optional
from pydantic import BaseModel, Field


class CharacterBioRequest(BaseModel):
    """Request schema for AI character bio generation."""
    name: str = Field(..., min_length=1)
    species: Optional[str] = None
    role: Optional[str] = None
    era: Optional[str] = None
    tags: list[str] = Field(default_factory=list, max_length=5)


class CharacterBioResponse(BaseModel):
    """Response schema for AI character bio generation."""
    short_bio: str
    long_bio: str


class SceneRequest(BaseModel):
    """Request schema for AI scene generation."""
    characters: list[str] = Field(..., min_length=1, max_length=5)
    setting: str = Field(..., min_length=1)
    mood: Optional[str] = None
    prompt: str = Field(..., min_length=1)


class SceneResponse(BaseModel):
    """Response schema for AI scene generation."""
    scene: str
    dialogue: str
