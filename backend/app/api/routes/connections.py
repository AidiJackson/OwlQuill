"""User connection (follow) routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.connection import UserConnection as ConnectionModel
from app.schemas.connection import Connection, ConnectionCreate
from app.services.notification_service import create_connection_notification

router = APIRouter()


@router.post("/", response_model=Connection, status_code=status.HTTP_201_CREATED)
def create_connection(
    connection_data: ConnectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Connection:
    """Follow a user (create a connection)."""
    # Check if trying to follow self
    if connection_data.following_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot follow yourself"
        )

    # Check if connection already exists
    existing_connection = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id,
        ConnectionModel.following_id == connection_data.following_id
    ).first()

    if existing_connection:
        return existing_connection

    # Check if target user exists
    target_user = db.query(User).filter(User.id == connection_data.following_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Create the connection
    db_connection = ConnectionModel(
        follower_id=current_user.id,
        following_id=connection_data.following_id
    )
    db.add(db_connection)
    db.flush()

    # Create notification for the user being followed
    create_connection_notification(
        db=db,
        following_id=connection_data.following_id,
        follower_id=current_user.id
    )

    db.commit()
    db.refresh(db_connection)
    return db_connection


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Unfollow a user (delete a connection)."""
    connection = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id,
        ConnectionModel.following_id == user_id
    ).first()

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found"
        )

    db.delete(connection)
    db.commit()


@router.get("/following", response_model=List[Connection])
def list_following(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Connection]:
    """List users that the current user is following."""
    connections = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id
    ).all()

    return connections


@router.get("/followers", response_model=List[Connection])
def list_followers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Connection]:
    """List users that follow the current user."""
    connections = db.query(ConnectionModel).filter(
        ConnectionModel.following_id == current_user.id
    ).all()

    return connections


@router.get("/status/{user_id}")
def get_connection_status(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """Check if current user is following a specific user."""
    connection = db.query(ConnectionModel).filter(
        ConnectionModel.follower_id == current_user.id,
        ConnectionModel.following_id == user_id
    ).first()

    return {"is_following": connection is not None}
