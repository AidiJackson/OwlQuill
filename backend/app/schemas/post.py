"""Post schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.post import ContentTypeEnum, PostKindEnum, SourceTypeEnum


class PostMentionRead(BaseModel):
    """Serialised representation of a PostMention ORM row."""
    mention_text: str
    target_type: str   # "user" | "character" | "unresolved"
    target_id: Optional[int] = None
    display_name: str
    url: str

    model_config = {"from_attributes": True}


class PostBase(BaseModel):
    """Base post schema."""
    title: Optional[str] = None
    content: str = Field(..., min_length=1)
    content_type: ContentTypeEnum = ContentTypeEnum.IC
    post_kind: PostKindEnum = PostKindEnum.GENERAL
    source_type: SourceTypeEnum = SourceTypeEnum.USER
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
    # Optional so the serialization layer can omit the author's identity from
    # character-attributed posts for non-owner viewers (character-first policy —
    # keeps a user's roster from being reconstructed by clustering on this id).
    author_user_id: Optional[int] = None
    author_username: Optional[str] = None
    character_name: Optional[str] = None
    character_avatar_url: Optional[str] = None
    # Override: DB may have NULL for rows created before this field was added.
    source_type: Optional[SourceTypeEnum] = SourceTypeEnum.USER
    created_at: datetime
    updated_at: datetime
    mentions: list[PostMentionRead] = []
    # Number of comments on the post. Sent with the post so a collapsed comment
    # section can show a truthful count without first fetching the comments —
    # otherwise an existing comment is invisible until someone happens to expand.
    comment_count: int = 0

    model_config = {"from_attributes": True}
