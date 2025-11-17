"""Notification schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.models.notification import NotificationTypeEnum


class NotificationBase(BaseModel):
    """Base notification schema."""
    type: NotificationTypeEnum
    data: Optional[str] = None


class NotificationCreate(NotificationBase):
    """Notification creation schema."""
    user_id: int


class Notification(NotificationBase):
    """Notification schema."""
    id: int
    user_id: int
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationMarkRead(BaseModel):
    """Schema for marking notifications as read."""
    ids: list[int]


class NotificationUnreadCount(BaseModel):
    """Schema for unread notification count."""
    count: int
