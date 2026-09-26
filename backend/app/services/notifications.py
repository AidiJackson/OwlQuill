"""Notification creation — the one place a ``Notification`` row is built.

Polish Phase 7.1. Before this module, the only producer (the @mention path in
``routes/posts.py``) constructed its row inline, so the payload's shape lived
in a route body and nowhere else. Every future producer (Phase 7.2: comments,
Story Space invites, direct messages) goes through :func:`create_notification`
so the account-owned row and its JSON-as-text payload are written the same way
everywhere.

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

#: A realm post @mentioned one of the recipient's characters.
NOTIFICATION_TYPE_MENTION = "mention"

#: Characters of post body a mention notification may carry as its preview.
MENTION_PREVIEW_CHARS = 120


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


def mention_preview_permitted(db: Session, recipient_user_id: int, realm: Optional[Realm]) -> bool:
    """May this recipient be shown the mentioning post's text?

    The same question as "may this account open the realm", answered by the
    same helper that gates the realm and post routes — so a notification can
    never show more than the destination it links to would. A public realm:
    yes. A private realm: only an owner or member. No realm on the post:
    nothing realm-scoped to protect.
    """
    return user_can_access_realm(db, recipient_user_id, realm)


def notify_character_mentioned(
    db: Session,
    *,
    recipient_user_id: int,
    post: Post,
    realm: Optional[Realm],
    author_character: Character,
    mentioned_character: Character,
    mention_text: str,
    content: str,
) -> Notification:
    """Write the ``mention`` row for one resolved @mention. Does NOT commit.

    The caller has already resolved ``mentioned_character`` through the
    mention system and established that its owner is not the author; this
    function does no name resolution of its own and never will — the addressing
    rules (and their non-unique-name debt) belong to ``services/mentions.py``.

    Payload contract (stable keys; the frontend renders from these):

      post_id, realm_id             — the target. Ids only; an id is not content.
      author_character_id/_name     — WHO did it, as a character. Snapshot.
      mentioned_character_id/_name  — WHICH of the recipient's characters was
                                      addressed. New in 7.1: an account with
                                      several characters could not previously
                                      tell them apart.
      mention_text                  — the literal ``@Handle`` as written.
      realm_name, post_preview      — ONLY when the recipient can access the
                                      realm. A private realm's name is itself
                                      withheld by ``GET /realms/{id}`` for
                                      non-members, so it follows the same rule
                                      as the excerpt.

    Legacy rows (pre-7.1) carry ``author_character_name``, ``mention_text``,
    ``post_preview`` and a now-unused ``target_type``; they keep rendering
    because the reader falls back key by key.
    """
    permitted = mention_preview_permitted(db, recipient_user_id, realm)
    payload: dict[str, Any] = {
        "post_id": post.id,
        "realm_id": post.realm_id,
        "author_character_id": author_character.id,
        "author_character_name": author_character.name,
        "mentioned_character_id": mentioned_character.id,
        "mentioned_character_name": mentioned_character.name,
        "mention_text": mention_text,
        "realm_name": realm.name if (permitted and realm is not None) else None,
        "post_preview": content[:MENTION_PREVIEW_CHARS] if permitted else None,
    }
    return create_notification(
        db, user_id=recipient_user_id, type=NOTIFICATION_TYPE_MENTION, payload=payload
    )


def delete_mention_notifications_for_post(db: Session, post_id: int) -> int:
    """Delete every mention notification that points at ``post_id``. Does NOT commit.

    Called when a post is deleted. A mention row snapshots up to
    ``MENTION_PREVIEW_CHARS`` of the post body, so leaving it behind would keep
    the deleted text readable in the recipient's notification list.

    Matched by PARSING each payload and comparing ``post_id`` as an integer —
    never by a text match on the JSON, where ``"post_id":1`` is a prefix of
    ``"post_id":12``. Only ``mention`` rows are considered; a malformed payload
    is left alone rather than guessed at. Scans the mention rows in Python,
    which is fine at closed-beta volume and keeps notification storage as it is.

    Returns the number of rows deleted.
    """
    deleted = 0
    rows = db.query(Notification).filter(
        Notification.type == NOTIFICATION_TYPE_MENTION
    ).all()
    for row in rows:
        try:
            payload = json.loads(row.payload or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        target = payload.get("post_id")
        # bool is an int subclass; True must not match post 1.
        if type(target) is int and target == post_id:
            db.delete(row)
            deleted += 1
    return deleted
