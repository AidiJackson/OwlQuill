"""Character name and alias policy — the one authoritative check (closed beta).

Both write paths, ``POST /characters/`` and ``PATCH /characters/{id}``, call
these helpers; nothing else writes ``Character.name`` or ``Character.alias``.
The client trims and length-checks as an affordance only.

WHY IT LIVES HERE AND NOT ON THE SCHEMA. Two reasons, both deliberate:

* ``CharacterBase`` is also the parent of the READ schema. A validator there
  would make every legacy row that predates this policy (an untrimmed name, a
  reserved word) fail serialization on read — a 500 on a character nobody was
  editing. Write-time policy must not become read-time breakage.
* The frontend's generic ``apiClient.request`` surfaces ``detail`` as the error
  message. Pydantic's 422 ``detail`` is a list of objects, which renders as
  "[object Object]"; a route-raised 422 carries one readable sentence that
  Edit Details shows verbatim.

WHAT THIS IS NOT. A fiction platform must allow villains and dark or strange
names. There is deliberately no
profanity, sexual-term, public-figure, brand or homoglyph filter here. The rules
below are about *integrity* — invisible or deceptive characters, markup and
links where a name belongs, and impersonation of the platform itself.

THE DUPLICATE RULE IS TEMPORARY. @mentions still resolve by name
(``services/mentions.py``), so two characters sharing a name make a mention
ambiguous. Until stable character handles replace name-based resolution,
case-insensitive duplicates are refused. Remove :func:`find_name_conflict`'s
callers when handles land.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.character import Character

#: Maximum length of a name or alias, counted AFTER normalisation.
NAME_MAX_LENGTH = 100
ALIAS_MAX_LENGTH = 100

#: Whole-name matches only, case-insensitive. Not a word list: "Admiral Staffe"
#: and "The System Breaker" are fine. These are names a reader could take as
#: the platform speaking.
RESERVED_NAMES = frozenset(
    {"ficshon", "admin", "moderator", "staff", "support", "system", "official"}
)

#: Bidirectional embedding/override (U+202A–U+202E) and isolate (U+2066–U+2069)
#: controls: they reorder how a name displays, so what a reader sees is not
#: what was stored.
_BIDI_CONTROLS = frozenset(chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A)))

#: Invisible characters that let two names look identical while differing.
#: U+200D (ZERO WIDTH JOINER) is intentionally ABSENT: it is what joins emoji
#: sequences (👩‍🚀), and refusing it would refuse ordinary emoji.
_ZERO_WIDTH = frozenset({"​", "‌", "⁠", "﻿"})

_WHITESPACE_RUN = re.compile(r"\s+")


class CharacterNameError(ValueError):
    """A name or alias the policy refuses. ``str(exc)`` is user-facing copy."""


def _normalise(value: str) -> str:
    """NFC, then every run of whitespace (including tabs and newlines) → one
    space, then trim. Whitespace is folded BEFORE the control check so a pasted
    tab or line break is tidied rather than refused."""
    value = unicodedata.normalize("NFC", value)
    return _WHITESPACE_RUN.sub(" ", value).strip()


def _check_common(value: str, label: str, max_length: int) -> None:
    """The rules shared by name and alias. ``value`` is already normalised."""
    if len(value) > max_length:
        raise CharacterNameError(f"{label} must be at most {max_length} characters.")
    for ch in value:
        if ch in _BIDI_CONTROLS or ch in _ZERO_WIDTH:
            raise CharacterNameError(f"{label} contains an invisible or text-direction character.")
        if unicodedata.category(ch) == "Cc":
            raise CharacterNameError(f"{label} contains a control character.")
    if "<" in value or ">" in value:
        raise CharacterNameError(f"{label} cannot contain < or >.")
    lowered = value.lower()
    if "://" in lowered or "www." in lowered:
        raise CharacterNameError(f"{label} cannot be a link.")
    if not any(unicodedata.category(ch)[0] in ("L", "N") for ch in value):
        raise CharacterNameError(f"{label} needs at least one letter or number.")
    if value.casefold() in RESERVED_NAMES:
        raise CharacterNameError(f'"{value}" is reserved. Please choose another {label.lower()}.')


def normalize_character_name(value: Optional[str]) -> str:
    """Return the stored form of a character name, or raise.

    ``None`` is refused here rather than at the database: ``name`` is NOT NULL,
    and an explicit ``"name": null`` in a PATCH used to reach the commit and
    surface as a 500.
    """
    if value is None:
        raise CharacterNameError("Name cannot be empty.")
    if not isinstance(value, str):  # pragma: no cover - the schema types it
        raise CharacterNameError("Name must be text.")
    name = _normalise(value)
    if not name:
        raise CharacterNameError("Name cannot be empty.")
    _check_common(name, "Name", NAME_MAX_LENGTH)
    return name


def normalize_character_alias(value: Optional[str]) -> Optional[str]:
    """Return the stored form of an alias, or raise.

    Alias stays optional: ``None`` clears it, and a value that normalises to
    nothing (``""``, ``"   "``) clears it too rather than storing an empty or
    whitespace-only string. Aliases are not required to be unique.
    """
    if value is None:
        return None
    alias = _normalise(value)
    if not alias:
        return None
    _check_common(alias, "Alias", ALIAS_MAX_LENGTH)
    return alias


def find_name_conflict(
    db: Session, name: str, *, exclude_character_id: Optional[int] = None
) -> Optional[int]:
    """Id of another character whose name equals ``name`` case-insensitively.

    TEMPORARY closed-beta rule — see the module docstring. ``exclude_character_id``
    is the character being renamed, so changing only the capitalisation of one's
    own name is not a conflict with oneself.

    Compared with SQL ``lower()`` on both sides — the SAME comparison
    ``services/mentions.py`` uses to resolve a mention, which is the ambiguity
    this rule exists to prevent. On SQLite ``lower()`` folds ASCII only; on
    PostgreSQL (DEV/LIVE) it is locale-aware. All characters count, private
    ones included: a private character can become public again.
    """
    q = db.query(Character.id).filter(func.lower(Character.name) == name.lower())
    if exclude_character_id is not None:
        q = q.filter(Character.id != exclude_character_id)
    row = q.order_by(Character.id).first()
    return row[0] if row else None


DUPLICATE_NAME_MESSAGE = (
    "Another character already has this name. During the closed beta, "
    "character names must be unique — please choose another."
)
