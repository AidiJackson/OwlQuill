"""Scene routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.scene import Scene as SceneModel
from app.models.realm import RealmMembership as RealmMembershipModel
from app.schemas.scene import Scene, SceneCreate, SceneUpdate

router = APIRouter()


@router.post("/realms/{realm_id}/scenes", response_model=Scene, status_code=status.HTTP_201_CREATED)
def create_scene_in_realm(
    realm_id: int,
    scene_data: SceneCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Scene:
    """Create a new scene in a realm."""
    # Check if user is a member of the realm
    membership = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == realm_id,
        RealmMembershipModel.user_id == current_user.id
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of this realm to create scenes"
        )

    db_scene = SceneModel(
        **scene_data.model_dump(),
        realm_id=realm_id,
        created_by=current_user.id
    )
    db.add(db_scene)
    db.commit()
    db.refresh(db_scene)
    return db_scene


@router.get("/realms/{realm_id}/scenes", response_model=List[Scene])
def list_realm_scenes(
    realm_id: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db)
) -> List[Scene]:
    """List scenes in a realm."""
    scenes = db.query(SceneModel).filter(
        SceneModel.realm_id == realm_id
    ).order_by(SceneModel.created_at.desc()).offset(skip).limit(limit).all()
    return scenes


@router.get("/{scene_id}", response_model=Scene)
def get_scene(
    scene_id: int,
    db: Session = Depends(get_db)
) -> Scene:
    """Get a single scene."""
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )
    return scene


@router.patch("/{scene_id}", response_model=Scene)
def update_scene(
    scene_id: int,
    scene_data: SceneUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Scene:
    """Update a scene."""
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    # Check if user is the creator or realm owner/admin
    membership = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == scene.realm_id,
        RealmMembershipModel.user_id == current_user.id
    ).first()

    if not membership or (scene.created_by != current_user.id and membership.role not in ["owner", "admin"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this scene"
        )

    # Update scene fields
    update_data = scene_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(scene, field, value)

    db.commit()
    db.refresh(scene)
    return scene


@router.delete("/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scene(
    scene_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Delete a scene."""
    scene = db.query(SceneModel).filter(SceneModel.id == scene_id).first()
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scene not found"
        )

    # Check if user is the creator or realm owner/admin
    membership = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == scene.realm_id,
        RealmMembershipModel.user_id == current_user.id
    ).first()

    if not membership or (scene.created_by != current_user.id and membership.role not in ["owner", "admin"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this scene"
        )

    db.delete(scene)
    db.commit()
