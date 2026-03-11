"""Character routes."""
import logging
from datetime import datetime, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.character import Character as CharacterModel, VisibilityEnum
from app.schemas.character import Character, CharacterCreate, CharacterUpdate, CharacterSearchResult

router = APIRouter()
logger = logging.getLogger(__name__)

_COOLDOWN_HOURS = 24
_BETA_CHARACTER_LIMIT = 1


def _is_admin(user: User) -> bool:
    """Check if user is an admin (bypasses beta restrictions).

    Checks the is_admin DB flag first, then falls back to the ADMIN_EMAILS
    config list so email-configured admins also get the bypass.
    """
    return bool(user.is_admin) or user.email.lower() in settings.get_admin_emails()


@router.post("/", response_model=Character, status_code=status.HTTP_201_CREATED)
def create_character(
    character_data: CharacterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Character:
    """Create a new character."""
    is_admin = _is_admin(current_user)

    # Enforce cooldown after character deletion (admins bypass)
    if current_user.next_character_allowed_at and not is_admin:
        now = datetime.utcnow()
        if now < current_user.next_character_allowed_at:
            remaining = current_user.next_character_allowed_at - now
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Character creation is on cooldown. "
                    f"You can create a new character in {hours}h {minutes}m "
                    f"(after {current_user.next_character_allowed_at.isoformat()}Z)."
                ),
            )

    # Enforce beta 1-character limit (admins bypass)
    if not is_admin:
        existing_count = db.query(CharacterModel).filter(
            CharacterModel.owner_id == current_user.id
        ).count()
        if existing_count >= _BETA_CHARACTER_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Beta limit: only {_BETA_CHARACTER_LIMIT} character per account. "
                    "Delete your existing character first."
                ),
            )
    else:
        logger.info(
            "[admin-bypass] user=%s bypassing beta character limit (create)",
            current_user.email,
        )

    db_character = CharacterModel(
        **character_data.model_dump(),
        owner_id=current_user.id
    )
    db.add(db_character)
    db.commit()
    db.refresh(db_character)
    return db_character


@router.get("/", response_model=List[Character])
def list_my_characters(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Character]:
    """List current user's characters."""
    characters = db.query(CharacterModel).filter(
        CharacterModel.owner_id == current_user.id
    ).all()
    return characters


@router.get("/search", response_model=List[CharacterSearchResult])
def search_characters(
    q: str = Query("", min_length=0, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CharacterSearchResult]:
    """Search characters by name or tags.

    Returns public characters and the current user's own characters.
    """
    if len(q.strip()) < 2:
        return []

    pattern = f"%{q.strip()}%"
    results = (
        db.query(CharacterModel)
        .filter(
            or_(
                CharacterModel.visibility == VisibilityEnum.PUBLIC,
                CharacterModel.owner_id == current_user.id,
            ),
            or_(
                CharacterModel.name.ilike(pattern),
                CharacterModel.tags.ilike(pattern),
            ),
        )
        .order_by(CharacterModel.name)
        .limit(20)
        .all()
    )
    return results


@router.get("/{character_id}", response_model=Character)
def get_character(
    character_id: int,
    db: Session = Depends(get_db)
) -> Character:
    """Get a character by ID."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )
    character.owner_username = character.owner.username if character.owner else None
    return character


@router.patch("/{character_id}", response_model=Character)
def update_character(
    character_id: int,
    character_update: CharacterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Character:
    """Update a character."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this character"
        )

    for field, value in character_update.model_dump(exclude_unset=True).items():
        setattr(character, field, value)

    db.commit()
    db.refresh(character)
    return character


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Delete a character and enforce a 24-hour creation cooldown."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this character"
        )

    db.delete(character)

    # Set 24h cooldown on the user (admins bypass)
    if not _is_admin(current_user):
        current_user.next_character_allowed_at = datetime.utcnow() + timedelta(hours=_COOLDOWN_HOURS)
    else:
        logger.info(
            "[admin-bypass] user=%s bypassing delete cooldown (character_id=%s)",
            current_user.email,
            character_id,
        )

    db.commit()
