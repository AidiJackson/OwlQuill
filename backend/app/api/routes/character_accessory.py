"""Character accessory endpoint — identity-pack accessory slot (v1).

POST /{character_id}/identity-accessory
  Adds or replaces a locked accessory in the character's identity_anchor_json.
  Requires auth + ownership. No visual_locked requirement (forward compatibility).
"""
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.character import Character as CharacterModel
from app.models.user import User
from app.services.character_accessory import append_accessory

logger = logging.getLogger(__name__)

router = APIRouter()


class AccessoryCreateRequest(BaseModel):
    type: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    visual_rules: list[str] = Field(default_factory=list, max_length=10)
    anchor_image_url: str | None = None


class AccessoryResponse(BaseModel):
    character_id: int
    accessories: list[dict]


@router.post(
    "/{character_id}/identity-accessory",
    response_model=AccessoryResponse,
    summary="Add or replace a locked accessory in the character's identity pack (v1)",
)
def add_identity_accessory(
    character_id: int,
    body: AccessoryCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessoryResponse:
    """Add or replace a locked accessory slot on the character's identity_anchor_json.

    - Requires authentication and character ownership.
    - Does NOT require visual_locked=True (forward compatibility).
    - If an accessory with the same type already exists, it is replaced.
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )

    # Build the accessory dict
    new_accessory: dict = {
        "id": f"{body.type}_{uuid4().hex[:8]}",
        "type": body.type,
        "name": body.name,
        "description": body.description,
        "visual_rules": body.visual_rules,
        "anchor_image_url": body.anchor_image_url,
        "locked": True,
    }

    updated_json = append_accessory(character.identity_anchor_json, new_accessory)
    character.identity_anchor_json = updated_json
    db.commit()
    db.refresh(character)

    from app.services.character_accessory import get_accessories
    accessories = get_accessories(character.identity_anchor_json)

    logger.info(
        "identity_accessory_saved character_id=%s type=%s accessory_id=%s",
        character_id,
        body.type,
        new_accessory["id"],
    )

    return AccessoryResponse(character_id=character_id, accessories=accessories)
