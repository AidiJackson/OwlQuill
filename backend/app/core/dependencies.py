"""FastAPI dependencies for authentication and database."""
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

security = HTTPBearer()


def user_is_admin(user: User) -> bool:
    """Single definition of "is this user an admin".

    Admins are either flagged in the DB or listed in ADMIN_EMAILS — the same
    expression previously repeated inline across the admin, canon, body-identity
    and StoryLab routes.
    """
    return bool(user.is_admin) or user.email.lower() in settings.get_admin_emails()


def get_owned_character(
    character_id: int,
    user: User,
    db: Session,
    *,
    allow_admin: bool = False,
    not_owner_detail: str = "You don't have permission to modify this character.",
):
    """Fetch a character (404 if missing) and enforce ownership (403 otherwise).

    Replaces the per-route ``_get_owned_character`` copies. ``allow_admin`` and
    ``not_owner_detail`` preserve each route's original semantics — style shops
    admit admins, the canon API uses a different 403 message.
    """
    from app.models.character import Character as CharacterModel

    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != user.id and not (allow_admin and getattr(user, "is_admin", False)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=not_owner_detail)
    return character


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token."""
    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[int] = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "banned",
                "detail": user.ban_reason or "Your account has been suspended.",
            },
        )

    return user


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get current user if authenticated, otherwise None."""
    if credentials is None:
        return None

    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None
