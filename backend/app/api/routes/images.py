"""Image library endpoints — generate and list user images."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.entitlements import require_creator
from app.models.user import User
from app.models.character import Character
from app.models.character_image import CharacterImage, ImageKindEnum
from app.schemas.character_image import CharacterImageRead
from app.services.asset_persistence import OwnedBy, persist_image_asset
from app.services.image_quota import check_weekly_quota, get_quota_status
from app.services.stub_image_generator import render_placeholder_png

router = APIRouter()


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=250)


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
            detail="Image generation belongs to characters — generate from a character you own.",
        )
    # Prefer a visually-locked character
    for c in chars:
        if c.visual_locked:
            return c
    return chars[0]


@router.get("/quota")
def get_image_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's weekly image generation allowance status."""
    return get_quota_status(current_user, db)


@router.post(
    "/generate",
    response_model=CharacterImageRead,
    dependencies=[Depends(require_creator)],
)
def generate_library_image(
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a stub image and save it to the user's image library."""
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    character = _pick_character(db, current_user)

    image = persist_image_asset(
        db,
        content=render_placeholder_png(
            label=body.prompt[:40] + ("…" if len(body.prompt) > 40 else ""),
            sublabel="Ficshon Library",
            role="generated",
        ),
        # The character was picked from this account's own characters, so its
        # owner IS the caller; ``OwnedBy.character`` keeps one rule across every
        # writer — the asset belongs to the character's owner — and makes
        # ``current_user`` unnameable here.
        owner=OwnedBy.character(character),
        kind=ImageKindEnum.GENERATED,
        provider="stub",
        prompt_summary=body.prompt[:80],
        metadata={"library": True, "prompt": body.prompt},
    )
    # The commit moved here from inside ``create_character_image``, which used
    # to own a transaction it could not see the rest of. This route's work is
    # the row, so the route commits it.
    db.commit()
    db.refresh(image)

    return image


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
