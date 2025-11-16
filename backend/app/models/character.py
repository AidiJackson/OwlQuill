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
    short_bio = Column(Text, nullable=True)
    long_bio = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)
    tags = Column(String, nullable=True)  # Stored as comma-separated for MVP
    visibility = Column(SQLEnum(VisibilityEnum), default=VisibilityEnum.PUBLIC, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner = relationship("User", back_populates="characters")
    posts = relationship("Post", back_populates="character")
    comments = relationship("Comment", back_populates="character")
