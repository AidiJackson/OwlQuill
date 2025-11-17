"""Notification routes."""
from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.notification import Notification as NotificationModel
from app.schemas.notification import (
    Notification,
    NotificationMarkRead,
    NotificationUnreadCount
)

router = APIRouter()


@router.get("/", response_model=List[Notification])
def list_notifications(
    only_unread: bool = False,
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Notification]:
    """List notifications for the current user."""
    query = db.query(NotificationModel).filter(
        NotificationModel.user_id == current_user.id
    )

    if only_unread:
        query = query.filter(NotificationModel.is_read == False)

    notifications = query.order_by(
        NotificationModel.created_at.desc()
    ).offset(skip).limit(limit).all()

    return notifications


@router.post("/mark-read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notifications_read(
    mark_read_data: NotificationMarkRead,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Mark notifications as read."""
    db.query(NotificationModel).filter(
        NotificationModel.id.in_(mark_read_data.ids),
        NotificationModel.user_id == current_user.id
    ).update({"is_read": True}, synchronize_session=False)

    db.commit()


@router.get("/unread-count", response_model=NotificationUnreadCount)
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> NotificationUnreadCount:
    """Get the count of unread notifications."""
    count = db.query(NotificationModel).filter(
        NotificationModel.user_id == current_user.id,
        NotificationModel.is_read == False
    ).count()

    return NotificationUnreadCount(count=count)
