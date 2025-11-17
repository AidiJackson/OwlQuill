"""Reaction routes."""
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.reaction import Reaction as ReactionModel
from app.models.post import Post as PostModel
from app.schemas.reaction import Reaction, ReactionCreate

router = APIRouter()


@router.post("/posts/{post_id}/react", response_model=Dict[str, any])
def toggle_reaction(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, any]:
    """Toggle a 'like' reaction on a post."""
    # Check if post exists
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    # Check if user already reacted
    existing_reaction = db.query(ReactionModel).filter(
        ReactionModel.post_id == post_id,
        ReactionModel.user_id == current_user.id
    ).first()

    if existing_reaction:
        # Remove reaction (unlike)
        db.delete(existing_reaction)
        db.commit()
        action = "removed"
    else:
        # Add reaction (like)
        db_reaction = ReactionModel(
            post_id=post_id,
            user_id=current_user.id,
            type="like"
        )
        db.add(db_reaction)
        db.commit()
        action = "added"

    # Get updated count
    reaction_count = db.query(func.count(ReactionModel.id)).filter(
        ReactionModel.post_id == post_id
    ).scalar()

    return {
        "action": action,
        "count": reaction_count,
        "user_reacted": action == "added"
    }


@router.get("/posts/{post_id}/reactions", response_model=Dict[str, any])
def get_post_reactions(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, any]:
    """Get reaction count and status for a post."""
    # Check if post exists
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    # Get total count
    reaction_count = db.query(func.count(ReactionModel.id)).filter(
        ReactionModel.post_id == post_id
    ).scalar()

    # Check if current user has reacted
    user_reaction = db.query(ReactionModel).filter(
        ReactionModel.post_id == post_id,
        ReactionModel.user_id == current_user.id
    ).first()

    return {
        "count": reaction_count,
        "user_reacted": user_reaction is not None
    }


@router.post("/posts/{post_id}/reactions", response_model=Reaction, status_code=status.HTTP_201_CREATED)
def create_reaction(
    post_id: int,
    reaction_data: ReactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Reaction:
    """Add a reaction to a post."""
    # Check if post exists
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    # Check if user already reacted with this type
    existing_reaction = db.query(ReactionModel).filter(
        ReactionModel.post_id == post_id,
        ReactionModel.user_id == current_user.id,
        ReactionModel.type == reaction_data.type
    ).first()

    if existing_reaction:
        return existing_reaction

    db_reaction = ReactionModel(
        **reaction_data.model_dump(),
        post_id=post_id,
        user_id=current_user.id
    )
    db.add(db_reaction)
    db.commit()
    db.refresh(db_reaction)
    return db_reaction


@router.delete("/{reaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reaction(
    reaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Remove a reaction."""
    reaction = db.query(ReactionModel).filter(ReactionModel.id == reaction_id).first()
    if not reaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reaction not found"
        )
    if reaction.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this reaction"
        )

    db.delete(reaction)
    db.commit()
