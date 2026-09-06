"""Which stored assets ACTIVE canon is currently pointing at (Phase 4D3-2).

WHY THIS EXISTS
---------------
Phase 4D3-3 gives the identity-canon writers owned ``CharacterImage`` rows. The
moment those rows exist, the two generic image-management routes —
``DELETE /characters/{id}/images/{image_id}`` and
``DELETE /users/me/character-images/{image_id}`` — can reach them, and neither
knows anything about canon. A founder tidying their library could archive the
very image their character's face canon is built from.

WHAT ARCHIVING ACTUALLY DOES TODAY, AND WHY THAT IS NOT REASSURING
------------------------------------------------------------------
Canon generation reads URLs out of canon JSON and calls ``load_image_bytes`` on
them; it never looks at a row, so ``status`` is invisible to it. Archiving a
canon-referenced image therefore breaks nothing *right now* — it silently
desynchronises the asset's lifecycle from the reference that uses it: the owner
is told the image is gone, and canon keeps generating from its bytes. Phase 4E
makes canon resolution row-aware, at which point the same action starts breaking
canon for real. The guard belongs here, before the rows exist, not after the
first support ticket.

WHY NOT JUST PROTECT THE KINDS
------------------------------
``PROTECTED_IMAGE_KINDS`` protects the four ``ANCHOR_*`` kinds, and that is the
right mechanism THERE because anchors are consumed by kind+status queries — the
identity lock counts four ACTIVE anchors, ``canon_bridge`` looks one up by kind.
Canon slots are consumed by URL. Extending a kind list to cover them would
protect nothing that is actually read by kind, and would make every SUPERSEDED
canon card permanently undeletable — a library that only grows. Reference-based
protection releases an asset the moment canon stops pointing at it, which is the
behaviour a founder expects and the one a kind list cannot express.

WHERE CANON KEEPS ITS URLS
--------------------------
Five JSON documents across two tables, enumerated in :data:`_CANON_SOURCES`.
They are read as opaque JSON and walked for strings rather than parsed through
their Pydantic schemas: a schema that gains a URL field would silently escape a
field-by-field reader, and this guard failing open is exactly the failure it is
here to prevent. Walking every string costs one row read per character.

NOT A SESSION HOOK, ON PURPOSE
------------------------------
This is called BY the two generic routes. It must not become a mapper or
session-level guard, because 4D3-3's canon-aware replacement archives the
superseded row and rewrites the canon reference in the SAME transaction — and a
hook would refuse the legitimate half of that operation. Canon-aware code is
allowed to do what generic code is not; that distinction is the whole design.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services.character_home_media import candidate_file_paths

logger = logging.getLogger(__name__)

#: (model, attribute) pairs holding canon JSON, from the 4D3 inspection.
#:
#: ``CharacterIdentityCanon`` carries the v2 canon (face slots, body slots,
#: permanent-mark references and detail crops, accessory design/fit anchors);
#: ``Character`` carries the identity anchor snapshot and the legacy body
#: markings with their generated anchors. All five are live reference stores —
#: the scene router and the pack builders read every one of them.
#: Each entry is (model, column identifying the character, JSON columns).
_CANON_SOURCES = (
    (
        CharacterIdentityCanon,
        CharacterIdentityCanon.character_id,
        ("face_canon_json", "body_canon_json", "accessories_json"),
    ),
    (
        Character,
        Character.id,
        ("identity_anchor_json", "body_canon_json"),
    ),
)


def _walk_strings(node: Any) -> Iterable[str]:
    """Every string anywhere in a decoded JSON document.

    Deliberately indiscriminate. Selecting only ``*_url``-ish keys would mean
    this guard's coverage depended on a naming convention that canon has already
    broken once (``detail_crop_url`` beside ``final_character_card_image_url``),
    and a missed key here is an unguarded delete.
    """
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_strings(value)
    elif isinstance(node, str):
        yield node


def _decode(raw: Any) -> Any:
    """Decode a canon column, which may be TEXT holding JSON or already-parsed.

    Returns ``None`` for anything unreadable. A canon document this cannot parse
    contributes no protected paths — stated here rather than left implicit,
    because it is the one place this guard fails OPEN, and it does so only for a
    document that no reader could have resolved a URL from either.
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    return None


def canon_referenced_file_paths(db: Session, character_id: Optional[int]) -> set[str]:
    """Every stored ``file_path`` spelling ACTIVE canon references for a character.

    Returns the union of :func:`~app.services.character_home_media.candidate_file_paths`
    over every URL found in that character's canon documents — i.e. already in
    the form a ``CharacterImage.file_path`` can be compared against directly.

    Sharing ``candidate_file_paths`` with the public resolver and with
    ``asset_persistence.source_image_for_url`` is not tidiness: canon stores
    whatever ``save_image`` returned, which may be ``static/generated/x.png``,
    ``/static/generated/x.png`` or a full R2 URL for the same file. A second
    normalisation would eventually disagree with the first, and the one that
    disagreed leniently would be the unguarded delete.

    A characterless asset (Phase 4C) has no canon to consult: ``character_id``
    of ``None`` returns an empty set, and deleting the character CASCADEs its
    canon away, so nothing can be protected by a reference that no longer exists.
    """
    if not character_id:
        return set()

    paths: set[str] = set()
    for model, key_column, columns in _CANON_SOURCES:
        row = db.query(model).filter(key_column == character_id).first()
        if row is None:
            continue
        for column in columns:
            document = _decode(getattr(row, column, None))
            if document is None:
                continue
            for value in _walk_strings(document):
                if not value:
                    continue
                paths |= candidate_file_paths(value)
    return paths


def is_canon_referenced(db: Session, image) -> bool:
    """True when ACTIVE canon currently points at *image*'s stored file.

    Scoped to the image's OWN character, which is where its canon lives. A
    rowless canon URL — one naming bytes no row was ever created for, of which
    DEV holds 100 — protects nothing, because it matches no ``file_path``; that
    is the correct outcome and not an oversight. Historical references are left
    exactly as they are.
    """
    file_path = getattr(image, "file_path", None)
    if not file_path:
        return False
    return file_path in canon_referenced_file_paths(
        db, getattr(image, "character_id", None)
    )


#: Refusal text for a generic archive of a live canon asset. Names the way out,
#: because "no" without a route is how a founder ends up with an image they can
#: neither use nor remove.
CANON_REFERENCED_MESSAGE = (
    "This image is part of this character's identity canon and cannot be "
    "removed here. Replace or clear the canon slot that uses it first."
)
