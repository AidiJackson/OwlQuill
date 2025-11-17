"""User routes."""
from typing import List, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User as UserModel
from app.models.connection import Connection as ConnectionModel
from app.schemas.user import User, UserUpdate
from app.schemas.connection import ConnectionUser

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


@router.post("/{user_id}/connect", response_model=Dict[str, str], status_code=status.HTTP_201_CREATED)
def connect_to_user(
    user_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """Connect to (follow) a user."""
    # Can't connect to yourself
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot connect to yourself"
        )

    # Check if target user exists
    target_user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if connection already exists
    existing_connection = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id,
        ConnectionModel.followee_id == user_id
    ).first()

    if existing_connection:
        return {"message": "Already connected"}

    # Create connection
    connection = ConnectionModel(
        follower_id=current_user.id,
        followee_id=user_id
    )
    db.add(connection)
    db.commit()

    return {"message": "Connected successfully"}


@router.delete("/{user_id}/connect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_from_user(
    user_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Disconnect from (unfollow) a user."""
    connection = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id,
        ConnectionModel.followee_id == user_id
    ).first()

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found"
        )

    db.delete(connection)
    db.commit()


@router.get("/me/connections", response_model=List[ConnectionUser])
def get_my_connections(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[ConnectionUser]:
    """Get list of users I'm connected to (following)."""
    connections = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id
    ).all()

    # Get the user details for each connection
    followee_ids = [c.followee_id for c in connections]
    users = db.query(UserModel).filter(UserModel.id.in_(followee_ids)).all()

    return users


@router.get("/{user_id}/connection-status", response_model=Dict[str, bool])
def get_connection_status(
    user_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, bool]:
    """Check if current user is connected to a specific user."""
    connection = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id,
        ConnectionModel.followee_id == user_id
    ).first()

    return {"is_connected": connection is not None}
