"""Body canon endpoints — persistent anatomical markings (tattoos, scars, burns, birthmarks)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import save_image
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage
from app.models.user import User
from app.schemas.body_canon import BodyCanonRead, BodyMarkingCreate, BodyMarkingRead
from app.services.body_canon import (
    add_marking,
    build_anchor_generation_prompt,
    get_marking_by_id,
    load_markings,
    remove_marking,
    to_read_list,
    update_marking,
)
from app.services.image_provider import get_provider_for_option

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
    # Style-shop tattoo items are NO LONGER auto-synced into body canon here.
    # Body canon is now managed exclusively through the /identity-canon routes.
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


# ── Anchor image endpoints ────────────────────────────────────────────


class BodyAnchorResponse(BaseModel):
    character_id: int
    marking: BodyMarkingRead


def _marking_to_read(marking) -> BodyMarkingRead:
    from app.services.body_canon import build_compact_token
    return BodyMarkingRead(**marking.model_dump(), compact_token=build_compact_token(marking))


@router.post(
    "/{character_id}/body-markings/{marking_id}/generate-anchor",
    response_model=BodyAnchorResponse,
    summary="Generate a close-up body anchor reference image for a marking",
)
def generate_body_anchor(
    character_id: int,
    marking_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodyAnchorResponse:
    character = _get_owned_character(character_id, current_user, db)
    marking = get_marking_by_id(character, marking_id)
    if not marking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marking '{marking_id}' not found on this character.",
        )

    anchor_prompt = build_anchor_generation_prompt(marking, character_name=character.name or "")

    try:
        provider = get_provider_for_option("option1")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image provider unavailable. Please try again later.",
        ) from exc

    try:
        png_bytes = provider.generate_image(prompt=anchor_prompt)
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "body_canon_anchor_generation_failed character_id=%s marking_id=%s error=%r",
            character_id, marking_id, str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Anchor image generation failed. Please try again.",
        ) from exc

    anchor_url = save_image(png_bytes)
    updated = update_marking(character, marking_id, {
        "anchor_image_url": anchor_url,
        "anchor_status": "generated",
        "anchor_prompt": anchor_prompt,
    })
    db.commit()

    logger.info(
        "body_canon_anchor_generated character_id=%s marking_id=%s url=%s",
        character_id, marking_id, anchor_url,
    )
    return BodyAnchorResponse(character_id=character_id, marking=_marking_to_read(updated))  # type: ignore[arg-type]


@router.post(
    "/{character_id}/body-markings/{marking_id}/lock-anchor",
    response_model=BodyAnchorResponse,
    summary="Lock a generated body anchor image",
)
def lock_body_anchor(
    character_id: int,
    marking_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodyAnchorResponse:
    character = _get_owned_character(character_id, current_user, db)
    marking = get_marking_by_id(character, marking_id)
    if not marking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Marking '{marking_id}' not found.")
    if not marking.anchor_image_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No anchor image generated yet. Call generate-anchor first.",
        )
    updated = update_marking(character, marking_id, {"anchor_status": "locked"})
    db.commit()
    logger.info("body_canon_anchor_locked character_id=%s marking_id=%s", character_id, marking_id)
    return BodyAnchorResponse(character_id=character_id, marking=_marking_to_read(updated))  # type: ignore[arg-type]


class UseExistingAnchorBody(BaseModel):
    image_id: int


@router.post(
    "/{character_id}/body-markings/{marking_id}/use-existing-anchor",
    response_model=BodyAnchorResponse,
    summary="Assign an existing gallery image as the anchor for a body marking",
)
def use_existing_body_anchor(
    character_id: int,
    marking_id: str,
    body: UseExistingAnchorBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodyAnchorResponse:
    """Promote an existing CharacterImage as a marking anchor, bypassing generation."""
    character = _get_owned_character(character_id, current_user, db)
    marking = get_marking_by_id(character, marking_id)
    if not marking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Marking '{marking_id}' not found on this character.",
        )
    image = db.query(CharacterImage).filter(
        CharacterImage.id == body.image_id,
        CharacterImage.character_id == character_id,
    ).first()
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found or does not belong to this character.",
        )
    updated = update_marking(character, marking_id, {
        "anchor_image_url": image.file_path,
        "anchor_status": "locked",
        "anchor_prompt": None,
    })
    db.commit()
    logger.info(
        "body_canon_anchor_use_existing character_id=%s marking_id=%s image_id=%s url=%s",
        character_id, marking_id, body.image_id, image.file_path,
    )
    return BodyAnchorResponse(character_id=character_id, marking=_marking_to_read(updated))  # type: ignore[arg-type]


@router.post(
    "/{character_id}/body-markings/{marking_id}/replace-anchor",
    response_model=BodyAnchorResponse,
    summary="Replace an existing body anchor image with a freshly generated one",
)
def replace_body_anchor(
    character_id: int,
    marking_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodyAnchorResponse:
    """Regenerate the anchor and reset status to 'generated' (requires re-locking)."""
    character = _get_owned_character(character_id, current_user, db)
    marking = get_marking_by_id(character, marking_id)
    if not marking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Marking '{marking_id}' not found.")

    anchor_prompt = build_anchor_generation_prompt(marking, character_name=character.name or "")

    try:
        provider = get_provider_for_option("option1")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Image provider unavailable.") from exc

    try:
        png_bytes = provider.generate_image(prompt=anchor_prompt)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Anchor image generation failed.") from exc

    anchor_url = save_image(png_bytes)
    updated = update_marking(character, marking_id, {
        "anchor_image_url": anchor_url,
        "anchor_status": "generated",
        "anchor_prompt": anchor_prompt,
    })
    db.commit()
    logger.info("body_canon_anchor_replaced character_id=%s marking_id=%s url=%s", character_id, marking_id, anchor_url)
    return BodyAnchorResponse(character_id=character_id, marking=_marking_to_read(updated))  # type: ignore[arg-type]
