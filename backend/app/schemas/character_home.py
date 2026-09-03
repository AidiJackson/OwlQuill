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
