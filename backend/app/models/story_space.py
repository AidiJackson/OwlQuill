"""Story Spaces models — private invite-only collaboration spaces."""
from datetime import datetime
import enum

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChannelTypeEnum(str, enum.Enum):
    STORY = "story"
    CHAT = "chat"
    PLANNING = "planning"


class StorySpace(Base):
    __tablename__ = "story_spaces"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=True)       # optional internal label, never used for routing
    description = Column(Text, nullable=True)
    cover_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    owner = relationship("User", foreign_keys=[owner_id])
    members = relationship(
        "StorySpaceMember",
        back_populates="space",
        cascade="all, delete-orphan",
    )
    channels = relationship(
        "StorySpaceChannel",
        back_populates="space",
        cascade="all, delete-orphan",
        order_by="StorySpaceChannel.position",
    )
    posts = relationship(
        "StorySpacePost",
        back_populates="space",
        cascade="all, delete-orphan",
    )


class StorySpaceMember(Base):
    __tablename__ = "story_space_members"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("story_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), default="member", nullable=False)  # 'owner' | 'member'
    invited_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    space = relationship("StorySpace", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    invited_by = relationship("User", foreign_keys=[invited_by_id])

    __table_args__ = (
        UniqueConstraint("space_id", "user_id", name="uq_space_member"),
    )


class StorySpaceChannel(Base):
    __tablename__ = "story_space_channels"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("story_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type = Column(String(20), nullable=False)  # 'story' | 'chat' | 'planning'
    name = Column(String(100), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    space = relationship("StorySpace", back_populates="channels")
    posts = relationship(
        "StorySpacePost",
        back_populates="channel",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("space_id", "channel_type", name="uq_space_channel_type"),
    )


class StorySpacePost(Base):
    __tablename__ = "story_space_posts"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("story_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("story_space_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)
    content_type = Column(String(20), nullable=False, default="ic")  # 'ic' | 'ooc' | 'narration'
    source_type = Column(String(20), nullable=True, default="user")  # 'user' | 'ai_assisted' | 'ai_generated'
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    space = relationship("StorySpace", back_populates="posts")
    channel = relationship("StorySpaceChannel", back_populates="posts")
    author = relationship("User", foreign_keys=[author_user_id])
    character = relationship("Character", foreign_keys=[character_id])

    __table_args__ = (
        Index("ix_space_post_channel_created", "channel_id", "created_at"),
    )


class PublishedStory(Base):
    __tablename__ = "published_stories"

    id = Column(Integer, primary_key=True, index=True)
    space_id = Column(Integer, ForeignKey("story_spaces.id", ondelete="SET NULL"), nullable=True)  # internal audit only, never exposed via API
    publisher_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    cover_url = Column(String(512), nullable=True)
    visibility = Column(String(20), nullable=False, default="public")
    realm_id = Column(Integer, ForeignKey("realms.id", ondelete="SET NULL"), nullable=True)  # reserved for v2 publish-to-realm
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    publisher = relationship("User", foreign_keys=[publisher_user_id])
    segments = relationship(
        "PublishedStorySegment",
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="PublishedStorySegment.position",
    )


class PublishedStorySegment(Base):
    __tablename__ = "published_story_segments"

    id = Column(Integer, primary_key=True, index=True)
    published_story_id = Column(Integer, ForeignKey("published_stories.id", ondelete="CASCADE"), nullable=False, index=True)
    source_post_id = Column(Integer, ForeignKey("story_space_posts.id", ondelete="SET NULL"), nullable=True)  # internal audit only, never exposed via API
    position = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    character_name_snap = Column(String(200), nullable=True)
    content_type = Column(String(20), nullable=False, default="ic")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    story = relationship("PublishedStory", back_populates="segments")
    character = relationship("Character", foreign_keys=[character_id])

    __table_args__ = (
        UniqueConstraint("published_story_id", "position", name="uq_segment_position"),
    )
