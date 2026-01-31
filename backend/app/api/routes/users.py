"""User routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User as UserModel
from app.schemas.user import User, UserUpdate, PublicUserProfile

router = APIRouter()


@router.get("/me", response_model=User)
def get_current_user_info(current_user: UserModel = Depends(get_current_user)) -> User:
    """Get current user information."""
    return current_user


@router.patch("/me", response_model=User)
def update_current_user(
    user_update: UserUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """Update current user information."""
    if user_update.display_name is not None:
        current_user.display_name = user_update.display_name
    if user_update.bio is not None:
        current_user.bio = user_update.bio
    if user_update.avatar_url is not None:
        current_user.avatar_url = user_update.avatar_url

    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/{username}", response_model=PublicUserProfile)
def get_user_profile(
    username: str,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PublicUserProfile:
    """Get a public-facing user profile by username (no email)."""
    user = db.query(UserModel).filter(UserModel.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
