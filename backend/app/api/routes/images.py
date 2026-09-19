"""Image library endpoints — the account's weekly allowance and its library listing.

``POST /images/generate`` lived here until Polish Phase 6.2. It made a stub
placeholder PNG, attached it to whichever character it picked, and spent the
weekly image allowance on it — a characterless generator from before the
product went character-first. Generation is ``POST /characters/{id}/image-
generator/generate`` (image_generator.py); the rows the old route wrote are
ordinary CharacterImage records and are untouched.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.character_image import CharacterImage
from app.schemas.character_image import CharacterImageRead
from app.services.image_quota import get_quota_status

router = APIRouter()


@router.get("/quota")
def get_image_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's weekly image generation allowance status."""
    return get_quota_status(current_user, db)


@router.get("/", response_model=list[CharacterImageRead])
def list_library_images(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the current user's library images (newest first).

    Ownership is ``CharacterImage.user_id`` (Phase 4B1). It was previously a
    ``character_id IN (characters I own)`` subquery — the same question routed
    through the character association. The ``library`` metadata filter and the
    ordering are unchanged.
    """
    images = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.user_id == current_user.id,
            CharacterImage.metadata_json["library"].as_boolean() == True,  # noqa: E712
        )
        .order_by(CharacterImage.created_at.desc())
        .all()
    )
    return images
