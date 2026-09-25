"""Social context for the anonymous Character Home timeline (Social Pan).

A Character Home is character-FIRST, not character-ISOLATED: beneath each
public post it shows the social evidence that already exists on that post —
aggregate reaction totals, the exact comment count, and the latest few
comments with safe attribution. This module builds that block.

It is a PROJECTION, built field by field from explicitly selected columns, and
it never touches the generic comment or reaction serializers. Those describe
social state to a signed-in member; this describes it to nobody in particular.
So nothing here can carry an account: no ``user_id``, no ``author_user_id``, no
username, no account sigil or account avatar — the account columns are never
selected, so they cannot be put on the wire by accident.

ADMISSION is the caller's job and is deliberately narrow. This module is only
ever handed post ids that have already passed the Home timeline's own
eligibility query (this character, PUBLIC realm, inner join). It does not
consult the generic post visibility rule and must never be used to discover
posts, only to decorate ones already admitted.

COMMENTER ATTRIBUTION, per comment:

====================================  ==========================================
commenter                             ``author``
====================================  ==========================================
PUBLIC and Home published             ``character``: name, safe avatar, id,
                                      ``linkable=True``
PUBLIC, Home not published            ``character``: name, safe avatar,
                                      ``linkable=False``, no id
PRIVATE / FRIENDS                     ``hidden_character``: nothing else
no character (Wanderer, or a          ``wanderer``: nothing else
character since deleted)
====================================  ==========================================

Linkability is :func:`character_home_is_publishable` — the same predicate that
admits the commenter's own Home — so a link can never point at a Home that
would answer 404. The character id is sent only alongside ``linkable=True``,
because the link is the only thing it is for.

A deleted character's comment has ``character_id`` NULL (``ON DELETE SET
NULL``) and cannot be told apart from a Wanderer's, so both are attributed
neutrally and identically; neither ever falls back to the account.

Every commenter avatar goes through :func:`resolve_public_media_urls`, the
avatar rule the Home applies to its own portrait. Unresolvable means ``None``;
the comment still renders.

QUERY SHAPE for a page of N posts, independent of N:

* one grouped reaction query (``post_id, type, count``), allowlisted types only;
* one comment query using window functions — ``row_number()`` for the latest
  :data:`COMMENT_PREVIEW_LIMIT` per post and ``count() over`` for the exact
  total — with the commenting character outer-joined in the same statement;
* the batched avatar resolution (two image-table queries), when any previewed
  commenter has an avatar.
"""
from datetime import datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models.character import Character, VisibilityEnum
from app.models.comment import Comment
from app.models.reaction import Reaction
from app.schemas.character_home import (
    CharacterHomeCommentAuthor,
    CharacterHomeCommentPreview,
    CharacterHomePostSocial,
)
from app.schemas.reaction import REACTION_TYPES
from app.services.character_home_media import resolve_public_media_urls
from app.services.character_publication import character_home_is_publishable

#: The latest comments previewed per post. The exact total travels beside them.
COMMENT_PREVIEW_LIMIT = 3


def _reaction_totals(db: Session, post_ids: list[int]) -> dict[int, dict[str, int]]:
    rows = (
        db.query(Reaction.post_id, Reaction.type, func.count(Reaction.id))
        .filter(Reaction.post_id.in_(post_ids), Reaction.type.in_(REACTION_TYPES))
        .group_by(Reaction.post_id, Reaction.type)
        .all()
    )
    totals: dict[int, dict[str, int]] = {}
    for post_id, type_, count in rows:
        if count:
            totals.setdefault(post_id, {})[type_] = count
    # Re-key in the allowlist's own order so every response is ordered alike.
    return {
        pid: {t: by_type[t] for t in REACTION_TYPES if t in by_type}
        for pid, by_type in totals.items()
    }


def _latest_comments(db: Session, post_ids: list[int]):
    """(post_id, comment_id, content, provenance, created_at, total, Character|None)
    for the latest COMMENT_PREVIEW_LIMIT comments of each post."""
    ranked = (
        select(
            Comment.id.label("id"),
            Comment.post_id.label("post_id"),
            func.row_number()
            .over(
                partition_by=Comment.post_id,
                order_by=(Comment.created_at.desc(), Comment.id.desc()),
            )
            .label("rn"),
            func.count(Comment.id).over(partition_by=Comment.post_id).label("total"),
        )
        .where(Comment.post_id.in_(post_ids))
        .subquery()
    )
    commenter = aliased(Character)
    return (
        db.query(
            ranked.c.post_id,
            Comment.id,
            Comment.content,
            Comment.provenance,
            Comment.created_at,
            ranked.c.total,
            commenter,
        )
        .join(ranked, ranked.c.id == Comment.id)
        .outerjoin(commenter, commenter.id == Comment.character_id)
        .filter(ranked.c.rn <= COMMENT_PREVIEW_LIMIT)
        .all()
    )


def _author(character, avatars: dict) -> CharacterHomeCommentAuthor:
    if character is None:
        return CharacterHomeCommentAuthor(kind="wanderer")
    if character.visibility != VisibilityEnum.PUBLIC:
        return CharacterHomeCommentAuthor(kind="hidden_character")
    linkable = character_home_is_publishable(character)
    return CharacterHomeCommentAuthor(
        kind="character",
        name=character.name,
        avatar_url=avatars.get(character.avatar_url) if character.avatar_url else None,
        character_id=character.id if linkable else None,
        linkable=linkable,
    )


def social_for_posts(db: Session, post_ids: Iterable[int]) -> dict[int, CharacterHomePostSocial]:
    """The social block for each already-admitted post id.

    Every requested id gets a block; one with no activity gets an empty block
    (``comment_count=0``, no reactions, no comments), and the client omits it.
    """
    ids = list(dict.fromkeys(post_ids))
    if not ids:
        return {}

    reactions = _reaction_totals(db, ids)
    rows = _latest_comments(db, ids)

    visible_characters = [
        r[6] for r in rows if r[6] is not None and r[6].visibility == VisibilityEnum.PUBLIC
    ]
    avatars = resolve_public_media_urls(db, [c.avatar_url for c in visible_characters])

    counts: dict[int, int] = {}
    previews: dict[int, list[tuple[datetime, int, CharacterHomeCommentPreview]]] = {}
    for post_id, comment_id, content, provenance, created_at, total, character in rows:
        counts[post_id] = total
        previews.setdefault(post_id, []).append((
            created_at,
            comment_id,
            CharacterHomeCommentPreview(
                id=comment_id,
                content=content,
                provenance=provenance or "unknown",
                created_at=created_at,
                author=_author(character, avatars),
            ),
        ))

    # Previews read oldest-first, like a conversation; the SELECTION was the
    # newest three, tie-broken on id, so the page is stable either way.
    return {
        pid: CharacterHomePostSocial(
            comment_count=counts.get(pid, 0),
            reactions=reactions.get(pid, {}),
            comments=[p for _, _, p in sorted(previews.get(pid, []), key=lambda t: (t[0], t[1]))],
        )
        for pid in ids
    }
