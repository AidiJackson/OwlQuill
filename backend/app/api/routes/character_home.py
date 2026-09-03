"""Anonymous Character Home read API (Character Home Step 4).

The first surface in Ficshon that answers a request carrying no token at all.
It is kept in its own module for exactly that reason: everything here is public
by construction, so "is this route anonymous?" is answered by which file it
lives in rather than by reading its dependencies.

Two rules govern it, and both live elsewhere so this module cannot be the place
they drift:

* :func:`character_home_is_publishable` — whether this character has a Home at
  all (PUBLIC *and* founder-granted permission, read together);
* :func:`resolve_public_media_url` — whether a given avatar/cover may be shown
  to an anonymous viewer.

Nothing authenticated changes shape because of this file. ``GET
/characters/{id}`` keeps its own visibility rule and its own schema.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.character import Character as CharacterModel
from app.schemas.character_home import CharacterHomePublic
from app.services.character_home_media import resolve_public_media_url
from app.services.character_publication import character_home_is_publishable

router = APIRouter()
logger = logging.getLogger(__name__)


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

    No gallery is embedded. The Home's media lives behind
    ``GET /characters/{id}/images``, which is gated by the same predicate for
    anonymous callers — one contract per surface, each independently testable,
    and no second pagination story to keep in step with the first.
    """
    character = (
        db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    )
    if not character_home_is_publishable(character):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

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
