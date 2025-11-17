"""Discovery and search routes."""
from typing import Optional, Literal, List, Union
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.models.user import User as UserModel
from app.models.character import Character as CharacterModel
from app.models.realm import Realm as RealmModel
from app.schemas.discovery import (
    SearchResponse,
    UserSearchResult,
    CharacterSearchResult,
    RealmSearchResult,
)

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=100, description="Search query"),
    type: Literal["all", "user", "character", "realm"] = Query("all", description="Resource type to search"),
    limit: int = Query(20, ge=1, le=50, description="Maximum results to return"),
    db: Session = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
) -> SearchResponse:
    """
    Search for users, characters, and realms.

    Uses ILIKE for case-insensitive pattern matching.
    """
    results: List[Union[UserSearchResult, CharacterSearchResult, RealmSearchResult]] = []
    search_pattern = f"%{q}%"

    # Search users
    if type in ["all", "user"]:
        users = db.query(UserModel).filter(
            or_(
                UserModel.username.ilike(search_pattern),
                UserModel.display_name.ilike(search_pattern)
            )
        ).limit(limit if type == "user" else limit // 3).all()

        for user in users:
            results.append(UserSearchResult(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                bio=user.bio,
                result_type="user"
            ))

    # Search characters (only public ones unless owned by current user)
    if type in ["all", "character"]:
        char_query = db.query(CharacterModel).options(joinedload(CharacterModel.owner))

        if current_user:
            # Show public characters + own private characters
            char_query = char_query.filter(
                or_(
                    CharacterModel.visibility == "public",
                    CharacterModel.owner_id == current_user.id
                )
            )
        else:
            # Only public characters for non-authenticated users
            char_query = char_query.filter(CharacterModel.visibility == "public")

        char_query = char_query.filter(
            or_(
                CharacterModel.name.ilike(search_pattern),
                CharacterModel.alias.ilike(search_pattern)
            )
        )

        characters = char_query.limit(limit if type == "character" else limit // 3).all()

        for char in characters:
            results.append(CharacterSearchResult(
                id=char.id,
                name=char.name,
                avatar_url=char.avatar_url,
                short_bio=char.short_bio,
                owner_username=char.owner.username if char.owner else None,
                result_type="character"
            ))

    # Search realms
    if type in ["all", "realm"]:
        realm_query = db.query(RealmModel).options(joinedload(RealmModel.owner))

        # Only search public realms for MVP
        realm_query = realm_query.filter(RealmModel.is_public == True)

        realm_query = realm_query.filter(
            or_(
                RealmModel.name.ilike(search_pattern),
                RealmModel.tagline.ilike(search_pattern),
                RealmModel.description.ilike(search_pattern)
            )
        )

        realms = realm_query.limit(limit if type == "realm" else limit // 3).all()

        for realm in realms:
            results.append(RealmSearchResult(
                id=realm.id,
                name=realm.name,
                slug=realm.slug,
                tagline=realm.tagline,
                description=realm.description,
                owner_username=realm.owner.username if realm.owner else None,
                is_public=realm.is_public,
                result_type="realm"
            ))

    return SearchResponse(
        results=results,
        total=len(results)
    )
