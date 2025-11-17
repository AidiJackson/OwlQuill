"""Scene model for roleplay threads within realms."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class Scene(Base):
    """Scene model for roleplay threads/storylines within a realm."""

    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(Integer, ForeignKey("realms.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    realm = relationship("Realm", back_populates="scenes")
    creator = relationship("User", back_populates="created_scenes")
    posts = relationship("Post", back_populates="scene", cascade="all, delete-orphan")
