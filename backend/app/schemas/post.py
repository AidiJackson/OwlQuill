"""Post schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.post import ContentTypeEnum


class PostBase(BaseModel):
    """Base post schema."""
    title: Optional[str] = None
    content: str = Field(..., min_length=1)
    content_type: ContentTypeEnum = ContentTypeEnum.IC
    character_id: Optional[int] = None


class PostCreate(PostBase):
    """Post creation schema."""
    pass


class PostUpdate(BaseModel):
    """Post update schema."""
    title: Optional[str] = None
    content: Optional[str] = Field(None, min_length=1)
    content_type: Optional[ContentTypeEnum] = None


class Post(PostBase):
    """Post schema."""
    id: int
    scene_id: int
    realm_id: int
    author_user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
