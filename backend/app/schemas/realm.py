"""Realm schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class RealmBase(BaseModel):
    """Base realm schema."""
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    genre: Optional[str] = None
    is_public: bool = True


class RealmCreate(RealmBase):
    """Realm creation schema."""
    pass


class RealmUpdate(BaseModel):
    """Realm update schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    genre: Optional[str] = None
    is_public: Optional[bool] = None


class Realm(RealmBase):
    """Realm schema."""
    id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RealmMembershipBase(BaseModel):
    """Base realm membership schema."""
    realm_id: int
    user_id: int
    role: str = "member"


class RealmMembershipCreate(BaseModel):
    """Realm membership creation schema."""
    role: str = "member"


class RealmMembership(RealmMembershipBase):
    """Realm membership schema."""
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
