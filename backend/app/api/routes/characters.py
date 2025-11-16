"""Character routes."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.character import Character as CharacterModel
from app.schemas.character import Character, CharacterCreate, CharacterUpdate

router = APIRouter()


@router.post("/", response_model=Character, status_code=status.HTTP_201_CREATED)
def create_character(
    character_data: CharacterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Character:
    """Create a new character."""
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
    """Delete a character."""
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
    db.commit()
