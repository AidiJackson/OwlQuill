"""Entitlements — the single source of truth for "what may this account do".

These conditions are deliberately NOT written inline at call sites. Ficshon's
creator entitlement is currently derived from character ownership, but the
Writer unlock will replace that rule. When it lands, it is changed here and
nowhere else — every caller keeps working unmodified.

The frontend mirror lives in ``frontend/src/lib/entitlements.ts``; the two must
agree, because a hidden navigation link is not an access control.
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, user_is_admin
from app.models.character import Character
from app.models.user import User
from app.services.seeding import is_seeder_account


def can_use_creator_tools(db: Session, user: User) -> bool:
    """May this account use the creator workspaces?

    Covers image generation, StoryLab, Editor Studio, RP Stories and
    publishing. Wanderers are a complete, first-class role — a False result
    means "this surface isn't part of your experience", never "you haven't
    finished setting up".

    NOTE: the character-count term is an implementation detail of the current
    rule. Replace it with the Writer entitlement here when that ships; callers
    stay unchanged.
    """
    if user_is_admin(user) or is_seeder_account(user):
        return True
    return db.query(Character).filter(Character.owner_id == user.id).count() > 0


def has_acting_character(db: Session, user: User) -> bool:
    """Does this account have a character it can *act as*?

    Distinct from :func:`can_use_creator_tools`, and deliberately so. Messaging,
    posting and realm-joining are character-to-character: they need an actual
    character behind them, so admin and seeder flags are irrelevant. A founder
    with zero characters genuinely cannot send a character-to-character message.

    Do not merge this with :func:`can_use_creator_tools` — doing so would grant
    actions that have no character to perform them.
    """
    return db.query(Character).filter(Character.owner_id == user.id).count() > 0


def require_creator(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency enforcing creator-tool access on a route.

    Returns the user so routes can use this in place of ``get_current_user``
    rather than depending on both.
    """
    if not can_use_creator_tools(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This is a creator workspace. Your account doesn't have access to it.",
        )
    return current_user
