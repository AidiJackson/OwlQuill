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


def is_founder_account(user: User) -> bool:
    """Is this the founder/seeder tier — Aidan (admin) or Lauren (seeder)?

    THE single predicate for "may this account use founder/seeder-only creator
    tooling". It composes the two existing definitions of account truth and
    invents nothing:

      * :func:`app.core.dependencies.user_is_admin` — ``is_admin`` flag OR
        ``ADMIN_EMAILS``.
      * :func:`app.services.seeding.is_seeder_account` — ``is_admin`` OR
        ``is_seeder`` flag OR ``ADMIN_EMAILS`` OR ``SEEDER_EMAILS``.

    Before this existed, each founder-only surface wrote its own ``_require_admin``
    on top of ``user_is_admin`` alone, so a dedicated seeder (``is_seeder`` with
    no admin rights) was refused everywhere — and separately, image quota exempted
    only ``ADMIN_EMAILS``, so a DB-flagged admin was still rate-limited. Both
    inconsistencies were real: they are why the seeding account could not do the
    work it exists to do. Fix them here, once.

    This is NOT a new authority system and carries no shared secret: it is a
    read over the same account columns every other guard already reads. It also
    does not widen ordinary creator access — ``can_use_creator_tools`` is
    untouched, and a Writer or Wanderer matches none of these terms.
    """
    return user_is_admin(user) or is_seeder_account(user)


def require_founder(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency enforcing founder/seeder access on a route.

    Used by the founder image workflow (upload, manual reference selection,
    founder generation jobs). Hiding the control in the UI is not enforcement —
    this is the authoritative gate and it fails closed for every ordinary
    creator and Wanderer.
    """
    if not is_founder_account(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This is a founder tool. Your account doesn't have access to it.",
        )
    return current_user


def has_writer_unlock(user: User) -> bool:
    """Has this account paid for (or been granted) the Writer Unlock?

    The unlock is the ONLY thing that turns a Wanderer into a Writer. It is a
    stored grant — never inferred from behaviour — so no UI path, redirect or
    empty state can manufacture it. Founder/admin/seeder accounts are handled
    separately by the callers below; they are not "unlocked", they are exempt.
    """
    return getattr(user, "writer_unlocked_at", None) is not None


def can_create_character(db: Session, user: User) -> bool:
    """May this account create a character at all?

    Distinct from :func:`can_use_creator_tools`: that one asks "may you use the
    creator workspaces", which an existing Writer passes by owning a character.
    This asks the *entry* question, and a Wanderer owns no character, so it can
    never be derived from character ownership — it needs the paid unlock.
    """
    if user_is_admin(user) or is_seeder_account(user):
        return True
    return has_writer_unlock(user)


def can_use_creator_tools(db: Session, user: User) -> bool:
    """May this account use the creator workspaces?

    Covers image generation, StoryLab, Editor Studio, RP Stories and
    publishing. Wanderers are a complete, first-class role — a False result
    means "this surface isn't part of your experience", never "you haven't
    finished setting up".

    The character-count term is retained so an existing Writer who predates the
    unlock keeps their workspaces; the unlock is the forward-looking term.
    """
    if user_is_admin(user) or is_seeder_account(user):
        return True
    if has_writer_unlock(user):
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


def require_writer_unlock(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency enforcing the paid Writer Unlock on a route.

    Used by character creation. Hiding the button is not enforcement — this is
    the authoritative gate, and it fails closed for every account that has no
    stored unlock and is not a founder/admin/seeder.
    """
    if not can_create_character(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Creating a character requires the Writer Unlock. "
                "Your account is a Wanderer account."
            ),
        )
    return current_user
