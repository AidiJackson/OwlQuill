"""ScenePost schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScenePostCreate(BaseModel):
    """Schema for creating a scene post (turn)."""
    content: str = Field(..., min_length=1)
    character_id: Optional[int] = None
    reply_to_id: Optional[int] = None


class ScenePostOut(BaseModel):
    """Schema for returning a scene post."""
    id: int
    scene_id: int
    author_user_id: int
    author_username: Optional[str] = None
    character_id: Optional[int] = None
    character_name: Optional[str] = None
    content: str
    reply_to_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}
