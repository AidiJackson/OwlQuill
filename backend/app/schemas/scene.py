"""Scene schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.scene import SceneVisibilityEnum


class SceneCreate(BaseModel):
    """Schema for creating a scene."""
    realm_id: int
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: SceneVisibilityEnum = SceneVisibilityEnum.PUBLIC


class SceneOut(BaseModel):
    """Schema for returning a scene."""
    id: int
    realm_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    visibility: SceneVisibilityEnum
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime
    post_count: int = 0

    model_config = {"from_attributes": True}
