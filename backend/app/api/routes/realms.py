"""Realm routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.realm import Realm as RealmModel, RealmMembership as RealmMembershipModel
from app.schemas.realm import Realm, RealmCreate, RealmMembership

router = APIRouter()


@router.post("/", response_model=Realm, status_code=status.HTTP_201_CREATED)
def create_realm(
    realm_data: RealmCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Realm:
    """Create a new realm."""
    # Check if slug is unique
    existing_realm = db.query(RealmModel).filter(RealmModel.slug == realm_data.slug).first()
    if existing_realm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug already taken"
        )

    db_realm = RealmModel(
        **realm_data.model_dump(),
        owner_id=current_user.id
    )
    db.add(db_realm)
    db.commit()
    db.refresh(db_realm)

    # Add owner as member with owner role
    membership = RealmMembershipModel(
        realm_id=db_realm.id,
        user_id=current_user.id,
        role="owner"
    )
    db.add(membership)
    db.commit()

    return db_realm


@router.get("/", response_model=List[Realm])
def list_realms(
    search: Optional[str] = Query(None),
    public_only: bool = Query(True),
    db: Session = Depends(get_db)
) -> List[Realm]:
    """List realms with optional search."""
    query = db.query(RealmModel)

    if public_only:
        query = query.filter(RealmModel.is_public == True)

    if search:
        query = query.filter(RealmModel.name.ilike(f"%{search}%"))

    realms = query.all()
    return realms


@router.get("/{realm_id}", response_model=Realm)
def get_realm(
    realm_id: int,
    db: Session = Depends(get_db)
) -> Realm:
    """Get a realm by ID."""
    realm = db.query(RealmModel).filter(RealmModel.id == realm_id).first()
    if not realm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realm not found"
        )
    return realm


@router.post("/{realm_id}/join", response_model=RealmMembership, status_code=status.HTTP_201_CREATED)
def join_realm(
    realm_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> RealmMembership:
    """Join a realm."""
    realm = db.query(RealmModel).filter(RealmModel.id == realm_id).first()
    if not realm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realm not found"
        )

    if not realm.is_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This realm is private"
        )

    # Check if already a member
    existing_membership = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == realm_id,
        RealmMembershipModel.user_id == current_user.id
    ).first()

    if existing_membership:
        return existing_membership

    membership = RealmMembershipModel(
        realm_id=realm_id,
        user_id=current_user.id,
        role="member"
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


@router.get("/{realm_id}/members", response_model=List[RealmMembership])
def list_realm_members(
    realm_id: int,
    db: Session = Depends(get_db)
) -> List[RealmMembership]:
    """List members of a realm."""
    realm = db.query(RealmModel).filter(RealmModel.id == realm_id).first()
    if not realm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realm not found"
        )

    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == realm_id
    ).all()
    return memberships
