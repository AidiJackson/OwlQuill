"""Body canon endpoints — persistent anatomical markings (tattoos, scars, burns, birthmarks)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.character import Character as CharacterModel
from app.models.user import User
from app.schemas.body_canon import BodyCanonRead, BodyMarkingCreate, BodyMarkingRead
from app.services.body_canon import add_marking, load_markings, remove_marking, to_read_list

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_owned_character(
    character_id: int,
    current_user: User,
    db: Session,
) -> CharacterModel:
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )
    return character


@router.get(
    "/{character_id}/body-markings",
    response_model=BodyCanonRead,
    summary="List all body canon markings for a character",
)
def list_body_markings(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodyCanonRead:
    character = _get_owned_character(character_id, current_user, db)
    markings = load_markings(character)
    return to_read_list(character_id, markings)


@router.post(
    "/{character_id}/body-markings",
    response_model=BodyCanonRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a body marking to a character's canon",
)
def add_body_marking(
    character_id: int,
    body: BodyMarkingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodyCanonRead:
    character = _get_owned_character(character_id, current_user, db)
    add_marking(character, body)
    db.commit()
    db.refresh(character)
    markings = load_markings(character)
    return to_read_list(character_id, markings)


@router.delete(
    "/{character_id}/body-markings/{marking_id}",
    response_model=BodyCanonRead,
    summary="Remove a body marking from a character's canon",
)
def delete_body_marking(
    character_id: int,
    marking_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodyCanonRead:
    character = _get_owned_character(character_id, current_user, db)
    found = remove_marking(character, marking_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marking '{marking_id}' not found on this character.",
        )
    db.commit()
    db.refresh(character)
    markings = load_markings(character)
    return to_read_list(character_id, markings)
