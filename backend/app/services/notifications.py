"""Notification creation — the one place a ``Notification`` row is built.

Polish Phase 7.1 centralised row creation here. Every producer (W-10A's
character tags; Phase 7.2A comments; Phase 7.2B direct messages) goes through
:func:`create_notification` — or, for the one row that is updated in place,
:func:`_encode_payload` — so the account-owned row and its JSON-as-text
payload are written the same way everywhere.

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
from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.comment import Comment
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

#: Phase 7.2A. Another account commented on a post the recipient authored.
NOTIFICATION_TYPE_POST_COMMENTED = "post_commented"

#: Every type whose payload points at a post by ``post_id`` and may carry a
#: preview of its body (or, for comments, of the comment). Deleting the post
#: deletes these rows.
POST_NOTIFICATION_TYPES = frozenset({
    NOTIFICATION_TYPE_MENTION,
    NOTIFICATION_TYPE_CHARACTER_TAGGED,
    NOTIFICATION_TYPE_POST_COMMENTED,
})

#: Characters of post body a post notification may carry as its preview.
POST_PREVIEW_CHARS = 120

#: Phase 7.2B. Another account's character messaged one of the recipient's
#: characters. Points at a CONVERSATION, never a post, so it is deliberately
#: NOT in :data:`POST_NOTIFICATION_TYPES`. Carries no message text.
NOTIFICATION_TYPE_MESSAGE_RECEIVED = "message_received"


def _encode_payload(payload: Mapping[str, Any]) -> str:
    """The one payload encoding: compact JSON, ``None`` values dropped."""
    compact = {k: v for k, v in payload.items() if v is not None}
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


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
    notif = Notification(user_id=user_id, type=type, payload=_encode_payload(payload))
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


def notify_post_commented(
    db: Session,
    *,
    post: Post,
    realm: Optional[Realm],
    comment: Comment,
    commenter_character: Optional[Character],
) -> Notification:
    """Write the ``post_commented`` row for one new comment. Does NOT commit.

    The caller has created the comment and decided that the post's author
    should hear about it: a different account, not across a block. Called once
    per created comment, in the comment's own transaction — so a comment that
    fails to commit leaves no row, and one comment is at most one row.

    Payload contract (stable keys; the frontend renders from these):

      post_id, realm_id, comment_id — the target. Ids only; an id is not content.
      commenter_kind                — ``"character"`` or ``"wanderer"``.
      commenter_character_id/_name  — WHO commented, as a character. Snapshot.
                                      Absent for a Wanderer: the payload never
                                      carries an account username, even the
                                      public Wanderer one.
      post_character_id/_name       — WHICH of the recipient's characters wrote
                                      the post. Snapshot; absent if gone.
      realm_name, comment_preview   — ONLY when the recipient can access the
                                      realm (:func:`post_preview_permitted`).

    No account username or id is ever written.
    """
    recipient_user_id = post.author_user_id
    permitted = post_preview_permitted(db, recipient_user_id, realm)
    post_character = post.character
    payload: dict[str, Any] = {
        "post_id": post.id,
        "realm_id": post.realm_id,
        "comment_id": comment.id,
        "commenter_kind": "character" if commenter_character is not None else "wanderer",
        "commenter_character_id": commenter_character.id if commenter_character is not None else None,
        "commenter_character_name": commenter_character.name if commenter_character is not None else None,
        "post_character_id": post_character.id if post_character is not None else None,
        "post_character_name": post_character.name if post_character is not None else None,
        "realm_name": realm.name if (permitted and realm is not None) else None,
        "comment_preview": comment.content[:POST_PREVIEW_CHARS] if permitted else None,
    }
    return create_notification(
        db, user_id=recipient_user_id, type=NOTIFICATION_TYPE_POST_COMMENTED, payload=payload
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

    * Post deleted — call with ``post_id`` alone: every ``mention``,
      ``character_tagged`` and ``post_commented`` row for that post goes,
      because each may snapshot up to :data:`POST_PREVIEW_CHARS` of the deleted
      body or of one of its (cascade-deleted) comments.
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


def delete_comment_notifications(db: Session, comment_id: int) -> int:
    """Delete the ``post_commented`` row(s) for ``comment_id``. Does NOT commit.

    A comment notification may snapshot up to :data:`POST_PREVIEW_CHARS` of the
    comment, so it goes with the comment. Matched by parsing the payload and
    comparing ids as integers, exactly as :func:`delete_post_notifications`.

    Returns the number of rows deleted.
    """
    deleted = 0
    rows = db.query(Notification).filter(Notification.type == NOTIFICATION_TYPE_POST_COMMENTED).all()
    for row in rows:
        try:
            payload = json.loads(row.payload or "")
        except (TypeError, ValueError):
            continue
        if _payload_int(payload, "comment_id") != comment_id:
            continue
        db.delete(row)
        deleted += 1
    return deleted


# ── Phase 7.2B: direct messages ──────────────────────────────────────────────

def _unread_message_rows(db: Session, user_id: int, conversation_id: int) -> list[Notification]:
    """The account's UNREAD ``message_received`` rows for one conversation.

    Matched by parsing each payload and comparing ids as integers, as every
    other cleanup here does. Oldest first.
    """
    rows = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.type == NOTIFICATION_TYPE_MESSAGE_RECEIVED,
            Notification.is_read == False,  # noqa: E712
        )
        .order_by(Notification.id)
        .all()
    )
    out = []
    for row in rows:
        try:
            payload = json.loads(row.payload or "")
        except (TypeError, ValueError):
            continue
        if _payload_int(payload, "conversation_id") == conversation_id:
            out.append(row)
    return out


def notify_message_received(
    db: Session,
    *,
    recipient_user_id: int,
    conversation_id: int,
    sender_character: Character,
    recipient_character: Character,
) -> Notification:
    """Record one new message for its recipient. Does NOT commit.

    The caller has stored the message and decided the recipient should hear
    about it: a different account, in a conversation the sender may write to
    (which already excludes blocks). Called once per sent message, in the
    message's own transaction.

    **Grouped while unread.** A recipient has at most one UNREAD row per
    conversation: a further message UPDATES it — newest sender snapshot,
    ``message_count`` + 1, ``created_at`` moved to now so it sorts to the top —
    rather than adding a row. Once that row is read, the next message starts a
    new one. (This groups notifications; it does not de-duplicate messages: a
    retried send is still two messages, counted as two.)

    Payload contract (stable keys; the frontend renders from these):

      conversation_id                  — the target. An id only.
      sender_character_id/_name        — WHO wrote, as a character. Snapshot.
      recipient_character_id/_name     — WHICH of the recipient's characters
                                         was written to. Snapshot.
      message_count                    — messages grouped in this row, >= 1.

    No message text, and no account username or id, is ever written: the row
    can outlive the conversation (a later block, a deleted character), and then
    it must say nothing the conversation itself would no longer show.
    """
    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "sender_character_id": sender_character.id,
        "sender_character_name": sender_character.name,
        "recipient_character_id": recipient_character.id,
        "recipient_character_name": recipient_character.name,
    }
    existing = _unread_message_rows(db, recipient_user_id, conversation_id)
    if existing:
        row = existing[-1]
        try:
            previous = json.loads(row.payload or "")
        except (TypeError, ValueError):
            previous = {}
        count = _payload_int(previous, "message_count") or 1
        payload["message_count"] = count + 1
        row.payload = _encode_payload(payload)
        row.created_at = datetime.utcnow()
        return row
    payload["message_count"] = 1
    return create_notification(
        db, user_id=recipient_user_id, type=NOTIFICATION_TYPE_MESSAGE_RECEIVED, payload=payload
    )


def mark_conversation_notifications_read(db: Session, *, user_id: int, conversation_id: int) -> int:
    """Mark the account's unread ``message_received`` rows for one conversation
    read. Does NOT commit. Touches no other type, conversation or account.

    Returns the number of rows marked.
    """
    rows = _unread_message_rows(db, user_id, conversation_id)
    for row in rows:
        row.is_read = True
    return len(rows)
