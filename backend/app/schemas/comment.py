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
    composition_session_id: Optional[str] = Field(None, max_length=36)


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
    # Wanderer attribution: the public Wanderer username and account sigil.
    # Both are omitted for character-attributed comments (see
    # app.services.seeding.serialize_comment_for_viewer).
    author_username: Optional[str] = None
    author_avatar_url: Optional[str] = None
    character_name: Optional[str] = None
    character_avatar_url: Optional[str] = None
    provenance: str = "unknown"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
