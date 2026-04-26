"""Pydantic schemas for Story Spaces — Stages 2-4."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


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
