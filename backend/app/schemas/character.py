"""Character schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.character import VisibilityEnum


class CharacterBase(BaseModel):
    """Fields a client may WRITE on a character.

    ``avatar_url``, ``cover_url`` and ``portrait_url`` are deliberately ABSENT
    (Beta Boundary 2). They used to live here, which made them ordinary create/
    update fields and therefore a route by which any account could point its
    character at an arbitrary third-party image — the display half of the same
    product rule Beta Boundary 1 closed for conditioning inputs.

    Avatar and cover are set through ``POST /characters/{id}/avatar`` and
    ``POST /characters/{id}/cover``, which take an ASSET ID and check that it
    exists, is ACTIVE, is not temporary, belongs to the caller, is
    public-surface-safe and is of an eligible kind. A raw string here could
    satisfy none of those, so removing the field is the fix; a validator on it
    would only be a weaker copy of the setter that already exists.

    ``portrait_url`` (RP sheets) has no governed setter and no asset model, so
    it is simply retired as a writable field rather than replaced. Nothing in
    character creation depends on it.

    THE NUMERIC FRAMING FIELDS STAY WRITABLE and are the reason this removal is
    invisible to the product: the picker calls the governed setter for the image
    and ``PATCH /characters/{id}`` for ``avatar_position_x/y``, ``avatar_scale``,
    ``cover_position_x/y`` and ``cover_scale``. Those carry no pointer.
    """
    name: str = Field(..., min_length=1, max_length=100)
    alias: Optional[str] = None
    age: Optional[str] = None
    species: Optional[str] = None
    role: Optional[str] = None
    era: Optional[str] = None
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    cover_position_y: Optional[float] = 0.5
    cover_position_x: Optional[float] = 0.5
    cover_scale: Optional[float] = 1.0
    avatar_position_x: Optional[float] = 0.5
    avatar_position_y: Optional[float] = 0.5
    avatar_scale: Optional[float] = 1.0
    tags: Optional[str] = None
    visibility: VisibilityEnum = VisibilityEnum.PUBLIC


class CharacterCreate(CharacterBase):
    """Character creation schema.

    Carries no image pointer at all. A character is created from words and
    receives its visual identity from Ficshon — see ``CharacterBase``.

    ``name`` is re-declared WITHOUT length constraints: the authoritative
    name/alias policy, length included, runs in the route through
    ``app.services.character_names`` after normalisation (so "  Pan  " is
    measured as "Pan"), and answers with one readable sentence. The
    constraints stay on ``CharacterBase`` because that is also the read schema.
    """
    name: str


class CharacterUpdate(BaseModel):
    """Character update schema.

    Same omission as :class:`CharacterBase`, for the same reason, and written
    out as its own field list rather than derived from it so that adding a field
    to one does not silently add it to the other.

    ``name`` carries no length constraint here for the same reason as
    :class:`CharacterCreate`. An explicit ``null`` for ``name`` or
    ``visibility`` is refused by the route (both columns are NOT NULL);
    omitting a field still means "leave it alone".
    """
    name: Optional[str] = None
    alias: Optional[str] = None
    age: Optional[str] = None
    species: Optional[str] = None
    role: Optional[str] = None
    era: Optional[str] = None
    short_bio: Optional[str] = None
    long_bio: Optional[str] = None
    cover_position_y: Optional[float] = None
    cover_position_x: Optional[float] = None
    cover_scale: Optional[float] = None
    avatar_position_x: Optional[float] = None
    avatar_position_y: Optional[float] = None
    avatar_scale: Optional[float] = None
    tags: Optional[str] = None
    visibility: Optional[VisibilityEnum] = None


class Character(CharacterBase):
    """Character as READ back from the API.

    The three image pointers reappear here because reading them is legitimate
    and the client renders them; only writing them was ever the problem. They
    are populated by the route, which passes ``avatar_url`` and ``cover_url``
    through the public-media resolver first — see
    ``app.services.character_projection``.

    VIEWER-AWARE (Polish Phase 5.1). Four fields are OWNER-ONLY and are
    ``None`` for anyone else, applied by ``project_character`` on the server —
    never by the client deciding what to hide:

    * ``owner_id`` — a public character must not be traceable to the account
      that owns it (identity-first policy). The directory and search never
      carried it; the detail read did, which let two public characters be
      clustered by account. The client never needed the number: what it asks
      is "may I manage this?", and ``is_owner`` answers that directly.
    * ``owner_username`` — same rule, already owner-only before this pass.
    * ``identity_anchor_json`` — identity infrastructure (lock string, prompt
      hash, anchor image urls). The anchors are working references the media
      surface deliberately withholds from visitors; this string handed them
      over. Owner surfaces (generation readiness) still read it.
    * ``identity_health`` — derived from the same anchor data (which slots
      exist and whether they are stale). Owner tooling state, not a fact about
      the character a visitor has any use for, so it goes with its source.

    ``is_owner`` is the one ownership signal the client uses. Every route that
    returns this schema sets it: the owner-scoped routes (create, list, update)
    to ``True``; the detail read to whatever the viewer actually is.
    """
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    portrait_url: Optional[str] = None
    id: int
    #: Owner-only; ``None`` for every other viewer.
    owner_id: Optional[int] = None
    #: Owner-only; ``None`` for every other viewer.
    owner_username: Optional[str] = None
    #: True when the caller owns this character. The client's only ownership
    #: signal — it must not be derived from ``owner_id``.
    is_owner: bool = False
    visual_locked: bool = False
    # True when the character has a generated identity canon (a face_front image
    # exists), even if it has not been locked yet. Used by the character list to
    # route existing characters to their detail page instead of the creation flow
    # (S24AR). Populated by the route layer; defaults False elsewhere.
    has_identity_canon: bool = False
    #: Owner-only; ``None`` for every other viewer (see the class docstring).
    identity_anchor_json: Optional[str] = None
    #: Owner-only; ``None`` for every other viewer.
    identity_health: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CharacterSearchResult(BaseModel):
    """Lightweight schema returned from character search."""
    id: int
    name: str
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    cover_position_y: Optional[float] = 0.5
    cover_position_x: Optional[float] = 0.5
    cover_scale: Optional[float] = 1.0
    avatar_position_x: Optional[float] = 0.5
    avatar_position_y: Optional[float] = 0.5
    avatar_scale: Optional[float] = 1.0
    short_bio: Optional[str] = None
    species: Optional[str] = None
    visibility: VisibilityEnum = VisibilityEnum.PUBLIC

    model_config = {"from_attributes": True}
