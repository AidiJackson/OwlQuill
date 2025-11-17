"""Profile schemas for user and character profiles."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class UserSummary(BaseModel):
    """Minimal user info for embedding in other objects."""
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

    model_config = {"from_attributes": True}


class CharacterSummary(BaseModel):
    """Minimal character info for embedding in other objects."""
    id: int
    name: str
    avatar_url: Optional[str] = None

    model_config = {"from_attributes": True}


class RealmSummary(BaseModel):
    """Minimal realm info for embedding in other objects."""
    id: int
    name: str
    slug: str
    tagline: Optional[str] = None

    model_config = {"from_attributes": True}


class PostSummary(BaseModel):
    """Post summary for profile pages."""
    id: int
    title: Optional[str] = None
    content: str
    content_type: str
    created_at: datetime
    realm: Optional[RealmSummary] = None
    character: Optional[CharacterSummary] = None
    author_user: UserSummary

    model_config = {"from_attributes": True}


class UserProfile(BaseModel):
    """Full user profile with stats and recent activity."""
    id: int
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime

    # Stats
    follower_count: int = 0
    following_count: int = 0
    total_posts: int = 0
    joined_realms_count: int = 0

    # Recent activity
    recent_posts: List[PostSummary] = []

    model_config = {"from_attributes": True}


class CharacterProfile(BaseModel):
    """Full character profile with stats and recent activity."""
    id: int
    name: str
    alias: Optional[str] = None
    age: Optional[str] = None
    species: Optional[str] = None
    role: Optional[str] = None
    era: Optional[str] = None
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    avatar_url: Optional[str] = None
    portrait_url: Optional[str] = None
    tags: Optional[str] = None
    visibility: str
    created_at: datetime

    # Owner info
    owner: UserSummary

    # Stats
    posts_count: int = 0
    realms_count: int = 0

    # Recent activity
    recent_posts: List[PostSummary] = []

    model_config = {"from_attributes": True}
