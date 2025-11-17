"""Scene schemas for API requests and responses."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.scene import SceneVisibilityEnum


# Scene Schemas
class SceneBase(BaseModel):
    """Base scene schema."""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: SceneVisibilityEnum = SceneVisibilityEnum.PUBLIC


class SceneCreate(SceneBase):
    """Scene creation schema."""
    pass


class SceneUpdate(BaseModel):
    """Scene update schema."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: Optional[SceneVisibilityEnum] = None


class Scene(SceneBase):
    """Scene response schema."""
    id: int
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ScenePost Schemas
class ScenePostBase(BaseModel):
    """Base scene post schema."""
    content: str = Field(..., min_length=1)
    character_id: Optional[int] = None
    reply_to_id: Optional[int] = None


class ScenePostCreate(ScenePostBase):
    """Scene post creation schema."""
    pass


class ScenePost(ScenePostBase):
    """Scene post response schema."""
    id: int
    scene_id: int
    author_user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
