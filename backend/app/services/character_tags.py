"""Explicit character tagging on posts (W-10A).

TAGGED is not AUTHORED. A tag is the author's deliberate statement that a post
concerns another character. It never touches ``posts.character_id`` or
``posts.author_kind``, never appears in the byline, and is not read by the
authored Timeline or the anonymous Character Home.

Three questions, answered here and nowhere else:

1. **May this character be tagged?** — :func:`validate_tag_targets`. The
   character must exist and be PUBLIC right now, and must not be the authoring
   character. Every refusal of a target the caller does not own reads the same
   (:data:`TAG_REFUSAL_DETAIL`), so the endpoint cannot be used to learn
   whether a PRIVATE/FRIENDS character, or any id at all, exists.

2. **Is a tag suppressed by a block?** — :func:`blocked_pairs`. A tag between
   accounts in a block relationship (either direction, the product's one
   definition, ``blocked_user_ids``) is STORED but inert: no notification, not
   on the tagged character's Tagged surface, and shown to nobody except the
   post's author. Refusing it, or hiding it from the author, would tell the
   author that a block exists. The rule is evaluated at read time, so a block
   created after tagging suppresses the tag too, and lifting it restores it.

3. **Which tags may this viewer see?** — :func:`project_tags_for_posts`.

   ===========================================  =============================
   viewer                                       sees the tag when
   ===========================================  =============================
   anonymous                                    never (W-10A shows no tags
                                                anonymously)
   the post's author                            character PUBLIC, or the
                                                author owns it
   the tagged character's owner                 not block-suppressed
   anyone else signed in                        PUBLIC and not block-suppressed
   ===========================================  =============================

   A character that becomes PRIVATE/FRIENDS keeps its row; the tag is hidden
   from everyone but its owner and reappears if it becomes PUBLIC again. A
   deleted character's rows are gone (ON DELETE CASCADE).

The projection emits :class:`TaggedCharacterRead` — the character id and its
LIVE name. No account field exists on that schema.

QUERY SHAPE for a page of posts: ``Post.character_tags`` and
``PostCharacterTag.character`` are ``selectin`` relationships, so the tags and
their characters arrive in two statements with the posts; the block check is
one more statement, issued only when the page has a cross-account tag.
"""
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.block import Block
from app.models.character import Character, VisibilityEnum
from app.schemas.post import TaggedCharacterRead

#: The one answer for a target that is missing, not PUBLIC, or otherwise not
#: taggable. Identical for every such case so it confirms nothing.
TAG_REFUSAL_DETAIL = "One or more of those characters can't be tagged."

#: The authoring character tagging itself. The caller owns it, so saying so
#: reveals nothing.
SELF_TAG_DETAIL = "A character can't tag itself."


def validate_tag_targets(
    db: Session, character_ids: list[int], author_character: Character
) -> list[Character]:
    """Return the characters to tag, in request order, or raise 422.

    ``character_ids`` has already been de-duplicated and capped by the schema.
    Blocks are deliberately NOT consulted here — see the module docstring.
    """
    if not character_ids:
        return []
    if author_character.id in character_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=SELF_TAG_DETAIL)

    found = {
        c.id: c
        for c in db.query(Character).filter(Character.id.in_(character_ids)).all()
    }
    targets = []
    for cid in character_ids:
        character = found.get(cid)
        if character is None or character.visibility != VisibilityEnum.PUBLIC:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=TAG_REFUSAL_DETAIL
            )
        targets.append(character)
    return targets


def blocked_pairs(db: Session, pairs: Iterable[tuple[int, int]]) -> set[frozenset]:
    """The subset of account pairs that are in a block relationship, either way.

    The same relation as ``app.services.safety.blocked_user_ids`` (a ``Block``
    row in either direction), asked for many pairs at once: one query for any
    number of pairs rather than one per distinct account. Pairs of an account with itself are
    never blocked and are not queried.
    """
    wanted = {frozenset(p) for p in pairs if p[0] != p[1]}
    if not wanted:
        return set()
    ids = set().union(*wanted)
    rows = (
        db.query(Block.blocker_id, Block.blocked_id)
        .filter(Block.blocker_id.in_(ids), Block.blocked_id.in_(ids))
        .all()
    )
    return {frozenset(r) for r in rows} & wanted


def _visible(viewer_id: int, post_author_id: int, character: Character, suppressed: bool) -> bool:
    is_public = character.visibility == VisibilityEnum.PUBLIC
    if viewer_id == post_author_id:
        # The author always sees what they wrote — hiding a blocked tag from
        # them would reveal the block — but not a since-hidden character.
        return is_public or character.owner_id == viewer_id
    if suppressed:
        return False
    return is_public or character.owner_id == viewer_id


def project_tags_for_posts(db: Session, posts, viewer) -> dict[int, list[TaggedCharacterRead]]:
    """Every post's tags, filtered for ``viewer``, keyed by post id."""
    posts = list(posts)
    result: dict[int, list[TaggedCharacterRead]] = {p.id: [] for p in posts}
    if viewer is None:
        return result

    live = [
        (post, tag.character)
        for post in posts
        for tag in (post.character_tags or [])
        if tag.character is not None
    ]
    if not live:
        return result

    suppressed = blocked_pairs(
        db, [(post.author_user_id, character.owner_id) for post, character in live]
    )
    for post, character in live:
        pair_blocked = frozenset((post.author_user_id, character.owner_id)) in suppressed
        if _visible(viewer.id, post.author_user_id, character, pair_blocked):
            result[post.id].append(
                TaggedCharacterRead(character_id=character.id, name=character.name)
            )
    return result


def tagged_surface_exclusions(db: Session, viewer_id: int, owner_id: int) -> set[int]:
    """Post authors to leave off a character's Tagged surface.

    Authors in a block relationship with the VIEWER (as the feed already does)
    or with the tagged character's OWNER (so a blocked tag never shows up on
    the character it names, for anyone).
    """
    from app.services.safety import blocked_user_ids

    excluded = set(blocked_user_ids(db, viewer_id))
    if owner_id != viewer_id:
        excluded |= blocked_user_ids(db, owner_id)
    return excluded
