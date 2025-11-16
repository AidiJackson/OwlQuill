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
    author_user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
