"""Realm routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.image_ingress import guard_supplied_image_fields
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.realm import Realm as RealmModel, RealmMembership as RealmMembershipModel
from app.schemas.realm import Realm, RealmCreate, RealmMembership

router = APIRouter()


#: ``RealmCreate`` fields that are user-supplied imagery.
#:
#: ``RealmUpdate`` also declares ``banner_url`` and is DEAD SCHEMA — no PATCH
#: route is registered for realms anywhere in the app. It is left in place
#: rather than deleted because removing it is a change to a contract nobody is
#: currently using either way, and this increment adds no realm-editing feature.
#: If a realm PATCH is ever added it MUST guard this same tuple; the test
#: ``test_realm_update_schema_is_not_routed`` fails the moment it is wired up,
#: so the guard cannot be forgotten silently.
REALM_IMAGE_FIELDS = ("banner_url",)


@router.post("/", response_model=Realm, status_code=status.HTTP_201_CREATED)
def create_realm(
    realm_data: RealmCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Realm:
    """Create a new realm.

    ``banner_url`` is founder/seeder-only (Beta Boundary 2). It was the only
    ordinary-user field in the product that both accepted an arbitrary external
    image URL and was rendered straight into an ``<img>`` on three shared
    surfaces — the realms grid, the realm header and the Home side panel — to
    every signed-in account. Realms have no asset model and building one is not
    this increment's job, so the product boundary is the instrument: founders
    keep the field, ordinary users create realms without a banner.

    Everything else about realm creation is untouched, including the fact that
    any authenticated account may create one.
    """
    guard_supplied_image_fields(current_user, realm_data, REALM_IMAGE_FIELDS)

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Realm]:
    """List realms with optional search.

    S24F: requires authentication. ``public_only`` (default) returns only public
    realms. With ``public_only=false`` the result is still restricted to realms the
    caller may see — public realms plus the caller's own/member private realms — so
    private realms can no longer be enumerated via ``public_only=false``.
    """
    query = db.query(RealmModel)

    if public_only:
        query = query.filter(RealmModel.is_public == True)
    else:
        member_realm_ids = db.query(RealmMembershipModel.realm_id).filter(
            RealmMembershipModel.user_id == current_user.id
        )
        query = query.filter(
            or_(
                RealmModel.is_public == True,
                RealmModel.owner_id == current_user.id,
                RealmModel.id.in_(member_realm_ids),
            )
        )

    if search:
        query = query.filter(RealmModel.name.ilike(f"%{search}%"))

    realms = query.all()
    return realms


@router.get("/{realm_id}", response_model=Realm)
def get_realm(
    realm_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Realm:
    """Get a realm by ID.

    S24E FIX B: requires authentication and enforces the same visibility rule as
    the realm list endpoint (which filters is_public==True). A realm is returned
    only when it is public or the caller is a member/owner; a private realm the
    caller is not in returns 404 (indistinguishable from non-existent).
    """
    realm = db.query(RealmModel).filter(RealmModel.id == realm_id).first()
    if not realm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realm not found"
        )
    if not realm.is_public and realm.owner_id != current_user.id:
        is_member = db.query(RealmMembershipModel).filter(
            RealmMembershipModel.realm_id == realm_id,
            RealmMembershipModel.user_id == current_user.id,
        ).first() is not None
        if not is_member:
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[RealmMembership]:
    """List members of a realm.

    S24G: MEMBERSHIP-REQUIRED for every realm, public or private — only the
    realm's owner or a member may view the roster. A private realm the caller
    is not in still returns 404 (hides existence); a public realm the caller
    has not joined returns 403.
    """
    realm = db.query(RealmModel).filter(RealmModel.id == realm_id).first()
    if not realm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Realm not found"
        )
    is_owner_or_member = realm.owner_id == current_user.id or db.query(
        RealmMembershipModel
    ).filter(
        RealmMembershipModel.realm_id == realm_id,
        RealmMembershipModel.user_id == current_user.id,
    ).first() is not None
    if not is_owner_or_member:
        if not realm.is_public:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Realm not found"
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Join this realm to view its member list"
        )

    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.realm_id == realm_id
    ).all()
    return memberships
