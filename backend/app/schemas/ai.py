"""AI-related schemas."""
from typing import Optional
from pydantic import BaseModel, Field


# Character Bio Generation
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


# Post Suggestion
class PostSuggestionRequest(BaseModel):
    """Request schema for AI post suggestion."""
    realm_name: Optional[str] = Field(None, description="Name of the realm/scene")
    character_name: Optional[str] = Field(None, description="Name of the character posting")
    recent_posts: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Recent posts in the scene for context"
    )
    tone_hint: Optional[str] = Field(
        None,
        description="Optional tone/style hint (e.g., 'dramatic', 'humorous', 'tense')"
    )


class PostSuggestionResponse(BaseModel):
    """Response schema for AI post suggestion."""
    suggested_text: str = Field(..., description="AI-generated suggested post content")


# Scene Summary
class SceneSummaryRequest(BaseModel):
    """Request schema for AI scene summary."""
    realm_name: Optional[str] = Field(None, description="Name of the realm/scene")
    posts: list[str] = Field(
        default_factory=list,
        description="Post contents to summarize"
    )


class SceneSummaryResponse(BaseModel):
    """Response schema for AI scene summary."""
    summary: str = Field(..., description="AI-generated scene summary")


# Legacy Scene Generation (kept for backward compatibility)
class SceneRequest(BaseModel):
    """Request schema for AI scene generation (legacy)."""
    characters: list[str] = Field(..., min_length=1, max_length=5)
    setting: str = Field(..., min_length=1)
    mood: Optional[str] = None
    prompt: str = Field(..., min_length=1)


class SceneResponse(BaseModel):
    """Response schema for AI scene generation (legacy)."""
    scene: str
    dialogue: str
