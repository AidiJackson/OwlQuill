"""Scene schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SceneBase(BaseModel):
    """Base scene schema."""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None


class SceneCreate(SceneBase):
    """Scene creation schema."""
    pass


class SceneUpdate(BaseModel):
    """Scene update schema."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None


class Scene(SceneBase):
    """Scene schema."""
    id: int
    realm_id: int
    created_by: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
