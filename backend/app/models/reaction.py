"""Reaction model."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class Reaction(Base):
    """Reaction model for posts."""

    __tablename__ = "reactions"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)  # like, heart, star, etc.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    post = relationship("Post", back_populates="reactions")
    user = relationship("User", back_populates="reactions")
