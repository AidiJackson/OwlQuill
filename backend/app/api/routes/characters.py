"""Character routes."""
import io
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.config import settings
from app.core.storage import save_image, file_path_to_url
from app.models.user import User
from app.models.character import Character as CharacterModel, VisibilityEnum
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum
from app.models.user_image import UserImage
from app.schemas.character import Character, CharacterCreate, CharacterUpdate, CharacterSearchResult
from app.services.pack_version import compute_identity_health

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"
_AVATAR_SIZE = (512, 512)
_COVER_SIZE = (2048, 720)


def _crop_to_banner(png_bytes: bytes) -> bytes:
    """Upper-biased crop and resize PNG bytes to 2048×720 cover banner.

    Faces and subjects appear in the upper portion of most generated images.
    We bias the vertical crop toward the top (15% down from the top of the
    excess) so faces are captured reliably.  Horizontal crops (wide images)
    are always centre-cropped — no horizontal bias is needed because the
    prompt instructs left-third subject placement at generation time.
    """
    img = PILImage.open(io.BytesIO(png_bytes))
    w, h = img.size
    target_ratio = _COVER_SIZE[0] / _COVER_SIZE[1]  # ~2.844

    if w / h > target_ratio:
        # Image is wider than target — crop horizontally (centre).
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        # Image is taller than target — crop vertically with upper bias.
        new_h = int(w / target_ratio)
        excess = h - new_h
        # Upper-biased at 15%: captures face/subject near top of frame.
        # When excess is 0 or negative, top=0 (no crop needed).
        top = max(0, min(int(excess * 0.15), excess))
        img = img.crop((0, top, w, top + new_h))

    img = img.resize(_COVER_SIZE, PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _crop_to_square(png_bytes: bytes) -> bytes:
    """Center-crop and resize PNG bytes to 512×512 square avatar."""
    img = PILImage.open(io.BytesIO(png_bytes))
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize(_AVATAR_SIZE, PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class SetCharacterAvatarRequest(BaseModel):
    image_type: str = Field(..., pattern=r"^(character|user)$")
    image_id: int


class SetCharacterAvatarResponse(BaseModel):
    avatar_url: str


class SetCharacterCoverRequest(BaseModel):
    image_type: str = Field(..., pattern=r"^(character|user)$")
    image_id: int
    cover_position_y: float = Field(default=0.5, ge=0.0, le=1.0)
    cover_position_x: float = Field(default=0.5, ge=0.0, le=1.0)


class SetCharacterCoverResponse(BaseModel):
    cover_url: str
    cover_position_y: float
    cover_position_x: float

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
    character.identity_health = compute_identity_health(character)
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


@router.post("/{character_id}/avatar", response_model=SetCharacterAvatarResponse)
def set_character_avatar(
    character_id: int,
    req: SetCharacterAvatarRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SetCharacterAvatarResponse:
    """Set a character's avatar from an existing character image or user image."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if req.image_type == "character":
        img = db.query(CharacterImage).filter(CharacterImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        src_char = db.query(CharacterModel).filter(CharacterModel.id == img.character_id).first()
        if not src_char or src_char.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != ImageStatusEnum.ACTIVE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")
    else:
        img = db.query(UserImage).filter(UserImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        if img.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")

    if img.file_path.startswith(("http://", "https://")):
        # R2-hosted image: use the URL directly, no local disk read needed.
        avatar_url = img.file_path
    else:
        source_path = Path(__file__).resolve().parent.parent.parent.parent / img.file_path.lstrip("/")
        if not source_path.exists():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source image file not found on disk")
        raw_bytes = source_path.read_bytes()
        avatar_bytes = _crop_to_square(raw_bytes)
        file_path = save_image(avatar_bytes)
        avatar_url = file_path_to_url(file_path)

    character.avatar_url = avatar_url
    db.commit()

    return SetCharacterAvatarResponse(avatar_url=avatar_url)


@router.post("/{character_id}/cover", response_model=SetCharacterCoverResponse)
def set_character_cover(
    character_id: int,
    req: SetCharacterCoverRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SetCharacterCoverResponse:
    """Set a character's cover/banner from an existing character image or user image."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if req.image_type == "character":
        img = db.query(CharacterImage).filter(CharacterImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        src_char = db.query(CharacterModel).filter(CharacterModel.id == img.character_id).first()
        if not src_char or src_char.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != ImageStatusEnum.ACTIVE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")
    else:
        from app.models.user_image import UserImage
        img = db.query(UserImage).filter(UserImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        if img.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")

    # Use the original image directly as the cover URL.
    # CSS object-fit:cover + object-position handles all positioning at render time.
    cover_url = file_path_to_url(img.file_path)

    character.cover_url = cover_url
    character.cover_position_y = req.cover_position_y
    character.cover_position_x = req.cover_position_x
    db.commit()

    return SetCharacterCoverResponse(
        cover_url=cover_url,
        cover_position_y=req.cover_position_y,
        cover_position_x=req.cover_position_x,
    )


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
