"""Comment routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.comment import Comment as CommentModel
from app.models.post import Post as PostModel
from app.schemas.comment import Comment, CommentCreate

router = APIRouter()


@router.post("/posts/{post_id}/comments", response_model=Comment, status_code=status.HTTP_201_CREATED)
def create_comment(
    post_id: int,
    comment_data: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Comment:
    """Create a comment on a post."""
    # Check if post exists
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    db_comment = CommentModel(
        **comment_data.model_dump(),
        post_id=post_id,
        author_user_id=current_user.id
    )
    db.add(db_comment)
    db.commit()
    db.refresh(db_comment)
    return db_comment


@router.get("/posts/{post_id}/comments", response_model=List[Comment])
def list_post_comments(
    post_id: int,
    db: Session = Depends(get_db)
) -> List[Comment]:
    """List comments on a post."""
    comments = db.query(CommentModel).filter(
        CommentModel.post_id == post_id
    ).order_by(CommentModel.created_at.asc()).all()
    return comments
