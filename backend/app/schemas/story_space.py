"""Pydantic schemas for Story Spaces — Stages 2-4."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PublishRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = None
    cover_url: Optional[str] = Field(None, max_length=512)
    post_ids: List[int]


class PublishedSegmentRead(BaseModel):
    id: int
    position: int
    content: str
    content_type: str
    character_id: Optional[int] = None
    character_name_snap: Optional[str] = None
    provenance: str = "unknown"
    # source_post_id is an internal audit field — intentionally excluded


class PublishedStoryRead(BaseModel):
    id: int
    # space_id is an internal audit field — intentionally excluded
    publisher_user_id: int
    title: str
    summary: Optional[str] = None
    cover_url: Optional[str] = None
    visibility: str
    #: Roll-up of the segments' provenance — worst case wins.
    provenance: str = "unknown"
    segment_count: int
    segments: List[PublishedSegmentRead]
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class StorySpacePostCreate(BaseModel):
    content: str = Field(..., min_length=1)
    content_type: str = Field("ic", pattern="^(ic|ooc|narration)$")
    character_id: Optional[int] = None
    # ``source_type`` removed — it let the client pick its own badge. See
    # app/schemas/post.py::PostCreate.
    composition_session_id: Optional[str] = Field(None, max_length=36)


class StorySpacePostRead(BaseModel):
    id: int
    space_id: int
    channel_id: int
    # author_user_id is a numeric ownership handle (never a public human name);
    # it is retained for is-author/edit checks. The account USERNAME is
    # deliberately NOT part of this payload — Story Spaces are collaborative
    # surfaces and characters are the only public identity here. A post with no
    # character renders as an unlinked "Wanderer" on the client.
    author_user_id: int
    character_id: Optional[int] = None
    character_name: Optional[str] = None
    character_avatar_url: Optional[str] = None
    content: str
    content_type: str
    provenance: str = "unknown"
    created_at: datetime
    updated_at: datetime


class SpaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = Field(None, max_length=100)   # optional internal label, never routed
    description: Optional[str] = None
    cover_url: Optional[str] = Field(None, max_length=512)


class ChannelRead(BaseModel):
    id: int
    channel_type: str
    name: str
    position: int

    model_config = {"from_attributes": True}


class MemberRead(BaseModel):
    id: int
    space_id: int
    user_id: int
    username: str
    role: str
    joined_at: datetime


class SpaceListItem(BaseModel):
    id: int
    owner_id: int
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    your_role: str
    member_count: int
    created_at: datetime
    updated_at: datetime


class SpaceRead(BaseModel):
    id: int
    owner_id: int
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    your_role: str
    member_count: int
    channels: List[ChannelRead]
    created_at: datetime
    updated_at: datetime


class InviteRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
