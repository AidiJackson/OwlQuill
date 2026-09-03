"""Character Home publication predicate (Character Home Step 2).

One question, answered in one place: *is this character eligible to have an
anonymous Public Character Home?*

The rule has two independent halves and needs both:

* ``visibility == PUBLIC`` — the creator's own privacy choice, unchanged and
  still authoritative;
* ``public_home_enabled`` — founder-granted permission for a Character Home to
  be published at all.

``public_home_enabled`` is permission, never an override. A PRIVATE character
with the flag set stays unpublishable, which is why the flag is read *with*
visibility here rather than instead of it anywhere downstream.

This predicate governs the *anonymous* Character Home surface only, and every
anonymous surface must route through it:

* ``GET /characters/{id}/public-home`` — the Home profile itself (Step 4);
* ``GET /characters/{id}/images`` — the Home's gallery, for anonymous callers
  only. That endpoint predates the gate and was open to any PUBLIC character,
  which published a character's media while its Home stayed unpublished; Step 4
  closed that.

Existing *authenticated* character access — ``GET /characters/{id}``,
owner/creator workflows, and the signed-in branch of the images endpoint —
deliberately does not call it: adding it there would turn a publication
permission into a second authorization requirement for functionality that
already works.
"""
from typing import Optional

from app.models.character import Character, VisibilityEnum


def character_home_is_publishable(character: Optional[Character]) -> bool:
    """True when this character may have an anonymous Public Character Home.

    Requires PUBLIC visibility AND ``public_home_enabled``. Fail-closed: a
    missing character, or a flag that is NULL/absent on a row predating the
    column, reads as not publishable.
    """
    if character is None:
        return False
    if character.visibility != VisibilityEnum.PUBLIC:
        return False
    return bool(getattr(character, "public_home_enabled", False))
