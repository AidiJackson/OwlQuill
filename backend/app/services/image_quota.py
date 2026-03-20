"""Image generation weekly allowance service (B22).

Rolling 7-day window per user. Admin users are unlimited.

Public API:
- ``check_weekly_quota(user, db)``  → 429 JSONResponse or None
- ``get_quota_status(user, db)``    → dict with used/limit/remaining/unlimited
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
    Regular users get used/limit/remaining for the rolling 7-day window.
    """
    if _is_admin(user):
        return {
            "used": 0,
            "limit": None,
            "remaining": None,
            "unlimited": True,
            "reset_in_seconds": None,
        }

    since = datetime.utcnow() - timedelta(days=_WINDOW_DAYS)
    used = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.user_id == user.id,
            CharacterImage.created_at >= since,
        )
        .count()
    )
    limit = settings.IMAGE_WEEKLY_LIMIT
    remaining = max(0, limit - used)
    reset_in = int(timedelta(days=_WINDOW_DAYS).total_seconds())
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "unlimited": False,
        "reset_in_seconds": reset_in,
    }


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
        return JSONResponse(
            status_code=429,
            content={
                "error": "quota_exceeded",
                "detail": (
                    "You've used all your images for this week. "
                    "Your allowance resets in 7 days."
                ),
                "limit": quota["limit"],
                "reset_in_seconds": quota["reset_in_seconds"],
            },
        )
    return None
