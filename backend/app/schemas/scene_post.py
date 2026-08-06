"""ScenePost schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScenePostCreate(BaseModel):
    """Schema for creating a scene post (turn)."""
    content: str = Field(..., min_length=1)
    character_id: Optional[int] = None
    reply_to_id: Optional[int] = None
    composition_session_id: Optional[str] = Field(None, max_length=36)


class ScenePostOut(BaseModel):
    """Schema for returning a scene post.

    author_user_id/author_username are populated only for the viewer's own
    turns (character-first identity — accounts are never public authors).
    """
    id: int
    scene_id: int
    author_user_id: Optional[int] = None
    author_username: Optional[str] = None
    character_id: Optional[int] = None
    character_name: Optional[str] = None
    content: str
    reply_to_id: Optional[int] = None
    provenance: str = "unknown"
    created_at: datetime

    model_config = {"from_attributes": True}
