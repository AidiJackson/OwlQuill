"""Scene model for roleplay scenes and threads."""
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.core.database import Base


class SceneVisibilityEnum(str, PyEnum):
    """Scene visibility options."""
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


class Scene(Base):
    """Scene model - represents a roleplay scene/thread."""
    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    visibility = Column(
        Enum(SceneVisibilityEnum),
        default=SceneVisibilityEnum.PUBLIC,
        nullable=False
    )
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    creator = relationship("User", back_populates="created_scenes")
    posts = relationship("ScenePost", back_populates="scene", cascade="all, delete-orphan")


class ScenePost(Base):
    """ScenePost model - represents a post within a scene."""
    __tablename__ = "scene_posts"

    id = Column(Integer, primary_key=True, index=True)
    scene_id = Column(Integer, ForeignKey("scenes.id"), nullable=False)
    author_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=True)
    content = Column(Text, nullable=False)
    reply_to_id = Column(Integer, ForeignKey("scene_posts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    scene = relationship("Scene", back_populates="posts")
    author = relationship("User", foreign_keys=[author_user_id])
    character = relationship("Character")
    reply_to = relationship("ScenePost", remote_side=[id], backref="replies")
