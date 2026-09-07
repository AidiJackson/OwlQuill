"""Character read projections that apply the public-media safety rule.

WHY THIS EXISTS. ``Character.avatar_url`` and ``Character.cover_url`` are plain
denormalised strings. The Character Home and the share/OG metadata have resolved
them through :func:`resolve_public_media_url` since Phase 4D2, so a pointer with
no image row behind it is withheld rather than rendered. Three other surfaces
that emit the same two columns never got that treatment and returned them raw:

  * ``GET /characters/directory`` — the Wanderer browse surface, every PUBLIC
    character, shown to any signed-in account;
  * ``GET /characters/search`` — same schema, feeds the message-recipient picker;
  * ``GET /characters/{id}`` — the full character, shown to any viewer of a
    PUBLIC character;
  * ``GET|POST /messages/conversations`` — the messaging summary, which carries
    the same column to the other participant.

The Beta Boundary 2 audit found the divergence: the same stored string that the
Home suppresses, the directory rendered. Closing the WRITE path (the pointer
fields are gone from ``CharacterCreate``/``CharacterUpdate``) stops new ones
arriving; this closes the READ path, which is the half that also covers values
already in the database, a founder or migration writing the column directly, and
any serializer added later that forgets to ask.

WHAT IT DOES NOT DO. It never writes. The resolver's verdict is applied to the
SCHEMA instance, never to the ORM object — assigning to ``character.avatar_url``
would mark the row dirty and a later flush would persist a suppression as a
deletion. The owner keeps every value they had; only what leaves the server
changes.

It also does not re-implement the rule. :func:`resolve_public_media_url` and its
batched form remain the single definition of "safe enough to show", shared with
the Home, the OG card, posts and comments, so these surfaces cannot drift from
those.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from app.schemas.character import Character as CharacterSchema
from app.schemas.character import CharacterSearchResult
from app.schemas.messaging import CharacterSummary
from app.services.character_home_media import (
    resolve_public_media_url,
    resolve_public_media_urls,
)


def project_character(db: Session, character) -> CharacterSchema:
    """One character, with its avatar and cover put through the safety rule.

    Call AFTER the route has attached its computed extras (``owner_username``,
    ``identity_health``, ``has_identity_canon``) to *character*, since those are
    read off the object during validation.
    """
    out = CharacterSchema.model_validate(character)
    out.avatar_url = resolve_public_media_url(db, out.avatar_url)
    out.cover_url = resolve_public_media_url(db, out.cover_url)
    return out


def project_characters(db: Session, characters: Iterable) -> list[CharacterSchema]:
    """:func:`project_character` for a list, resolving every pointer in one pass.

    A roster or a directory page asks the same question about the same one or
    two urls repeatedly; the per-character form would issue two queries each.
    """
    characters = list(characters)
    resolved = _batch(db, characters)
    out: list[CharacterSchema] = []
    for character in characters:
        schema = CharacterSchema.model_validate(character)
        schema.avatar_url = _lookup(resolved, schema.avatar_url)
        schema.cover_url = _lookup(resolved, schema.cover_url)
        out.append(schema)
    return out


def project_search_results(db: Session, characters: Iterable) -> list[CharacterSearchResult]:
    """The directory/search projection — same rule, narrower schema.

    ``CharacterSearchResult`` carries no owner fields by design (identity-first
    policy); this adds the media rule to it without widening what it exposes.
    """
    characters = list(characters)
    resolved = _batch(db, characters)
    out: list[CharacterSearchResult] = []
    for character in characters:
        schema = CharacterSearchResult.model_validate(character)
        schema.avatar_url = _lookup(resolved, schema.avatar_url)
        schema.cover_url = _lookup(resolved, schema.cover_url)
        out.append(schema)
    return out


def project_character_summaries(
    db: Session, characters: Iterable
) -> list[CharacterSummary]:
    """The messaging summary — id, name, avatar — with the avatar resolved.

    Messaging was the last serializer emitting ``Character.avatar_url`` straight
    off the column. It is a PRIVATE 1:1 surface, so nothing about who may see a
    conversation changes here and no public-character visibility rule is
    introduced: the participants are exactly who they were. What changes is that
    the avatar answers to the same media rule it answers to everywhere else, so
    a pointer with no image row behind it is withheld rather than fetched by the
    other participant's browser.

    Batched because ``GET /messages/conversations`` serialises two characters
    per conversation, and a roster of twenty would otherwise pay forty queries
    to answer the same question about the same one or two avatars.
    """
    characters = list(characters)
    resolved = resolve_public_media_urls(
        db, [getattr(c, "avatar_url", None) for c in characters]
    )
    out: list[CharacterSummary] = []
    for character in characters:
        schema = CharacterSummary.model_validate(character)
        schema.avatar_url = _lookup(resolved, schema.avatar_url)
        out.append(schema)
    return out


def _batch(db: Session, characters: Sequence) -> dict[str, Optional[str]]:
    """One resolver call covering every avatar and cover in *characters*."""
    urls: list[Optional[str]] = []
    for character in characters:
        urls.append(getattr(character, "avatar_url", None))
        urls.append(getattr(character, "cover_url", None))
    return resolve_public_media_urls(db, urls)


def _lookup(resolved: dict[str, Optional[str]], url: Optional[str]) -> Optional[str]:
    """The verdict for *url*, defaulting to withheld.

    A url missing from the batch is treated as unsafe rather than passed
    through, matching how every other batched caller in this codebase reads
    these maps: the fail-closed default is what makes a lookup miss a suppressed
    image instead of an unresolved one.
    """
    if not url:
        return None
    return resolved.get(url)
