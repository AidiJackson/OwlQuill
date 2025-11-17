"""Scene routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.scene import Scene as SceneModel, ScenePost as ScenePostModel, SceneVisibilityEnum
from app.schemas.scene import Scene, SceneCreate, SceneUpdate, ScenePost, ScenePostCreate

router = APIRouter()


@router.post("/", response_model=Scene, status_code=status.HTTP_201_CREATED)
def create_scene(
    scene_data: SceneCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Scene:
    """Create a new scene."""
    db_scene = SceneModel(
        **scene_data.model_dump(),
        created_by_user_id=current_user.id
    )
    db.add(db_scene)
    db.commit()
    db.refresh(db_scene)
    return db_scene


@router.get("/", response_model=List[Scene])
def list_scenes(
    created_by_me: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[Scene]:
    """
    List scenes.

    - If created_by_me=True, return only scenes created by current user
    - Otherwise, return all public scenes
    """
    query = db.query(SceneModel)

    if created_by_me:
        query = query.filter(SceneModel.created_by_user_id == current_user.id)
    else:
        # Only show public scenes in general listing
        query = query.filter(SceneModel.visibility == SceneVisibilityEnum.PUBLIC)

    scenes = query.order_by(SceneModel.created_at.desc()).all()
    return scenes


@router.get("/{scene_id}", response_model=Scene)
def get_scene(
    scene_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Scene:
    """Get a specific scene by ID."""
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()

    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    # Check access permissions
    if scene.visibility == SceneVisibilityEnum.PRIVATE:
        if scene.created_by_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this private scene"
            )

    return scene


@router.get("/{scene_id}/posts", response_model=List[ScenePost])
def list_scene_posts(
    scene_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[ScenePost]:
    """List all posts in a scene, ordered by creation time."""
    # First verify scene exists and user has access
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()

    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    # Check access permissions
    if scene.visibility == SceneVisibilityEnum.PRIVATE:
        if scene.created_by_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this private scene"
            )

    posts = db.query(ScenePostModel).filter(
        ScenePostModel.scene_id == scene_id
    ).order_by(ScenePostModel.created_at.asc()).all()

    return posts


@router.post("/{scene_id}/posts", response_model=ScenePost, status_code=status.HTTP_201_CREATED)
def create_scene_post(
    scene_id: int,
    post_data: ScenePostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ScenePost:
    """Create a new post in a scene."""
    # Verify scene exists
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()

    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    # For now, allow any authenticated user to post in public/unlisted scenes
    # Check access for private scenes
    if scene.visibility == SceneVisibilityEnum.PRIVATE:
        if scene.created_by_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to post in this private scene"
            )

    # Create the post
    db_post = ScenePostModel(
        **post_data.model_dump(),
        scene_id=scene_id,
        author_user_id=current_user.id
    )
    db.add(db_post)
    db.commit()
    db.refresh(db_post)

    return db_post
