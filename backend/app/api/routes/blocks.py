"""Block routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.block import UserBlock as UserBlockModel
from app.schemas.block import Block, BlockCreate

router = APIRouter()


@router.post("/", response_model=Block, status_code=status.HTTP_201_CREATED)
def create_block(
    block_data: BlockCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Block:
    """Block a user."""
    # Can't block yourself
    if block_data.blocked_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot block yourself"
        )

    # Check if target user exists
    target_user = db.query(User).filter(User.id == block_data.blocked_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if already blocked
    existing_block = db.query(UserBlockModel).filter(
        UserBlockModel.blocker_id == current_user.id,
        UserBlockModel.blocked_id == block_data.blocked_id
    ).first()

    if existing_block:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already blocked"
        )

    # Create block
    db_block = UserBlockModel(
        blocker_id=current_user.id,
        blocked_id=block_data.blocked_id
    )
    db.add(db_block)
    db.commit()
    db.refresh(db_block)
    return db_block


@router.get("/", response_model=List[Block])
def list_blocks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Block]:
    """List all users blocked by the current user."""
    blocks = db.query(UserBlockModel).filter(
        UserBlockModel.blocker_id == current_user.id
    ).order_by(UserBlockModel.created_at.desc()).all()
    return blocks


@router.delete("/{blocked_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(
    blocked_user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Unblock a user."""
    block = db.query(UserBlockModel).filter(
        UserBlockModel.blocker_id == current_user.id,
        UserBlockModel.blocked_id == blocked_user_id
    ).first()

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Block not found"
        )

    db.delete(block)
    db.commit()
