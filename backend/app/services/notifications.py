"""Notification creation — the one place a ``Notification`` row is built.

Polish Phase 7.1 centralised row creation here. Every producer (W-10A's
character tags; Phase 7.2: comments, Story Space invites, direct messages) goes
through :func:`create_notification` so the account-owned row and its
JSON-as-text payload are written the same way everywhere.

W-10A: typed ``@mentions`` NO LONGER NOTIFY. The legacy parser addresses by
ASCII name prefix, so ``@Leo Vance`` reached whoever owned "Leo" and ``@Zoë``
reached "Zo" — a notification, with a preview, to the wrong account. Explicit
character tagging (:func:`notify_character_tagged`) is now the only way a post
notifies another character's owner. Historical ``mention`` rows are left
exactly as they are; the reader still renders them and post deletion still
removes them.

Two rules the helpers enforce and their callers may rely on:

* **The account owns the row; the character is the social identity.** A
  payload names the acting CHARACTER (id + name snapshot) and the recipient's
  CHARACTER where the interaction has one. It never carries an account
  username as the displayed actor — accounts are private infrastructure.
* **Protected content stays protected.** A recipient who cannot open the
  target does not receive its text through the side door of a notification.
  The row may still truthfully say *that* their character was addressed.

Deliberately boring: no bus, no queue, no dedup framework, no delivery
channels, no preferences. The helpers ``db.add`` and return; the CALLER owns
the transaction, exactly as the inline code did.
"""
import json
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.notification import Notification
from app.models.post import Post
from app.models.realm import Realm
from app.services.visibility import user_can_access_realm

#: LEGACY. A realm post @mentioned one of the recipient's characters. No longer
#: written (W-10A); kept because historical rows exist, are rendered, and are
#: removed with their post.
NOTIFICATION_TYPE_MENTION = "mention"

#: W-10A. A post's author explicitly tagged one of the recipient's characters.
NOTIFICATION_TYPE_CHARACTER_TAGGED = "character_tagged"

#: Every type whose payload points at a post by ``post_id`` and may carry a
#: preview of its body. Deleting the post deletes these rows.
POST_NOTIFICATION_TYPES = frozenset({NOTIFICATION_TYPE_MENTION, NOTIFICATION_TYPE_CHARACTER_TAGGED})

#: Characters of post body a post notification may carry as its preview.
POST_PREVIEW_CHARS = 120


def create_notification(
    db: Session,
    *,
    user_id: int,
    type: str,
    payload: Mapping[str, Any],
) -> Notification:
    """Add one account-owned notification row. Does NOT commit.

    ``payload`` is serialised once, here, as compact JSON so every producer
    writes the same encoding and the reader (``Notifications.tsx``) parses one
    shape. Keys with a ``None`` value are dropped rather than written as
    ``null``: the frontend treats a missing key and a null key identically,
    and omitting is what lets "preview withheld" be indistinguishable from
    "legacy row with no preview" — there is nothing to leak in either.
    """
    compact = {k: v for k, v in payload.items() if v is not None}
    notif = Notification(
        user_id=user_id,
        type=type,
        payload=json.dumps(compact, ensure_ascii=False, separators=(",", ":")),
    )
    db.add(notif)
    return notif


def post_preview_permitted(db: Session, recipient_user_id: int, realm: Optional[Realm]) -> bool:
    """May this recipient be shown the post's text?

    The same question as "may this account open the realm", answered by the
    same helper that gates the realm and post routes — so a notification can
    never show more than the destination it links to would. A public realm:
    yes. A private realm: only an owner or member. No realm on the post:
    nothing realm-scoped to protect.
    """
    return user_can_access_realm(db, recipient_user_id, realm)


def notify_character_tagged(
    db: Session,
    *,
    recipient_user_id: int,
    post: Post,
    realm: Optional[Realm],
    author_character: Character,
    tagged_character: Character,
) -> Notification:
    """Write the ``character_tagged`` row for one explicit tag. Does NOT commit.

    The caller has validated the tag (``services/character_tags``) and decided
    that the recipient should hear about it: not the author's own character,
    not across a block. Called once per (post, tagged character), at post
    creation only — posts are not editable, so a tag cannot be re-added.

    Payload contract (stable keys; the frontend renders from these):

      post_id, realm_id             — the target. Ids only; an id is not content.
      author_character_id/_name     — WHO tagged, as a character. Snapshot.
      tagged_character_id/_name     — WHICH of the recipient's characters was
                                      tagged. Snapshot.
      realm_name, post_preview      — ONLY when the recipient can access the
                                      realm (:func:`post_preview_permitted`).

    No account username or id is ever written.
    """
    permitted = post_preview_permitted(db, recipient_user_id, realm)
    payload: dict[str, Any] = {
        "post_id": post.id,
        "realm_id": post.realm_id,
        "author_character_id": author_character.id,
        "author_character_name": author_character.name,
        "tagged_character_id": tagged_character.id,
        "tagged_character_name": tagged_character.name,
        "realm_name": realm.name if (permitted and realm is not None) else None,
        "post_preview": post.content[:POST_PREVIEW_CHARS] if permitted else None,
    }
    return create_notification(
        db, user_id=recipient_user_id, type=NOTIFICATION_TYPE_CHARACTER_TAGGED, payload=payload
    )


def _payload_int(payload: Any, key: str) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    # bool is an int subclass; True must not match id 1.
    return value if type(value) is int else None


def delete_post_notifications(
    db: Session, post_id: int, *, tagged_character_id: Optional[int] = None
) -> int:
    """Delete the post-pointing notifications for ``post_id``. Does NOT commit.

    The one cleanup path for every type in :data:`POST_NOTIFICATION_TYPES`.

    * Post deleted — call with ``post_id`` alone: every ``mention`` and
      ``character_tagged`` row for that post goes, because each may snapshot up
      to :data:`POST_PREVIEW_CHARS` of the deleted body.
    * One tag removed — pass ``tagged_character_id``: only the
      ``character_tagged`` row(s) for that character on that post go.

    Matched by PARSING each payload and comparing ids as integers — never by a
    text match on the JSON, where ``"post_id":1`` is a prefix of
    ``"post_id":12``. A malformed payload is left alone rather than guessed at.
    Scans the candidate rows in Python, which is fine at closed-beta volume and
    keeps notification storage as it is.

    Returns the number of rows deleted.
    """
    types = (
        {NOTIFICATION_TYPE_CHARACTER_TAGGED}
        if tagged_character_id is not None
        else POST_NOTIFICATION_TYPES
    )
    deleted = 0
    rows = db.query(Notification).filter(Notification.type.in_(types)).all()
    for row in rows:
        try:
            payload = json.loads(row.payload or "")
        except (TypeError, ValueError):
            continue
        if _payload_int(payload, "post_id") != post_id:
            continue
        if (
            tagged_character_id is not None
            and _payload_int(payload, "tagged_character_id") != tagged_character_id
        ):
            continue
        db.delete(row)
        deleted += 1
    return deleted
