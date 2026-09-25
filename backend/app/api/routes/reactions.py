"""Reaction routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_optional
from app.models.user import User
from app.models.reaction import Reaction as ReactionModel
from app.models.post import Post as PostModel
from app.schemas.reaction import REACTION_TYPES, Reaction, ReactionCreate
from app.services.visibility import user_can_access_post

router = APIRouter()


def project_reaction(reaction: ReactionModel, viewer: Optional[User]) -> Reaction:
    """The viewer-aware projection of one reaction.

    ``user_id`` survives only when it is the viewer's own; everyone else's is
    withheld, and an anonymous viewer owns nothing.
    """
    own = viewer is not None and reaction.user_id == viewer.id
    return Reaction(
        id=reaction.id,
        post_id=reaction.post_id,
        type=reaction.type,
        user_id=reaction.user_id if own else None,
        created_at=reaction.created_at,
    )


def _accessible_post_or_404(db: Session, post_id: int, viewer: Optional[User]) -> PostModel:
    """The post, when this caller may read it; otherwise 404.

    A missing post and an inaccessible one answer identically, and the same
    gate guards writes: knowing a post id is not access to the post.
    """
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not user_can_access_post(db, viewer.id if viewer is not None else None, post):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post


@router.get("/posts/{post_id}/reactions", response_model=list[Reaction])
def get_post_reactions(
    post_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> list[Reaction]:
    """Return all reactions for a post.

    S24F: reactions inherit the post's realm visibility. Public-realm reactions
    remain readable (including unauthenticated, matching the comments convention); a
    post in a PRIVATE realm the caller cannot access returns 404, so its reactions
    are not leaked to non-members. A realm-less post is not public, so it is 404
    to an anonymous caller.

    Each reaction is projected for the viewer (:func:`project_reaction`): the
    reacting account's id is returned only on the viewer's own reactions. A row
    whose type is outside the allowlist is dropped, never served.
    """
    _accessible_post_or_404(db, post_id, current_user)

    rows = (
        db.query(ReactionModel)
        .filter(
            ReactionModel.post_id == post_id,
            ReactionModel.type.in_(REACTION_TYPES),
        )
        .order_by(ReactionModel.id.asc())
        .all()
    )
    return [project_reaction(r, current_user) for r in rows]


@router.post("/posts/{post_id}/reactions", response_model=Reaction, status_code=status.HTTP_201_CREATED)
def create_reaction(
    post_id: int,
    reaction_data: ReactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Reaction:
    """Add a reaction to a post.

    Only a caller who may read the post may react to it — a private realm's
    post is 404 to a non-member here exactly as it is on read.
    """
    _accessible_post_or_404(db, post_id, current_user)

    # Check if user already reacted with this type
    existing_reaction = db.query(ReactionModel).filter(
        ReactionModel.post_id == post_id,
        ReactionModel.user_id == current_user.id,
        ReactionModel.type == reaction_data.type
    ).first()

    if existing_reaction:
        return project_reaction(existing_reaction, current_user)

    db_reaction = ReactionModel(
        type=reaction_data.type,
        post_id=post_id,
        user_id=current_user.id
    )
    db.add(db_reaction)
    db.commit()
    db.refresh(db_reaction)
    return project_reaction(db_reaction, current_user)


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
