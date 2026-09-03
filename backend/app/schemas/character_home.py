"""Public Character Home schemas (Character Home Step 4).

The anonymous projection of a character. Separate from ``schemas.character``
on purpose: that module describes a character to the people inside Ficshon who
already have a reason to be looking at it, and it grows whenever an internal
feature needs a new field. Anything reachable without a token must not inherit
that growth, so this schema is an ALLOWLIST maintained by hand — a field
appears here because someone decided it should be public, never because it was
added to the model.

Everything omitted is omitted structurally, not merely left unset, so no route
bug or ORM refresh can put it on the wire.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CharacterHomePublic(BaseModel):
    """A character as an anonymous visitor sees it.

    Identity and presentation, and nothing else.

    Deliberately absent, each for its own reason:

    * ``age`` — a real-world-sensitive attribute on a public page; excluded
      until there is a product decision to show it, not by oversight.
    * ``owner_id`` / ``owner_username`` / owner email — the character-first
      policy already applied by ``GET /characters/{id}``, which shows the owner
      link to the owner alone. An anonymous surface has no owner to show it to.
    * ``public_home_enabled``, ``visibility`` — publication mechanics. A visitor
      who can read this response already knows the Home is published; a visitor
      who cannot must not learn that the character exists at all.
    * ``visual_locked``, ``identity_spec_json``, ``identity_anchor_json``,
      ``identity_spec_version``, ``body_canon_json``, ``identity_health``,
      ``has_identity_canon`` — canon and private identity data plus generation
      metadata: the character's workshop, not the character.
    * ``portrait_url`` — an RP-sheet asset, not part of the Home's V1 surface,
      and not covered by the avatar/cover safety resolution below.
    * ``created_at`` / ``updated_at`` — internal record timing, no public use.

    ``avatar_url`` and ``cover_url`` are nullable HERE in a way they are not on
    the model: the route resolves each through the public-surface safety rule
    and sends ``None`` for an image that may not be shown anonymously. The
    positioning fields still travel, so a Home with a suppressed cover renders
    its fallback rather than a mispositioned one when a cover returns later.

    ``tags`` keeps the model's comma-separated string exactly as every other
    character schema exposes it. Reshaping it into a list would be a new
    contract to maintain in two places for no gain at this step.
    """

    id: int
    name: str
    alias: Optional[str] = None
    role: Optional[str] = None
    era: Optional[str] = None
    species: Optional[str] = None
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    tags: Optional[str] = None

    avatar_url: Optional[str] = None
    avatar_position_x: Optional[float] = None
    avatar_position_y: Optional[float] = None
    avatar_scale: Optional[float] = None

    cover_url: Optional[str] = None
    cover_position_x: Optional[float] = None
    cover_position_y: Optional[float] = None
    cover_scale: Optional[float] = None


class CharacterHomePostPublic(BaseModel):
    """One entry on a published Character Home's anonymous timeline.

    Built explicitly by the route, never validated from the ORM row and never
    borrowed from ``schemas.post.Post`` — that serializer carries
    ``author_user_id``, ``author_username`` and the mention list, and exists to
    describe a post to a signed-in member who is already inside Ficshon.

    Deliberately absent:

    * ``author_user_id`` / ``author_username`` — the character-first policy
      already strips these for non-authors of a character post. On a surface
      with no viewer at all there is nobody they could correctly be shown to.
    * ``character_id`` / ``character_name`` / ``character_avatar_url`` — the
      Home already IS the character, so repeating it adds nothing, and the
      avatar in particular would need its own safety resolution to be safe to
      echo here.
    * ``mentions`` — a mention row can resolve to a USER, and its ``target_id``
      is then an account id. The identity-first display rules make the rendered
      text safe, but the ids underneath are not, and V1 does not need them.
    * ``comment_count``, reactions — no comment or reaction data in Step 5.
    * ``updated_at`` — edit history. The Home is a chronology of what was
      published, keyed on ``created_at``.
    * ``provenance_evidence``, ``provenance_rule_version``,
      ``provenance_decided_at`` — the server-side reasoning behind the badge,
      as opposed to the badge.
    * ``source_type`` — retired, written by nothing.

    ``provenance`` itself IS included: it is Ficshon's public authorship badge,
    already shown to every viewer of a post today, and it is one short opaque
    string carrying nothing about the account. A Character Home that dropped it
    would present AI-assisted writing with the same silence as anything else.

    ``realm_id`` and ``realm_name`` are safe because the eligibility rule
    admits public realms only — a private realm's name can never reach this
    schema, since a post in one never becomes an entry.

    ``image_url`` is nullable HERE in a way the model's is not: an attachment
    the anonymous surface may not show is sent as ``None`` while the post's
    text publishes normally.

    There is no content or trigger warning field: the Post model has none. When
    one is added, it belongs on this schema, and its absence today is a gap in
    the product rather than a field withheld.
    """

    id: int
    title: Optional[str] = None
    content: str
    content_type: str
    post_kind: str
    provenance: str
    created_at: datetime
    image_url: Optional[str] = None
    realm_id: Optional[int] = None
    realm_name: Optional[str] = None
