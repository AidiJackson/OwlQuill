"""Shared realm-visibility helpers (S24F).

Mirrors the realm visibility rule established in S24D/S24E: a realm is accessible
to a caller when it is public, or the caller is its owner or a member. Posts,
comments, and reactions inherit their realm's visibility.

``user_id`` may be ``None`` for unauthenticated callers — public realms remain
accessible to them; private realms do not, and neither does realm-less content.

Realm-less content is the one case the anonymous and authenticated answers
differ on. A signed-in caller may read it (``GET /posts/{id}`` has always
served it to any authenticated account, and notifications rely on the same
answer), but an anonymous caller may not: a realm-less post has no public realm
to be public in, which is the same fail-closed reading the anonymous Character
Home timeline applies with its inner join on ``realms.is_public``. Before this,
knowing a realm-less post's id was enough to read its comments and reactions
with no token at all.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.realm import Realm, RealmMembership
from app.models.post import Post


def user_can_access_realm(db: Session, user_id: Optional[int], realm: Optional[Realm]) -> bool:
    """True when the (possibly anonymous) caller may see this realm's contents."""
    if realm is None:
        # Orphaned / realm-less resource: nothing realm-scoped to gate for a
        # signed-in caller, but nothing public about it for an anonymous one.
        return user_id is not None
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
    """True when the caller may see this post (via its realm's visibility).

    Also the gate for MUTATING a post's social state — commenting and reacting.
    Being able to name a post id is not access to it; a caller who could not
    read the post must not be able to add to it either.

    A missing post is not accessible: callers answer 404 for both, so the two
    cannot be told apart.
    """
    if post is None:
        return False
    realm = db.query(Realm).filter(Realm.id == post.realm_id).first()
    return user_can_access_realm(db, user_id, realm)
