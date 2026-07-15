"""Reaction routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_optional
from app.models.user import User
from app.models.reaction import Reaction as ReactionModel
from app.models.post import Post as PostModel
from app.schemas.reaction import Reaction, ReactionCreate
from app.services.visibility import user_can_access_post

router = APIRouter()


@router.get("/posts/{post_id}/reactions", response_model=list[Reaction])
def get_post_reactions(
    post_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> list[ReactionModel]:
    """Return all reactions for a post.

    S24F: reactions inherit the post's realm visibility. Public-realm reactions
    remain readable (including unauthenticated, matching the comments convention); a
    post in a PRIVATE realm the caller cannot access returns 404, so its reactions
    are not leaked to non-members.
    """
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if post is not None:
        user_id = current_user.id if current_user is not None else None
        if not user_can_access_post(db, user_id, post):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    return db.query(ReactionModel).filter(ReactionModel.post_id == post_id).all()


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
