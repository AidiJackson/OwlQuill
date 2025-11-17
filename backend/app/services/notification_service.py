"""Notification service for creating notifications."""
import json
from typing import Optional, List
from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationTypeEnum
from app.models.realm import RealmMembership, Realm


def create_notification(
    db: Session,
    user_id: int,
    notification_type: NotificationTypeEnum,
    data: dict,
) -> Notification:
    """Create a notification for a user.

    Args:
        db: Database session
        user_id: ID of the user to notify
        notification_type: Type of notification
        data: Data payload for the notification

    Returns:
        Created notification
    """
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        data=json.dumps(data),
        is_read=False
    )
    db.add(notification)
    db.flush()
    return notification


def create_reaction_notification(
    db: Session,
    post_author_id: int,
    reactor_id: int,
    post_id: int
) -> Optional[Notification]:
    """Create a notification for a post reaction.

    Args:
        db: Database session
        post_author_id: ID of the post author
        reactor_id: ID of the user who reacted
        post_id: ID of the post

    Returns:
        Created notification or None if reactor is the author
    """
    # Don't notify if user reacted to their own post
    if post_author_id == reactor_id:
        return None

    return create_notification(
        db=db,
        user_id=post_author_id,
        notification_type=NotificationTypeEnum.REACTION,
        data={"post_id": post_id, "reactor_id": reactor_id}
    )


def create_connection_notification(
    db: Session,
    following_id: int,
    follower_id: int
) -> Notification:
    """Create a notification for a new connection (follow).

    Args:
        db: Database session
        following_id: ID of the user being followed
        follower_id: ID of the user who followed

    Returns:
        Created notification
    """
    return create_notification(
        db=db,
        user_id=following_id,
        notification_type=NotificationTypeEnum.CONNECTION,
        data={"follower_id": follower_id}
    )


def create_scene_post_notifications(
    db: Session,
    realm_id: int,
    post_id: int,
    author_id: int
) -> List[Notification]:
    """Create notifications for a new post in a scene/realm.

    Args:
        db: Database session
        realm_id: ID of the realm
        post_id: ID of the post
        author_id: ID of the post author

    Returns:
        List of created notifications
    """
    notifications = []

    # Get the realm to notify the owner
    realm = db.query(Realm).filter(Realm.id == realm_id).first()
    if realm and realm.owner_id != author_id:
        notification = create_notification(
            db=db,
            user_id=realm.owner_id,
            notification_type=NotificationTypeEnum.SCENE_POST,
            data={"realm_id": realm_id, "post_id": post_id, "author_id": author_id}
        )
        notifications.append(notification)

    # Get all members of the realm (excluding the author)
    memberships = db.query(RealmMembership).filter(
        RealmMembership.realm_id == realm_id,
        RealmMembership.user_id != author_id
    ).all()

    for membership in memberships:
        # Skip if we already notified the owner
        if realm and membership.user_id == realm.owner_id:
            continue

        notification = create_notification(
            db=db,
            user_id=membership.user_id,
            notification_type=NotificationTypeEnum.SCENE_POST,
            data={"realm_id": realm_id, "post_id": post_id, "author_id": author_id}
        )
        notifications.append(notification)

    return notifications
