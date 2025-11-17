"""Character model."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class VisibilityEnum(str, enum.Enum):
    """Character visibility options."""
    PUBLIC = "public"
    FRIENDS = "friends"
    PRIVATE = "private"


class Character(Base):
    """Character/OC model for roleplay."""

    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    alias = Column(String, nullable=True)
    age = Column(String, nullable=True)
    species = Column(String, nullable=True)
    role = Column(String, nullable=True)  # e.g., "assassin", "healer", "detective"
    era = Column(String, nullable=True)  # e.g., "modern", "medieval", "sci-fi future"
    short_bio = Column(Text, nullable=True)
    long_bio = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)  # Legacy/external URL support
    avatar_media_id = Column(Integer, ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)
    portrait_url = Column(String, nullable=True)  # Character portrait for RP sheets
    tags = Column(String, nullable=True)  # Stored as comma-separated for MVP
    visibility = Column(SQLEnum(VisibilityEnum), default=VisibilityEnum.PUBLIC, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner = relationship("User", back_populates="characters")
    avatar_media = relationship("MediaAsset", foreign_keys=[avatar_media_id], post_update=True)
    posts = relationship("Post", back_populates="character")
    comments = relationship("Comment", back_populates="character")
