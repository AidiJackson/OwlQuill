"""Profile routes for user and character profiles."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_optional
from app.models.user import User as UserModel
from app.models.character import Character as CharacterModel
from app.models.post import Post as PostModel
from app.models.realm import RealmMembership
from app.schemas.profile import UserProfile, CharacterProfile, PostSummary, UserSummary, CharacterSummary, RealmSummary

router = APIRouter()


def _build_post_summaries(posts: list, limit: int = 5) -> list:
    """Helper to build post summary objects."""
    summaries = []
    for post in posts[:limit]:
        # Build realm summary if present
        realm_summary = None
        if post.realm:
            realm_summary = RealmSummary(
                id=post.realm.id,
                name=post.realm.name,
                slug=post.realm.slug,
                tagline=post.realm.tagline
            )

        # Build character summary if present
        character_summary = None
        if post.character:
            character_summary = CharacterSummary(
                id=post.character.id,
                name=post.character.name,
                avatar_url=post.character.avatar_url
            )

        # Build author summary
        author_summary = UserSummary(
            id=post.author_user.id,
            username=post.author_user.username,
            display_name=post.author_user.display_name,
            avatar_url=post.author_user.avatar_url
        )

        summaries.append(PostSummary(
            id=post.id,
            title=post.title,
            content=post.content[:200] + "..." if len(post.content) > 200 else post.content,
            content_type=post.content_type.value,
            created_at=post.created_at,
            realm=realm_summary,
            character=character_summary,
            author_user=author_summary
        ))
    return summaries


@router.get("/users/{username}", response_model=UserProfile)
def get_user_profile(
    username: str,
    db: Session = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
) -> UserProfile:
    """Get public user profile by username."""
    user = db.query(UserModel).filter(UserModel.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Count stats
    total_posts = db.query(func.count(PostModel.id)).filter(PostModel.author_user_id == user.id).scalar() or 0
    joined_realms_count = db.query(func.count(RealmMembership.id)).filter(RealmMembership.user_id == user.id).scalar() or 0

    # For MVP, follower/following counts are 0 (connection system not yet implemented)
    follower_count = 0
    following_count = 0

    # Get recent posts
    recent_posts = db.query(PostModel).options(
        joinedload(PostModel.realm),
        joinedload(PostModel.character),
        joinedload(PostModel.author_user)
    ).filter(PostModel.author_user_id == user.id).order_by(PostModel.created_at.desc()).limit(5).all()

    post_summaries = _build_post_summaries(recent_posts)

    return UserProfile(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=user.avatar_url,
        created_at=user.created_at,
        follower_count=follower_count,
        following_count=following_count,
        total_posts=total_posts,
        joined_realms_count=joined_realms_count,
        recent_posts=post_summaries
    )


@router.get("/me", response_model=UserProfile)
def get_current_user_profile(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserProfile:
    """Get current user's own profile."""
    return get_user_profile(current_user.username, db, current_user)


@router.get("/characters/{character_id}", response_model=CharacterProfile)
def get_character_profile(
    character_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
) -> CharacterProfile:
    """Get public character profile by ID."""
    character = db.query(CharacterModel).options(
        joinedload(CharacterModel.owner)
    ).filter(CharacterModel.id == character_id).first()

    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # Check visibility
    if character.visibility.value == "private" and (not current_user or character.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="This character is private")

    # Count stats
    posts_count = db.query(func.count(PostModel.id)).filter(PostModel.character_id == character.id).scalar() or 0

    # Count unique realms this character has posted in
    realms_count = db.query(func.count(func.distinct(PostModel.realm_id))).filter(
        PostModel.character_id == character.id,
        PostModel.realm_id.isnot(None)
    ).scalar() or 0

    # Get recent posts by this character
    recent_posts = db.query(PostModel).options(
        joinedload(PostModel.realm),
        joinedload(PostModel.character),
        joinedload(PostModel.author_user)
    ).filter(PostModel.character_id == character.id).order_by(PostModel.created_at.desc()).limit(5).all()

    post_summaries = _build_post_summaries(recent_posts)

    # Build owner summary
    owner_summary = UserSummary(
        id=character.owner.id,
        username=character.owner.username,
        display_name=character.owner.display_name,
        avatar_url=character.owner.avatar_url
    )

    return CharacterProfile(
        id=character.id,
        name=character.name,
        alias=character.alias,
        age=character.age,
        species=character.species,
        role=character.role,
        era=character.era,
        short_bio=character.short_bio,
        long_bio=character.long_bio,
        avatar_url=character.avatar_url,
        portrait_url=character.portrait_url,
        tags=character.tags,
        visibility=character.visibility.value,
        created_at=character.created_at,
        owner=owner_summary,
        posts_count=posts_count,
        realms_count=realms_count,
        recent_posts=post_summaries
    )
