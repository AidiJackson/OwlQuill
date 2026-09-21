"""Notification model — the account-owned, private return-loop row.

The row belongs to an ACCOUNT (``user_id``); the social identities inside it
are CHARACTERS, carried in the JSON payload. Rows are written only through
``app.services.notifications`` (Polish Phase 7.1), which is where the payload
contract per ``type`` is documented.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class Notification(Base):
    """One thing that happened to, or around, one of the account's characters."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Free string, one value per producer. Written today: "mention"
    # (services.notifications.NOTIFICATION_TYPE_MENTION). Phase 7.2 adds its
    # producers here; the frontend renders any type it does not know neutrally.
    type = Column(String, nullable=False)
    # JSON as text. Keys per type are the contract in services/notifications;
    # a snapshot at write time, never a live reference.
    payload = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="notifications")
