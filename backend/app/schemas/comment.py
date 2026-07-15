"""Comment schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CommentBase(BaseModel):
    """Base comment schema."""
    content: str = Field(..., min_length=1)
    character_id: Optional[int] = None


class CommentCreate(CommentBase):
    """Comment creation schema."""
    pass


class CommentUpdate(BaseModel):
    """Comment update schema."""
    content: Optional[str] = Field(None, min_length=1)


class Comment(CommentBase):
    """Comment schema."""
    id: int
    post_id: int
    # Optional so the serialization layer can omit the author's identity from
    # character-attributed comments for non-owner viewers (character-first policy).
    author_user_id: Optional[int] = None
    author_username: Optional[str] = None
    character_name: Optional[str] = None
    character_avatar_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
