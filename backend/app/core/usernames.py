"""Public username rules — the single source of truth.

Three separate identity concepts exist on Ficshon, and only the second one
lives here:

1. ``User.id``      — internal, immutable, never public, never user-editable.
2. ``User.username`` — the *Wanderer username*: the public identity of an
   account with no character. Editable, unique, validated here.
3. The character — the public identity of a Writer account, which replaces the
   account username publicly.

Registration and the change endpoint both call :func:`validate_username` so a
name that could never be registered can't be reached by renaming either.
"""
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 24

# Safe character set: ASCII letters, digits, underscore, dot and hyphen, with
# the separators confined to the interior. Deliberately narrow — usernames are
# rendered on public surfaces and used in @mentions, so no Unicode look-alikes,
# no whitespace, no leading/trailing punctuation, no doubled separators.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*$")

# Names reserved for the system, for routes, or because they impersonate staff.
# Compared case-insensitively against the normalized name.
RESERVED_USERNAMES = frozenset(
    {
        "admin", "administrator", "root", "system", "sysadmin", "superuser",
        "moderator", "mod", "staff", "support", "help", "ficshon", "official",
        "founder", "owner", "team", "security", "abuse", "billing", "payments",
        "api", "www", "mail", "email", "null", "none", "undefined", "anonymous",
        "me", "you", "user", "users", "account", "accounts", "settings",
        "profile", "profiles", "login", "logout", "signin", "signup",
        "register", "auth", "password", "wanderer", "wanderers",
        "writer", "writers", "character", "characters", "commons", "realm",
        "realms", "storylab", "studio", "editor", "images", "notifications",
        "messages", "search", "explore", "about", "terms", "privacy", "legal",
        "everyone", "here", "all",
    }
)

# How long an account must wait between public username changes. Short enough
# to fix a typo the same week, long enough that a name can't be churned to
# evade recognition after a bad interaction.
USERNAME_CHANGE_COOLDOWN = timedelta(days=14)


class UsernameError(ValueError):
    """A username failed validation. ``str(exc)`` is user-facing."""


def normalize_username(raw: Optional[str]) -> str:
    """Trim surrounding whitespace. Casing is preserved for display; collision
    checks are case-insensitive (see :func:`username_is_taken`)."""
    return (raw or "").strip()


def validate_username(raw: Optional[str]) -> str:
    """Return the normalized username, or raise :class:`UsernameError`.

    Pure — no database access, so it is usable from schema validators, scripts
    and both call sites (registration and the change endpoint).
    """
    name = normalize_username(raw)

    if not name:
        raise UsernameError("Please enter a username.")
    if len(name) < USERNAME_MIN_LENGTH:
        raise UsernameError(
            f"Usernames must be at least {USERNAME_MIN_LENGTH} characters."
        )
    if len(name) > USERNAME_MAX_LENGTH:
        raise UsernameError(
            f"Usernames must be at most {USERNAME_MAX_LENGTH} characters."
        )
    if not _USERNAME_RE.match(name):
        raise UsernameError(
            "Usernames may use letters, numbers, and single . _ - between them "
            "(no spaces or other symbols)."
        )
    if name.lower() in RESERVED_USERNAMES:
        raise UsernameError("That username is reserved. Please choose another.")

    return name


def username_is_taken(db: Session, username: str, *, exclude_user_id: Optional[int] = None) -> bool:
    """Case-insensitive uniqueness check.

    ``exclude_user_id`` lets an account "rename" to a different casing of the
    name it already holds without colliding with itself.
    """
    from app.models.user import User

    query = db.query(User.id).filter(func.lower(User.username) == username.lower())
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return db.query(query.exists()).scalar()


def username_change_available_at(user) -> Optional[datetime]:
    """When this account may next change its username, or None if it may now."""
    last = getattr(user, "username_changed_at", None)
    if last is None:
        return None
    available = last + USERNAME_CHANGE_COOLDOWN
    return available if available > datetime.utcnow() else None
