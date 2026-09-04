"""Anonymous Character Home read API (Character Home Steps 4 and 5).

The surfaces in Ficshon that answer a request carrying no token at all — the
Home's profile, its gallery, and its chronological timeline.
It is kept in its own module for exactly that reason: everything here is public
by construction, so "is this route anonymous?" is answered by which file it
lives in rather than by reading its dependencies.

Two rules govern it, and both live elsewhere so this module cannot be the place
they drift:

* :func:`character_home_is_publishable` — whether this character has a Home at
  all (PUBLIC *and* founder-granted permission, read together);
* :func:`resolve_public_media_url` / :func:`resolve_public_post_image_url` —
  whether a given avatar, cover or post attachment may be shown to an anonymous
  viewer;
* :func:`is_public_gallery_visible` — whether a given image belongs in the
  Home's gallery, being the creator's selection AND Ficshon's own eligibility
  rule, composed but never merged.

NOT ONE of these routes takes an authentication dependency, optional or
otherwise. A Character Home is a public projection: the same visitor sees the
same Home whether they arrive logged out, logged in as a stranger, logged in as
the creator, or as an admin. Making the result depend on who is asking would
mean the creator could never see what they had actually published, and it is
precisely how an unselected working image ends up on a public page. A creator
who wants their full library uses the authenticated image routes, which are a
different surface answering a different question.

Nothing authenticated changes shape because of this file. ``GET
/characters/{id}`` keeps its own visibility rule and its own schema.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage as CharacterImageModel, ImageStatusEnum
from app.models.post import Post as PostModel
from app.models.realm import Realm as RealmModel
from app.schemas.character_home import CharacterHomePostPublic, CharacterHomePublic
from app.schemas.character_image import CharacterImagePublic, is_public_gallery_visible
from app.services.character_home_media import (
    resolve_public_media_url,
    resolve_public_post_image_url,
)
from app.services.character_publication import character_home_is_publishable

router = APIRouter()
logger = logging.getLogger(__name__)


def _publishable_or_404(db: Session, character_id: int) -> CharacterModel:
    """Admission for every anonymous Character Home surface.

    One function so the profile and the timeline cannot answer the same
    question differently, and so a surface added later has an obvious thing to
    call. The 404 is identical in status and body to a nonexistent id.
    """
    character = (
        db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    )
    if not character_home_is_publishable(character):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    return character


@router.get(
    "/{character_id}/public-home",
    response_model=CharacterHomePublic,
    summary="Public Character Home profile (no authentication)",
)
def get_public_character_home(
    character_id: int,
    db: Session = Depends(get_db),
) -> CharacterHomePublic:
    """The anonymous public profile for a published Character Home.

    Requires no credentials. A character that is not publishable — missing,
    PRIVATE, FRIENDS, or PUBLIC without the founder grant — answers 404 with
    the same body as a nonexistent id, because distinguishing them would leak
    the existence of unpublished and private characters to anyone willing to
    walk the id space. This is the same 404-not-403 convention ``GET
    /characters/{id}`` already uses for private characters.

    The response is built field by field into :class:`CharacterHomePublic`. The
    ORM row is never handed to the serializer, so a column added to the model
    later cannot appear here without someone adding it to the schema too.

    Neither the gallery nor the timeline is embedded. The Home's media lives
    behind ``GET /characters/{id}/public-home/images`` and its posts behind
    ``GET /characters/{id}/public-home/posts``, both admitted by the same
    predicate — one contract per surface, each independently testable, and no
    second pagination story to keep in step with the first.
    """
    character = _publishable_or_404(db, character_id)

    return CharacterHomePublic(
        id=character.id,
        name=character.name,
        alias=character.alias,
        role=character.role,
        era=character.era,
        species=character.species,
        short_bio=character.short_bio,
        long_bio=character.long_bio,
        tags=character.tags,
        avatar_url=resolve_public_media_url(db, character.avatar_url),
        avatar_position_x=character.avatar_position_x,
        avatar_position_y=character.avatar_position_y,
        avatar_scale=character.avatar_scale,
        cover_url=resolve_public_media_url(db, character.cover_url),
        cover_position_x=character.cover_position_x,
        cover_position_y=character.cover_position_y,
        cover_scale=character.cover_scale,
    )


@router.get(
    "/{character_id}/public-home/images",
    response_model=list[CharacterImagePublic],
    summary="Public Character Home gallery (no authentication)",
)
def get_public_character_home_images(
    character_id: int,
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[CharacterImagePublic]:
    """The anonymous gallery for a published Character Home.

    THE canonical Character Home gallery contract. ``GET
    /characters/{id}/images`` is a different surface — the creator's working
    library, authenticated — and is no longer a public gallery at all.

    ADMISSION is three independent layers, all required, and none able to stand
    in for another:

    1. the Home is published — :func:`character_home_is_publishable`, applied by
       ``_publishable_or_404`` exactly as the profile and timeline apply it, so
       a gallery can never be reachable for a character whose Home is not;
    2. the creator selected the image — ``public_gallery_enabled``;
    3. Ficshon will expose the image — :func:`is_public_gallery_image`, which
       covers kind, ACTIVE status, unaccepted temp previews and studio
       provenance.

    Layers 2 and 3 are composed by :func:`is_public_gallery_visible` and are
    deliberately NOT merged: creator selection is checked alongside the safety
    rule, never inside it, so selecting an image can only ever subtract from
    what Ficshon allows and never add to it. That is also why the ``status ==
    ACTIVE`` filter below duplicates a condition the predicate already enforces
    — the query narrows for cost, the predicate decides for correctness, and
    removing either leaves the other still correct.

    THE RESULT DOES NOT DEPEND ON WHO IS ASKING. This route takes no
    authentication dependency at all, not even an optional one, so a token
    cannot widen it: logged out, signed-in stranger, the creator and an admin
    all receive byte-identical output. A creator inspecting their own Home sees
    what visitors see, which is the only way "what have I actually published?"
    has an honest answer. Their full working library remains at ``GET
    /characters/{id}/images`` and ``GET /users/me/character-images``.

    The response is :class:`CharacterImagePublic` — id, character_id, kind,
    created_at, url and nothing else. ``public_gallery_enabled`` is absent on
    purpose: it is the creator's own curation state, and to a visitor looking at
    an image that is already on the page it is not information. Provider names,
    prompts, seeds, raw metadata, owning account id, internal visibility and
    status are absent from the schema rather than merely unset, so none of them
    can leak by someone later handing this route an ORM row.

    Ordering is newest-first with ``id`` as a tie-break, matching the timeline,
    so a gallery is stable when seeded rows share a timestamp. ``limit`` is
    bounded because this is an unauthenticated endpoint; its default is higher
    than the timeline's because a gallery grid shows more at once than a page of
    posts.
    """
    _publishable_or_404(db, character_id)

    rows = (
        db.query(CharacterImageModel)
        .filter(
            CharacterImageModel.character_id == character_id,
            CharacterImageModel.status == ImageStatusEnum.ACTIVE,
            CharacterImageModel.public_gallery_enabled.is_(True),
        )
        .order_by(CharacterImageModel.created_at.desc(), CharacterImageModel.id.desc())
        .limit(limit)
        .all()
    )

    return [
        CharacterImagePublic.from_image(row)
        for row in rows
        if is_public_gallery_visible(row)
    ]


@router.get(
    "/{character_id}/public-home/posts",
    response_model=list[CharacterHomePostPublic],
    summary="Public Character Home timeline (no authentication)",
)
def get_public_character_home_posts(
    character_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[CharacterHomePostPublic]:
    """The anonymous chronological timeline for a published Character Home.

    Admission is the Home's own publication rule, so the timeline can never be
    reachable for a character whose profile is not.

    ELIGIBILITY is three independent conditions, all enforced in the query:

    * ``character_id`` matches exactly — posts by another character, and
      characterless account posts, are absent. The join on ``character_id``
      does both: a legacy account post has ``NULL`` there and cannot match.
    * the post's realm is PUBLIC. This is an INNER join against
      ``realms.is_public``, which is deliberately not how the authenticated
      ``GET /characters/{id}/posts`` decides — that endpoint filters by the
      viewer's own memberships, which is right for a member and meaningless for
      a visitor who has none. Membership is not a substitute for realm
      visibility, and an anonymous reader joins nothing. The inner join also
      excludes a post with no realm at all: a realm-less post has no public
      realm to be public in, so it fails closed.
    * the post exists. The Post model carries no soft-delete, hidden, or
      moderation column and ``DELETE /posts/{id}`` removes the row outright, so
      "not deleted" and "still selectable" are the same condition. If a
      moderation state is added later it belongs in this filter.

    Ordering is newest-first on ``created_at``, matching the authenticated
    character timeline, with ``id`` as a tie-break so a page is stable when
    seeded rows share a timestamp. ``limit`` reuses that endpoint's bounds
    (default 20, max 100) rather than inventing a second pagination story.

    Every attachment is re-checked through
    :func:`resolve_public_post_image_url`: an unsafe, withdrawn or
    unestablished image becomes ``None`` and the post's text still publishes.
    A post is never dropped because of its image.
    """
    _publishable_or_404(db, character_id)

    rows = (
        db.query(PostModel, RealmModel.name)
        .join(RealmModel, PostModel.realm_id == RealmModel.id)
        .filter(
            PostModel.character_id == character_id,
            RealmModel.is_public.is_(True),
        )
        .order_by(PostModel.created_at.desc(), PostModel.id.desc())
        .limit(limit)
        .all()
    )

    return [
        CharacterHomePostPublic(
            id=post.id,
            title=post.title,
            content=post.content,
            content_type=post.content_type.value,
            post_kind=post.post_kind,
            provenance=post.provenance,
            created_at=post.created_at,
            image_url=resolve_public_post_image_url(db, post.image_url),
            realm_id=post.realm_id,
            realm_name=realm_name,
        )
        for post, realm_name in rows
    ]
