"""Post schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.post import ContentTypeEnum, PostKindEnum


class PostBase(BaseModel):
    """Base post schema."""
    title: Optional[str] = None
    content: str = Field(..., min_length=1)
    content_type: ContentTypeEnum = ContentTypeEnum.IC
    post_kind: PostKindEnum = PostKindEnum.GENERAL
    character_id: Optional[int] = None
    image_url: Optional[str] = Field(None, max_length=512)


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
    realm_id: Optional[int] = None
    author_user_id: int
    author_username: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
