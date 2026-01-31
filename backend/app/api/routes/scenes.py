"""Scene routes."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.scene import Scene as SceneModel, SceneVisibilityEnum
from app.models.scene_post import ScenePost as ScenePostModel
from app.models.realm import RealmMembership as RealmMembershipModel
from app.schemas.scene import SceneCreate, SceneOut
from app.schemas.scene_post import ScenePostCreate, ScenePostOut

router = APIRouter()


def _require_realm_membership(db: Session, user_id: int, realm_id: int) -> None:
    """Raise 403 if user is not a member of the realm."""
    membership = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == realm_id,
        RealmMembershipModel.user_id == user_id,
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of this realm",
        )


def _check_scene_access(scene: SceneModel, user_id: int) -> None:
    """Raise 403 if user cannot access a scene based on visibility."""
    if scene.visibility == SceneVisibilityEnum.PRIVATE:
        if scene.created_by_user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This scene is private",
            )


def _scene_to_out(scene: SceneModel, post_count: int) -> SceneOut:
    """Convert a Scene model to SceneOut, injecting post_count."""
    return SceneOut(
        id=scene.id,
        realm_id=scene.realm_id,
        title=scene.title,
        description=scene.description,
        visibility=scene.visibility,
        created_by_user_id=scene.created_by_user_id,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
        post_count=post_count,
    )


@router.post("/", response_model=SceneOut, status_code=status.HTTP_201_CREATED)
def create_scene(
    data: SceneCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SceneOut:
    """Create a new scene in a realm."""
    _require_realm_membership(db, current_user.id, data.realm_id)

    scene = SceneModel(
        realm_id=data.realm_id,
        title=data.title,
        description=data.description,
        visibility=data.visibility,
        created_by_user_id=current_user.id,
    )
    db.add(scene)
    db.commit()
    db.refresh(scene)
    return _scene_to_out(scene, 0)


@router.get("/", response_model=List[SceneOut])
def list_scenes(
    realm_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[SceneOut]:
    """List scenes for a realm. Requires realm membership."""
    _require_realm_membership(db, current_user.id, realm_id)

    # Subquery for post counts
    post_counts = (
        db.query(ScenePostModel.scene_id, func.count(ScenePostModel.id).label("cnt"))
        .group_by(ScenePostModel.scene_id)
        .subquery()
    )

    scenes_with_counts = (
        db.query(SceneModel, func.coalesce(post_counts.c.cnt, 0))
        .outerjoin(post_counts, SceneModel.id == post_counts.c.scene_id)
        .filter(SceneModel.realm_id == realm_id)
        .order_by(SceneModel.updated_at.desc())
        .all()
    )

    results = []
    for scene, count in scenes_with_counts:
        if scene.visibility == SceneVisibilityEnum.PRIVATE and scene.created_by_user_id != current_user.id:
            continue
        results.append(_scene_to_out(scene, count))
    return results


@router.get("/{scene_id}", response_model=SceneOut)
def get_scene(
    scene_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SceneOut:
    """Get a single scene."""
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene not found")

    if scene.realm_id:
        _require_realm_membership(db, current_user.id, scene.realm_id)
    _check_scene_access(scene, current_user.id)

    count = db.query(func.count(ScenePostModel.id)).filter(ScenePostModel.scene_id == scene.id).scalar() or 0
    return _scene_to_out(scene, count)


@router.get("/{scene_id}/posts", response_model=List[ScenePostOut])
def list_scene_posts(
    scene_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ScenePostOut]:
    """List all posts (turns) in a scene, ordered chronologically."""
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene not found")

    if scene.realm_id:
        _require_realm_membership(db, current_user.id, scene.realm_id)
    _check_scene_access(scene, current_user.id)

    posts = (
        db.query(ScenePostModel)
        .options(selectinload(ScenePostModel.author), selectinload(ScenePostModel.character))
        .filter(ScenePostModel.scene_id == scene_id)
        .order_by(ScenePostModel.created_at.asc(), ScenePostModel.id.asc())
        .all()
    )

    return [
        ScenePostOut(
            id=p.id,
            scene_id=p.scene_id,
            author_user_id=p.author_user_id,
            author_username=p.author.username if p.author else None,
            character_id=p.character_id,
            character_name=p.character.name if p.character else None,
            content=p.content,
            reply_to_id=p.reply_to_id,
            created_at=p.created_at,
        )
        for p in posts
    ]


@router.post("/{scene_id}/posts", response_model=ScenePostOut, status_code=status.HTTP_201_CREATED)
def create_scene_post(
    scene_id: int,
    data: ScenePostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScenePostOut:
    """Add a post (turn) to a scene."""
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scene not found")

    if scene.realm_id:
        _require_realm_membership(db, current_user.id, scene.realm_id)
    _check_scene_access(scene, current_user.id)

    post = ScenePostModel(
        scene_id=scene_id,
        author_user_id=current_user.id,
        character_id=data.character_id,
        content=data.content,
        reply_to_id=data.reply_to_id,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    # Eager load for response
    db.refresh(post, attribute_names=["author", "character"])

    return ScenePostOut(
        id=post.id,
        scene_id=post.scene_id,
        author_user_id=post.author_user_id,
        author_username=post.author.username if post.author else None,
        character_id=post.character_id,
        character_name=post.character.name if post.character else None,
        content=post.content,
        reply_to_id=post.reply_to_id,
        created_at=post.created_at,
    )
