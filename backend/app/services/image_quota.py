"""Image generation weekly allowance service (B22) and identity-pack rate limit.

Rolling 7-day window per user (weekly quota):
- ``check_weekly_quota(user, db)``  → 429 JSONResponse or None
- ``get_quota_status(user, db)``    → dict with used/limit/remaining/unlimited/reset_at

Per-character 24-hour identity-pack rate limit:
- ``check_identity_pack_quota(character_id, user, db)``         → 429 JSONResponse or None
- ``get_identity_pack_quota_status(character_id, user, db)``    → dict with used/limit/remaining
"""
from datetime import datetime, timedelta

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.character_image import CharacterImage
from app.models.user import User

_WINDOW_DAYS = 7
_IDENTITY_PACK_WINDOW_HOURS = 24


def _is_quota_exempt(user: User) -> bool:
    """True when this account is exempt from image allowances.

    Named for what it decides. It was ``_is_admin``, which stopped being
    accurate the moment the exemption covered seeders as well as admins.

    Delegates to the single founder/seeder predicate. It previously read
    ``ADMIN_EMAILS`` alone, which made the exemption disagree with every other
    admin check in the codebase: an account carrying ``is_admin=True`` in the DB
    but absent from the env list was rate-limited as an ordinary creator, and the
    dedicated seeding account — whose entire purpose is bulk character seeding —
    was capped at ``IMAGE_WEEKLY_LIMIT`` images a week.

    The exemption is deliberately NOT widened past founder/seeder: ordinary
    creators and Wanderers keep the weekly allowance exactly as before.
    """
    from app.core.entitlements import is_founder_account  # lazy: avoids a cycle

    return is_founder_account(user)


def get_quota_status(user: User, db: Session) -> dict:
    """Return quota info dict for the user.

    Admin users receive unlimited=True with no usage tracked.
    Regular users get used/limit/remaining for the rolling 7-day window,
    plus reset_in_seconds and reset_at showing when the oldest image in the
    window expires (i.e. when the first slot reopens).
    """
    if _is_quota_exempt(user):
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

    # Counts by owning account (``CharacterImage.user_id``, Phase 4B1). See
    # check_weekly_quota's docstring for why this stays owner-keyed for now.
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


def _count_identity_pack_generations(character_id: int, db: Session) -> int:
    """Count identity pack generation attempts for a character in the last 24 hours.

    Counts CharacterImage records that have ``pack_role == "anchor_front"`` in
    their metadata_json.  One such record is created per generation attempt
    (the front anchor is always the first image written).  The count is stable
    through accept — accept updates kind/is_temp but preserves pack_role in
    metadata, so accepted packs are still counted toward the limit.
    """
    now = datetime.utcnow()
    since = now - timedelta(hours=_IDENTITY_PACK_WINDOW_HOURS)

    images = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.created_at >= since,
        )
        .all()
    )

    return sum(
        1 for img in images
        if isinstance(img.metadata_json, dict)
        and img.metadata_json.get("pack_role") == "anchor_front"
    )


def get_identity_pack_quota_status(character_id: int, user: User, db: Session) -> dict:
    """Return identity-pack rate-limit status for a character.

    Admins are unlimited.  Regular users get used/limit/remaining for the
    rolling 24-hour window scoped to this character.
    """
    if _is_quota_exempt(user):
        return {
            "used": 0,
            "limit": None,
            "remaining": None,
            "unlimited": True,
            "window_hours": _IDENTITY_PACK_WINDOW_HOURS,
        }

    used = _count_identity_pack_generations(character_id, db)
    limit = settings.IDENTITY_PACK_DAILY_LIMIT
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "unlimited": False,
        "window_hours": _IDENTITY_PACK_WINDOW_HOURS,
    }


def check_identity_pack_quota(character_id: int, user: User, db: Session) -> JSONResponse | None:
    """Return a 429 JSONResponse if this character has hit its per-day identity-pack limit.

    Returns None when generation may proceed (within limit or admin bypass).
    Only counts generate attempts that actually run the generation pipeline —
    dry-run calls and accept/lock operations are not counted.
    """
    if _is_quota_exempt(user):
        return None

    status = get_identity_pack_quota_status(character_id, user, db)
    if status["remaining"] == 0:
        return JSONResponse(
            status_code=429,
            content={
                "error": "identity_pack_rate_limited",
                "detail": (
                    f"You have used all {status['limit']} identity pack generations "
                    f"for this character today. The limit resets after "
                    f"{_IDENTITY_PACK_WINDOW_HOURS} hours."
                ),
                "limit": status["limit"],
                "used": status["used"],
                "remaining": 0,
                "window_hours": _IDENTITY_PACK_WINDOW_HOURS,
            },
        )
    return None


def check_weekly_quota(user: User, db: Session) -> JSONResponse | None:
    """Return a 429 JSONResponse if the user has hit their weekly image limit.

    Returns None if generation may proceed (within limit or admin bypass).
    Deduction happens only on successful generation — caller's responsibility
    to stamp user_id on the saved CharacterImage record.

    ``user_id`` is the asset's OWNING ACCOUNT (Phase 4B1), not "the generator".
    Counting it is legacy accounting that predates that meaning and is left
    unchanged here deliberately: the two coincide on every path except admin
    generation onto another account's character, which stamps the character's
    owner. The requester already has a proper home in
    ``image_generation_jobs.user_id``; moving quota onto it is a separate
    increment, not a side effect of renaming what ownership means.
    """
    if _is_quota_exempt(user):
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
