"""User routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.admin_seed import auto_join_commons
from app.models.user import User as UserModel
from app.models.post import Post as PostModel
from app.models.scene import Scene as SceneModel, SceneVisibilityEnum
from app.models.realm import Realm as RealmModel, RealmMembership as RealmMembershipModel
from app.schemas.post import Post
from app.schemas.scene import SceneOut
from app.schemas.user import User, UserUpdate, PublicUserProfile

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


@router.get("/{username}", response_model=PublicUserProfile)
def get_user_profile(
    username: str,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PublicUserProfile:
    """Get a public-facing user profile by username (no email)."""
    user = db.query(UserModel).filter(UserModel.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{username}/timeline")
def get_user_timeline(
    username: str,
    limit: int = 20,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a user's profile timeline (posts + scenes), access-safe."""
    # Ensure viewer is in The Commons (idempotent)
    auto_join_commons(current_user.id, db)

    # Resolve target user
    target = db.query(UserModel).filter(UserModel.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Viewer realm memberships
    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.user_id == current_user.id
    ).all()
    viewer_realm_ids = {m.realm_id for m in memberships}
    if not viewer_realm_ids:
        return []

    items = []

    # Posts authored by target user (only in realms viewer can see)
    posts = (
        db.query(PostModel, RealmModel.name)
        .join(RealmModel, PostModel.realm_id == RealmModel.id)
        .filter(
            PostModel.author_user_id == target.id,
            PostModel.realm_id.in_(viewer_realm_ids),
        )
        .order_by(PostModel.created_at.desc())
        .limit(limit)
        .all()
    )
    for post, realm_name in posts:
        items.append({
            "type": "post",
            "created_at": post.created_at,
            "realm_id": post.realm_id,
            "realm_name": realm_name,
            "payload": Post.model_validate(post).model_dump(),
        })

    # Scenes created by target user (only in realms viewer can see)
    scenes = (
        db.query(SceneModel, RealmModel.name)
        .join(RealmModel, SceneModel.realm_id == RealmModel.id)
        .filter(
            SceneModel.created_by_user_id == target.id,
            SceneModel.realm_id.in_(viewer_realm_ids),
        )
        .order_by(SceneModel.created_at.desc())
        .limit(limit)
        .all()
    )
    for scene, realm_name in scenes:
        if scene.visibility == SceneVisibilityEnum.PRIVATE and scene.created_by_user_id != current_user.id:
            continue
        items.append({
            "type": "scene",
            "created_at": scene.created_at,
            "realm_id": scene.realm_id,
            "realm_name": realm_name,
            "payload": SceneOut.model_validate(scene).model_dump(),
        })

    # Merge + sort
    items.sort(key=lambda i: i["created_at"], reverse=True)
    return items[:limit]
