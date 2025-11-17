"""Post model for story snippets/scenes."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class ContentTypeEnum(str, enum.Enum):
    """Post content type."""
    IC = "ic"  # In-character
    OOC = "ooc"  # Out-of-character
    NARRATION = "narration"


class Post(Base):
    """Post model for story snippets and scenes."""

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    scene_id = Column(Integer, ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    realm_id = Column(Integer, ForeignKey("realms.id", ondelete="CASCADE"), nullable=False)  # Denormalized for query performance
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    content_type = Column(SQLEnum(ContentTypeEnum), default=ContentTypeEnum.IC, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    scene = relationship("Scene", back_populates="posts")
    realm = relationship("Realm", back_populates="posts")
    author_user = relationship("User", back_populates="posts")
    character = relationship("Character", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    reactions = relationship("Reaction", back_populates="post", cascade="all, delete-orphan")
