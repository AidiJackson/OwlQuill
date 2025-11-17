"""Notification model."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class NotificationTypeEnum(str, enum.Enum):
    """Notification type enum."""
    REACTION = "reaction"
    CONNECTION = "connection"
    SCENE_POST = "scene_post"
    REALM_JOIN = "realm_join"


class Notification(Base):
    """Notification model."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(SQLEnum(NotificationTypeEnum), nullable=False)
    data = Column(Text, nullable=True)  # JSON stored as text for MVP
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="notifications")
