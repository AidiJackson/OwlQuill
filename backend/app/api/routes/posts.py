"""Post routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.post import Post as PostModel
from app.models.realm import RealmMembership as RealmMembershipModel
from app.models.block import UserBlock
from app.schemas.post import Post, PostCreate

router = APIRouter()


@router.get("/feed", response_model=List[Post])
def get_feed(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Post]:
    """Get feed of posts from realms the user is a member of."""
    # Get all realm IDs where user is a member
    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.user_id == current_user.id
    ).all()

    realm_ids = [m.realm_id for m in memberships]

    if not realm_ids:
        # User is not a member of any realms, return empty list
        return []

    # Get blocked user IDs
    blocked_users = db.query(UserBlock.blocked_id).filter(
        UserBlock.blocker_id == current_user.id
    ).all()
    blocked_user_ids = [b[0] for b in blocked_users]

    # Get posts from those realms, excluding blocked users
    query = db.query(PostModel).filter(
        PostModel.realm_id.in_(realm_ids)
    )

    if blocked_user_ids:
        query = query.filter(PostModel.author_user_id.notin_(blocked_user_ids))

    posts = query.order_by(PostModel.created_at.desc()).offset(skip).limit(limit).all()

    return posts


@router.post("/realms/{realm_id}/posts", response_model=Post, status_code=status.HTTP_201_CREATED)
def create_post_in_realm(
    realm_id: int,
    post_data: PostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Post:
    """Create a post in a realm."""
    # Check if user is a member of the realm
    membership = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == realm_id,
        RealmMembershipModel.user_id == current_user.id
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of this realm to post"
        )

    db_post = PostModel(
        **post_data.model_dump(),
        realm_id=realm_id,
        author_user_id=current_user.id
    )
    db.add(db_post)
    db.commit()
    db.refresh(db_post)
    return db_post


@router.get("/realms/{realm_id}/posts", response_model=List[Post])
def list_realm_posts(
    realm_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[Post]:
    """List posts in a realm."""
    # Get blocked user IDs
    blocked_users = db.query(UserBlock.blocked_id).filter(
        UserBlock.blocker_id == current_user.id
    ).all()
    blocked_user_ids = [b[0] for b in blocked_users]

    # Query posts, excluding blocked users
    query = db.query(PostModel).filter(
        PostModel.realm_id == realm_id
    )

    if blocked_user_ids:
        query = query.filter(PostModel.author_user_id.notin_(blocked_user_ids))

    posts = query.order_by(PostModel.created_at.desc()).offset(skip).limit(limit).all()
    return posts


@router.get("/{post_id}", response_model=Post)
def get_post(
    post_id: int,
    db: Session = Depends(get_db)
) -> Post:
    """Get a single post."""
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Delete a post."""
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    if post.author_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this post"
        )

    db.delete(post)
    db.commit()
