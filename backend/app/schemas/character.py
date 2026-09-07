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
    """
    pass


class CharacterUpdate(BaseModel):
    """Character update schema.

    Same omission as :class:`CharacterBase`, for the same reason, and written
    out as its own field list rather than derived from it so that adding a field
    to one does not silently add it to the other.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
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
    """
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    portrait_url: Optional[str] = None
    id: int
    owner_id: int
    owner_username: Optional[str] = None
    visual_locked: bool = False
    # True when the character has a generated identity canon (a face_front image
    # exists), even if it has not been locked yet. Used by the character list to
    # route existing characters to their detail page instead of the creation flow
    # (S24AR). Populated by the route layer; defaults False elsewhere.
    has_identity_canon: bool = False
    identity_anchor_json: Optional[str] = None
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
