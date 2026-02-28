"""Image library endpoints — generate and list user images."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.character import Character
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum
from app.schemas.character_image import CharacterImageRead, CharacterImageCreate
from app.services.character_visual import create_character_image
from app.services.stub_image_generator import generate_placeholder_png

router = APIRouter()


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=250)


def _check_weekly_quota(user: User, db: Session) -> JSONResponse | None:
    """Return a 429 JSONResponse if the user has hit their weekly image limit, else None."""
    if user.email.lower() in settings.get_admin_emails():
        return None
    since = datetime.utcnow() - timedelta(days=7)
    count = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.user_id == user.id,
            CharacterImage.created_at >= since,
        )
        .count()
    )
    if count >= settings.IMAGE_WEEKLY_LIMIT:
        reset_in = int(timedelta(days=7).total_seconds())
        return JSONResponse(
            status_code=429,
            content={
                "error": "quota_exceeded",
                "detail": "Weekly image limit reached.",
                "limit": settings.IMAGE_WEEKLY_LIMIT,
                "reset_in_seconds": reset_in,
            },
        )
    return None


def _pick_character(db: Session, user: User) -> Character:
    """Pick the best character owned by *user* for library images."""
    chars = (
        db.query(Character)
        .filter(Character.owner_id == user.id)
        .order_by(Character.created_at)
        .all()
    )
    if not chars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You need to create a character before generating images.",
        )
    # Prefer a visually-locked character
    for c in chars:
        if c.visual_locked:
            return c
    return chars[0]


@router.post("/generate", response_model=CharacterImageRead)
def generate_library_image(
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a stub image and save it to the user's image library."""
    quota_error = _check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    character = _pick_character(db, current_user)

    file_path = generate_placeholder_png(
        label=body.prompt[:40] + ("…" if len(body.prompt) > 40 else ""),
        sublabel="Ficshon Library",
        role="generated",
    )

    data = CharacterImageCreate(
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        file_path=file_path,
        provider="stub",
        prompt_summary=body.prompt[:80],
        metadata_json={"library": True, "prompt": body.prompt},
    )
    image = create_character_image(db, character.id, data)

    # Stamp user_id for weekly quota tracking
    image.user_id = current_user.id
    db.commit()
    db.refresh(image)

    return image


@router.get("/", response_model=list[CharacterImageRead])
def list_library_images(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the current user's library images (newest first)."""
    char_ids = (
        db.query(Character.id)
        .filter(Character.owner_id == current_user.id)
        .subquery()
    )
    images = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id.in_(char_ids),
            CharacterImage.metadata_json["library"].as_boolean() == True,  # noqa: E712
        )
        .order_by(CharacterImage.created_at.desc())
        .all()
    )
    return images
