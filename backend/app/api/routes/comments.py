"""Comment routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_optional
from app.models.user import User
from app.models.authorship import AUTHOR_KIND_CHARACTER, COMMENT_AUTHOR_KIND_WANDERER
from app.models.character import Character as CharacterModel
from app.models.comment import Comment as CommentModel
from app.models.post import Post as PostModel
from app.schemas.comment import Comment, CommentCreate
from app.services.composition import link_commit
from app.services.provenance import decide_provenance
from app.services.safety import blocked_user_ids
from app.services.visibility import user_can_access_post
from app.services.seeding import serialize_comments_for_viewer

router = APIRouter()

# Wanderers (accounts with no characters) may leave short, identity-less
# comments only.
_WANDERER_COMMENT_MAX_CHARS = 1000


@router.post("/posts/{post_id}/comments", response_model=Comment, status_code=status.HTTP_201_CREATED)
def create_comment(
    post_id: int,
    comment_data: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Comment:
    """Create a comment on a post.

    Character-first identity (Sprint 33): a comment is authored by one of the
    caller's characters. Accounts with no characters (Wanderers) may leave a
    short identity-less comment; accounts WITH characters must comment as one,
    and only as their own (closes the arbitrary-attribution hole).
    """
    # Commenting requires the same access as reading: a private realm's post is
    # 404 to a non-member here too, so knowing its id is not enough to write to it.
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not user_can_access_post(db, current_user.id, post):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    owned_count = db.query(CharacterModel).filter(
        CharacterModel.owner_id == current_user.id
    ).count()

    if comment_data.character_id is not None:
        owned = db.query(CharacterModel).filter(
            CharacterModel.id == comment_data.character_id,
            CharacterModel.owner_id == current_user.id,
        ).first()
        if not owned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only comment as your own character.",
            )
    elif owned_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Select a character to comment as.",
        )
    elif len(comment_data.content) > _WANDERER_COMMENT_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Comments are limited to {_WANDERER_COMMENT_MAX_CHARS} characters.",
        )

    decision = decide_provenance(
        db,
        user_id=current_user.id,
        content=comment_data.content,
        composition_session_id=comment_data.composition_session_id,
    )

    db_comment = CommentModel(
        post_id=post_id,
        author_user_id=current_user.id,
        character_id=comment_data.character_id,
        content=comment_data.content,
        # Recorded durably so a character comment stays character content
        # after its character is deleted — see app.models.authorship. The
        # characterless branch is only reachable for an account with no
        # characters (checked above): the legitimate Wanderer path.
        author_kind=(
            AUTHOR_KIND_CHARACTER
            if comment_data.character_id is not None
            else COMMENT_AUTHOR_KIND_WANDERER
        ),
    )
    db_comment.apply_provenance(decision)
    db.add(db_comment)
    db.flush()
    link_commit(db, decision.session, kind="comment", obj_id=db_comment.id)
    db.commit()
    db.refresh(db_comment)
    return db_comment


@router.get("/posts/{post_id}/comments", response_model=List[Comment])
def list_post_comments(
    post_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> List[Comment]:
    """List comments on a post. Excludes blocked users' comments when authenticated.

    S24F: comments inherit the post's realm visibility. Public-realm comments remain
    readable (including unauthenticated, preserving existing behaviour); a post in a
    PRIVATE realm the caller cannot access returns 404, so its comments are not
    leaked to non-members. A realm-less post is not public, so it is 404 to an
    anonymous caller; a missing post is 404 to everyone.

    Anonymous readers receive the fail-closed projection described on
    :func:`app.services.seeding.serialize_comment_for_viewer` — no account
    identity at all, and a character only when that character is PUBLIC.
    """
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    user_id = current_user.id if current_user is not None else None
    if not user_can_access_post(db, user_id, post):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    comments_q = db.query(CommentModel).filter(CommentModel.post_id == post_id)

    if current_user is not None:
        blocked = blocked_user_ids(db, current_user.id)
        if blocked:
            comments_q = comments_q.filter(CommentModel.author_user_id.notin_(blocked))

    comments = comments_q.options(
        selectinload(CommentModel.author_user),
        selectinload(CommentModel.character),
    ).order_by(CommentModel.created_at.asc()).all()
    return serialize_comments_for_viewer(comments, current_user, db)


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete a comment. Hard delete; nothing references a comment row.

    ``author_user_id`` is the only thing that grants this. It is checked FIRST,
    so an author can always remove what they published — including a comment
    written as a character they have since deleted, or on a post in a realm
    they have since left. Membership of the realm, ownership of the realm, and
    authorship of the post grant nothing.

    Everyone else is answered as the read path would answer them: 404 when
    they cannot see the post (so a private realm's comment ids are not
    confirmable by probing), 403 when they can see it but did not write it.
    """
    comment = db.query(CommentModel).filter(CommentModel.id == comment_id).first()
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    if comment.author_user_id != current_user.id:
        post = db.query(PostModel).filter(PostModel.id == comment.post_id).first()
        if not user_can_access_post(db, current_user.id, post):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this comment",
        )

    db.delete(comment)
    db.commit()
