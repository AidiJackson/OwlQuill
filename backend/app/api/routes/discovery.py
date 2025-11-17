"""Discovery routes for finding users and realms."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User as UserModel
from app.models.realm import Realm as RealmModel
from app.models.connection import UserConnection
from app.schemas.user import User
from app.schemas.realm import Realm

router = APIRouter()


@router.get("/users", response_model=List[User])
def discover_users(
    search: Optional[str] = Query(None, description="Search by username or display name"),
    skip: int = 0,
    limit: int = 20,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[User]:
    """Discover users - search or get suggestions."""
    query = db.query(UserModel).filter(
        UserModel.id != current_user.id  # Exclude current user
    )

    if search:
        # Case-insensitive search by username or display_name
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                func.lower(UserModel.username).like(func.lower(search_pattern)),
                func.lower(UserModel.display_name).like(func.lower(search_pattern))
            )
        )
    else:
        # Get suggested users (users not already connected to)
        # Get IDs of users current user is already following
        following_ids = db.query(UserConnection.following_id).filter(
            UserConnection.follower_id == current_user.id
        ).subquery()

        query = query.filter(
            ~UserModel.id.in_(following_ids)
        ).order_by(UserModel.created_at.desc())

    users = query.offset(skip).limit(limit).all()
    return users


@router.get("/realms", response_model=List[Realm])
def discover_realms(
    search: Optional[str] = Query(None, description="Search by realm name or description"),
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db)
) -> List[Realm]:
    """Discover realms - search or get suggestions."""
    # Only show public realms in discovery
    query = db.query(RealmModel).filter(RealmModel.is_public == True)

    if search:
        # Case-insensitive search by name or description
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                func.lower(RealmModel.name).like(func.lower(search_pattern)),
                func.lower(RealmModel.description).like(func.lower(search_pattern)),
                func.lower(RealmModel.tagline).like(func.lower(search_pattern))
            )
        )

    # Order by newest
    query = query.order_by(RealmModel.created_at.desc())

    realms = query.offset(skip).limit(limit).all()
    return realms
