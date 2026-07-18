"""Character accessory endpoints — identity-pack accessory slot (v1/v2).

POST /{character_id}/identity-accessory
  Adds or replaces a locked accessory in the character's identity_anchor_json.
  Requires auth + ownership. No visual_locked requirement (forward compatibility).

POST /{character_id}/identity-accessory/generate-anchor
  Generates a standalone anchor image for an existing accessory (v2).

POST /{character_id}/identity-accessory/lock-anchor
  Locks an accessory anchor image that has already been generated (v2).
"""
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import load_image_bytes, save_image
from app.models.character import Character as CharacterModel
from app.models.user import User
from app.services.character_accessory import (
    append_accessory,
    build_anchor_prompt,
    build_fit_anchor_prompt,
    get_accessories,
    get_identity_anchor_urls,
    update_accessory_in_json,
)
from app.services.image_provider import get_provider_for_option
from app.services.provider_capabilities import Capability, provider_supports

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


class AnchorActionRequest(BaseModel):
    accessory_id: str = Field(..., min_length=1, max_length=100)


class AnchorResponse(BaseModel):
    character_id: int
    accessory: dict


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


@router.post(
    "/{character_id}/identity-accessory/generate-anchor",
    response_model=AnchorResponse,
    summary="Generate a standalone anchor image for a locked accessory (v2)",
)
def generate_accessory_anchor(
    character_id: int,
    body: AnchorActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnchorResponse:
    """Generate a product-style standalone image for the accessory and store it.

    - Loads the named accessory from identity_anchor_json.
    - Builds a standalone object prompt (no wearer, neutral background).
    - Generates the image via the default image provider (option1).
    - Saves it via the existing storage pipeline (R2 or local disk).
    - Updates the accessory with anchor_image_url and anchor_status="generated".
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )

    accessories = get_accessories(character.identity_anchor_json)
    target = next((a for a in accessories if a.get("id") == body.accessory_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Accessory '{body.accessory_id}' not found on this character.",
        )

    anchor_prompt = build_anchor_prompt(target)

    try:
        provider = get_provider_for_option("option1")
    except (RuntimeError, ValueError) as exc:
        logger.warning(
            "accessory_anchor_provider_unavailable character_id=%s accessory_id=%s error=%r",
            character_id, body.accessory_id, str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image provider unavailable. Please try again later.",
        ) from exc

    try:
        png_bytes = provider.generate_image(prompt=anchor_prompt)
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "accessory_anchor_generation_failed character_id=%s accessory_id=%s error=%r",
            character_id, body.accessory_id, str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Anchor image generation failed. Please try again.",
        ) from exc

    anchor_image_url = save_image(png_bytes)

    updates = {
        "anchor_image_url": anchor_image_url,
        "anchor_status": "generated",
        "anchor_prompt": anchor_prompt,
        "anchor_created_at": datetime.utcnow().isoformat() + "Z",
    }
    updated_json, updated_acc = update_accessory_in_json(
        character.identity_anchor_json, body.accessory_id, updates
    )
    character.identity_anchor_json = updated_json
    db.commit()

    logger.info(
        "identity_accessory_anchor_generated character_id=%s accessory_id=%s url=%s",
        character_id, body.accessory_id, anchor_image_url,
    )

    return AnchorResponse(character_id=character_id, accessory=updated_acc)  # type: ignore[arg-type]


@router.post(
    "/{character_id}/identity-accessory/lock-anchor",
    response_model=AnchorResponse,
    summary="Lock an accessory anchor image that has been generated (v2)",
)
def lock_accessory_anchor(
    character_id: int,
    body: AnchorActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnchorResponse:
    """Lock the generated anchor image for an accessory.

    - Requires anchor_image_url to be set (i.e. generate-anchor was called first).
    - Sets anchor_status="locked".
    - A locked anchor is used as a supporting visual reference during image generation
      when the provider supports multi-image input.
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )

    accessories = get_accessories(character.identity_anchor_json)
    target = next((a for a in accessories if a.get("id") == body.accessory_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Accessory '{body.accessory_id}' not found on this character.",
        )

    if not target.get("anchor_image_url"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No anchor image exists for this accessory. Generate one first.",
        )

    updated_json, updated_acc = update_accessory_in_json(
        character.identity_anchor_json, body.accessory_id, {"anchor_status": "locked"}
    )
    character.identity_anchor_json = updated_json
    db.commit()

    logger.info(
        "identity_accessory_anchor_locked character_id=%s accessory_id=%s",
        character_id, body.accessory_id,
    )

    return AnchorResponse(character_id=character_id, accessory=updated_acc)  # type: ignore[arg-type]


@router.post(
    "/{character_id}/identity-accessory/generate-fit-anchor",
    response_model=AnchorResponse,
    summary="Generate a worn-portrait fit anchor for an accessory (v2)",
)
def generate_fit_anchor(
    character_id: int,
    body: AnchorActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnchorResponse:
    """Generate a neutral portrait of the character correctly wearing the accessory.

    - Requires visual_locked=True (locked character identity).
    - Requires accessory to have a description or object anchor.
    - Uses character identity anchor images as primary reference.
    - Prompt enforces: accessory fitted to lower face only, head/skull/hair remain visible.
    - Saves fit_anchor_image_url and fit_anchor_status="generated".
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )
    if not character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Character identity must be locked before generating a fit anchor.",
        )

    accessories = get_accessories(character.identity_anchor_json)
    target = next((a for a in accessories if a.get("id") == body.accessory_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Accessory '{body.accessory_id}' not found on this character.",
        )

    if not target.get("description") and not target.get("anchor_image_url"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Accessory must have a description or object anchor before generating a fit anchor.",
        )

    fit_prompt = build_fit_anchor_prompt(target, character_name=character.name or "")

    try:
        provider = get_provider_for_option("option1")
    except (RuntimeError, ValueError) as exc:
        logger.warning(
            "fit_anchor_provider_unavailable character_id=%s accessory_id=%s error=%r",
            character_id, body.accessory_id, str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image provider unavailable. Please try again later.",
        ) from exc

    # Load character identity anchor images (face as primary reference)
    anchor_urls = get_identity_anchor_urls(character.identity_anchor_json)
    anchor_images: list[bytes] = []
    for url in anchor_urls:
        try:
            anchor_images.append(load_image_bytes(url))
        except Exception as _le:
            logger.warning(
                "fit_anchor_load_identity_image_failed character_id=%s url=%s error=%r",
                character_id, url, str(_le),
            )

    png_bytes: bytes | None = None
    provider_supports_multi = provider_supports(provider, Capability.MULTI_IMAGE_ANCHORS)

    if provider_supports_multi and anchor_images:
        try:
            png_bytes = provider.generate_with_anchors(
                prompt=fit_prompt,
                anchor_images=anchor_images,
            )
        except (ValueError, RuntimeError, NotImplementedError) as _e:
            logger.warning(
                "fit_anchor_multi_failed character_id=%s error=%r", character_id, str(_e),
            )

    if png_bytes is None and anchor_images:
        try:
            png_bytes = provider.generate_grounded_image(
                prompt=fit_prompt,
                reference_image_bytes=anchor_images[0],
            )
        except (ValueError, RuntimeError, NotImplementedError) as _e:
            logger.warning(
                "fit_anchor_grounded_failed character_id=%s error=%r", character_id, str(_e),
            )

    if png_bytes is None:
        try:
            png_bytes = provider.generate_image(prompt=fit_prompt)
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "fit_anchor_generation_failed character_id=%s accessory_id=%s error=%r",
                character_id, body.accessory_id, str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Fit anchor image generation failed. Please try again.",
            ) from exc

    if png_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fit anchor image generation failed. Please try again.",
        )

    fit_anchor_url = save_image(png_bytes)

    updates = {
        "fit_anchor_image_url": fit_anchor_url,
        "fit_anchor_status": "generated",
        "fit_anchor_prompt": fit_prompt,
    }
    updated_json, updated_acc = update_accessory_in_json(
        character.identity_anchor_json, body.accessory_id, updates
    )
    character.identity_anchor_json = updated_json
    db.commit()

    logger.info(
        "identity_accessory_fit_anchor_generated character_id=%s accessory_id=%s url=%s",
        character_id, body.accessory_id, fit_anchor_url,
    )

    return AnchorResponse(character_id=character_id, accessory=updated_acc)  # type: ignore[arg-type]


@router.post(
    "/{character_id}/identity-accessory/lock-fit-anchor",
    response_model=AnchorResponse,
    summary="Lock a generated fit anchor so it is used in scene generation (v2)",
)
def lock_fit_anchor(
    character_id: int,
    body: AnchorActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnchorResponse:
    """Lock the generated fit anchor for an accessory.

    - Requires fit_anchor_image_url to be set (generate-fit-anchor called first).
    - Sets fit_anchor_status="locked".
    - A locked fit anchor is used as the accessory support reference during
      scene generation, placed after character identity anchors in the prompt
      hierarchy. The standalone object anchor is never used for scene generation.
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )

    accessories = get_accessories(character.identity_anchor_json)
    target = next((a for a in accessories if a.get("id") == body.accessory_id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Accessory '{body.accessory_id}' not found on this character.",
        )

    if not target.get("fit_anchor_image_url"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No fit anchor image exists for this accessory. Generate one first.",
        )

    updated_json, updated_acc = update_accessory_in_json(
        character.identity_anchor_json, body.accessory_id, {"fit_anchor_status": "locked"}
    )
    character.identity_anchor_json = updated_json
    db.commit()

    logger.info(
        "identity_accessory_fit_anchor_locked character_id=%s accessory_id=%s",
        character_id, body.accessory_id,
    )

    return AnchorResponse(character_id=character_id, accessory=updated_acc)  # type: ignore[arg-type]
