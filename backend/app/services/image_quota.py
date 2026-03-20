"""Image generation weekly allowance service (B22).

Rolling 7-day window per user. Admin users are unlimited.

Public API:
- ``check_weekly_quota(user, db)``  → 429 JSONResponse or None
- ``get_quota_status(user, db)``    → dict with used/limit/remaining/unlimited/reset_at
"""
from datetime import datetime, timedelta

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.character_image import CharacterImage
from app.models.user import User

_WINDOW_DAYS = 7


def _is_admin(user: User) -> bool:
    return user.email.lower() in settings.get_admin_emails()


def get_quota_status(user: User, db: Session) -> dict:
    """Return quota info dict for the user.

    Admin users receive unlimited=True with no usage tracked.
    Regular users get used/limit/remaining for the rolling 7-day window,
    plus reset_in_seconds and reset_at showing when the oldest image in the
    window expires (i.e. when the first slot reopens).
    """
    if _is_admin(user):
        return {
            "used": 0,
            "limit": None,
            "remaining": None,
            "unlimited": True,
            "reset_in_seconds": None,
            "reset_at": None,
        }

    now = datetime.utcnow()
    since = now - timedelta(days=_WINDOW_DAYS)

    # Single query ordered oldest-first: lets us count and find the reset anchor.
    images_in_window: list[CharacterImage] = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.user_id == user.id,
            CharacterImage.created_at >= since,
        )
        .order_by(CharacterImage.created_at.asc())
        .all()
    )

    used = len(images_in_window)
    limit = settings.IMAGE_WEEKLY_LIMIT
    remaining = max(0, limit - used)

    # Reset time = when the oldest image in the window falls out.
    # That is the earliest point at which remaining increases by at least 1.
    reset_in_seconds: int | None = None
    reset_at: str | None = None
    if images_in_window:
        oldest_created = images_in_window[0].created_at
        expires_at = oldest_created + timedelta(days=_WINDOW_DAYS)
        reset_in_seconds = max(0, int((expires_at - now).total_seconds()))
        reset_at = expires_at.isoformat() + "Z"

    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "unlimited": False,
        "reset_in_seconds": reset_in_seconds,
        "reset_at": reset_at,
    }


def _format_reset_duration(reset_in_seconds: int | None) -> str:
    """Return a short human-readable string for the 429 error message."""
    if not reset_in_seconds:
        return "weekly"
    hours = int(reset_in_seconds / 3600)
    if hours < 1:
        return "very soon"
    if hours < 24:
        return f"in about {hours} hour{'s' if hours != 1 else ''}"
    days = max(1, round(hours / 24))
    return f"in about {days} day{'s' if days != 1 else ''}"


def check_weekly_quota(user: User, db: Session) -> JSONResponse | None:
    """Return a 429 JSONResponse if the user has hit their weekly image limit.

    Returns None if generation may proceed (within limit or admin bypass).
    Deduction happens only on successful generation — caller's responsibility
    to stamp user_id on the saved CharacterImage record.
    """
    if _is_admin(user):
        return None

    quota = get_quota_status(user, db)
    if quota["remaining"] == 0:
        reset_str = _format_reset_duration(quota["reset_in_seconds"])
        return JSONResponse(
            status_code=429,
            content={
                "error": "quota_exceeded",
                "detail": (
                    f"Your weekly image allowance is used up. "
                    f"It resets {reset_str}."
                ),
                "limit": quota["limit"],
                "reset_in_seconds": quota["reset_in_seconds"],
                "reset_at": quota["reset_at"],
            },
        )
    return None
