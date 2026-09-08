"""Clearing the governed avatar/cover pointers that name a WITHDRAWN asset.

WHY THIS EXISTS. Archiving is the owner's delete: the two delete routes flip
``CharacterImage.status`` to ARCHIVED rather than removing the row, so
provenance, ownership and lineage survive the deletion of the picture. Since
this increment, ARCHIVED also means WITHDRAWN — ``is_public_media`` refuses an
archived row, so every shared surface fed by ``resolve_public_media_url`` stops
projecting it.

That suppression alone leaves the DATABASE in a state nobody asked for. Four
columns are plain denormalised strings with no foreign key —
``Character.avatar_url``, ``Character.cover_url``, ``User.avatar_url``,
``User.cover_url`` — and each keeps pointing at the archived asset afterwards.
The owner sees a portrait they deleted still named as their character's current
avatar in their own editor, the pointer is what a later re-vetting or a
different resolver would read, and "the read path hides it" is a weaker promise
than "the pointer is gone". So the write path clears it, in the SAME
transaction that archives the row.

IDENTITY, AND WHY IT IS STRING-SHAPED. There is no FK to follow back, so the
only identity available is the stored file. :func:`urls_naming_file_path` is the
exact inverse of the resolver's own :func:`candidate_file_paths`, so a pointer
is cleared when and only when the resolver would have said that pointer names
THIS row. A pointer that merely resembles the asset — a different file with a
similar name, a bare spelling the resolver does not treat as equivalent — is
left alone.

SCOPED TO THE ASSET'S OWNING ACCOUNT. Only pointers belonging to
``image.user_id`` are considered: that account's own characters, and that
account's own profile. Every route that writes one of these four columns
already requires the image and the target to belong to the caller
(``POST /characters/{id}/avatar`` and its siblings refuse ``img.user_id !=
current_user.id``), so a cross-account pointer is not a thing the product
creates. If one existed anyway, archiving somebody else's asset must not reach
into their profile — and the resolver suppresses it regardless.

WHAT IT DOES NOT DO:

* it does not delete bytes. No object is removed, no bucket setting changes,
  and an anonymous party already holding the direct public R2/static URL can
  still fetch the file. Application-layer withdrawal only;
* it does not touch canon. Live canon references are protected upstream: both
  delete routes refuse to archive an asset canon points at, and that refusal
  runs BEFORE this does;
* it does not restore. There is no un-archive in the product for beta, and
  clearing a pointer is not reversible by re-activating a row;
* it does not touch a built-in account sigil. Those are inline SVG marks with
  no bytes and no row (``app.core.account_sigils``); they can never appear in a
  file-path spelling set, and the branch is written out anyway so the exemption
  is visible rather than incidental.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.account_sigils import is_account_sigil
from app.models.character import Character
from app.models.user import User
from app.services.character_home_media import urls_naming_file_path

logger = logging.getLogger(__name__)


def clear_governed_pointers_for(db: Session, image) -> list[str]:
    """Clear every avatar/cover pointer that names *image*. Returns what changed.

    Call INSIDE the archiving transaction and before its ``commit``, so an
    asset is never withdrawn without its pointers going with it, and a failed
    commit rolls back both.

    *image* is duck-typed on ``file_path`` and ``user_id``, so it accepts a
    ``CharacterImage`` (both delete routes archive one of these — including the
    account-owned avatar crop, whose ``character_id`` is NULL) and a
    ``UserImage`` (the account cover family). No route archives a ``UserImage``
    today; the branch is here because the pointer relationship is real and the
    function must not silently do half the job the day one is added.

    Returns a list of ``"<what>:<id>"`` labels for the pointers actually
    cleared — empty when the asset was not anybody's current face, which is the
    ordinary case. The caller logs it; nothing branches on it.
    """
    file_path = getattr(image, "file_path", None)
    owner_id = getattr(image, "user_id", None)
    if not file_path or owner_id is None:
        return []

    spellings = urls_naming_file_path(file_path)
    cleared: list[str] = []

    # The owner's own characters. Scoped by ``owner_id`` rather than by the
    # image's ``character_id``: an account-level avatar crop has no character,
    # and a founder may legitimately have pointed a SECOND character at the
    # same stored file.
    characters = (
        db.query(Character).filter(Character.owner_id == owner_id).all()
    )
    for character in characters:
        if _names(character.avatar_url, spellings):
            character.avatar_url = None
            cleared.append(f"character_avatar:{character.id}")
        if _names(character.cover_url, spellings):
            character.cover_url = None
            cleared.append(f"character_cover:{character.id}")

    user = db.query(User).filter(User.id == owner_id).first()
    if user is not None:
        # A built-in sigil is not media and has no lifecycle. Checked first and
        # explicitly, mirroring ``resolve_account_avatar_url``, so the exemption
        # is a stated rule rather than a consequence of a string not matching.
        if not is_account_sigil(user.avatar_url or "") and _names(
            user.avatar_url, spellings
        ):
            user.avatar_url = None
            cleared.append(f"account_avatar:{user.id}")
        if _names(user.cover_url, spellings):
            user.cover_url = None
            cleared.append(f"account_cover:{user.id}")

    return cleared


def _names(pointer: Optional[str], spellings: set[str]) -> bool:
    """True when *pointer* is one of the spellings that name the archived file.

    Exact membership. Not a prefix, a suffix or a basename comparison: two
    different assets routinely share a basename, and "looks like it" is the
    failure mode that clears a pointer to an image the owner never deleted.
    """
    return bool(pointer) and pointer in spellings
