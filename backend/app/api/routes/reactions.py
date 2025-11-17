"""Reaction routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.reaction import Reaction as ReactionModel
from app.models.post import Post as PostModel
from app.schemas.reaction import Reaction, ReactionCreate
from app.services.notification_service import create_reaction_notification

router = APIRouter()


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
    db.flush()

    # Create notification for post author
    create_reaction_notification(
        db=db,
        post_author_id=post.author_user_id,
        reactor_id=current_user.id,
        post_id=post_id
    )

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
