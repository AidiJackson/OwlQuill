"""Shared realm-visibility helpers (S24F).

Mirrors the realm visibility rule established in S24D/S24E: a realm is accessible
to a caller when it is public, or the caller is its owner or a member. Posts,
comments, and reactions inherit their realm's visibility.

``user_id`` may be ``None`` for unauthenticated callers — public realms remain
accessible to them; private realms do not.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.realm import Realm, RealmMembership
from app.models.post import Post


def user_can_access_realm(db: Session, user_id: Optional[int], realm: Optional[Realm]) -> bool:
    """True when the (possibly anonymous) caller may see this realm's contents."""
    if realm is None:
        # Orphaned / realm-less resource: nothing realm-scoped to gate.
        return True
    if realm.is_public:
        return True
    if user_id is None:
        return False
    if realm.owner_id == user_id:
        return True
    return (
        db.query(RealmMembership)
        .filter(
            RealmMembership.realm_id == realm.id,
            RealmMembership.user_id == user_id,
        )
        .first()
        is not None
    )


def user_can_access_post(db: Session, user_id: Optional[int], post: Optional[Post]) -> bool:
    """True when the caller may see this post (via its realm's visibility)."""
    if post is None:
        return True
    realm = db.query(Realm).filter(Realm.id == post.realm_id).first()
    return user_can_access_realm(db, user_id, realm)
