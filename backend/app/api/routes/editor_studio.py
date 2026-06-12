"""Editor Studio routes — Sprint E1 foundation.

POST /editor/generate — edit/transform 1-3 existing character images with a
prompt via the gpt-image edit API. Character-preserving transformation only:
no Canon Studio generation, no Adult Studio pipeline, no LoRA/RunPod.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import file_path_to_url, load_image_bytes, save_image
from app.models.character import Character as CharacterModel
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User
from app.schemas.character_image import CharacterImageRead
from app.services.editor_studio import (
    EDITOR_VERSION,
    MAX_SOURCE_IMAGES,
    SUPPORTED_EDITOR_PROVIDERS,
    clamp_strength,
    get_editor,
    strength_to_input_fidelity,
)
from app.services.image_quota import check_weekly_quota

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per source image
_ACCEPTED_CONTENT_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/webp")


class EditorGenerateResponse(BaseModel):
    """Response for POST /editor/generate."""

    success: bool
    image_url: Optional[str] = None
    character_id: int
    provider: str
    prompt: str
    strength: float
    image: Optional[CharacterImageRead] = None
    error: Optional[str] = None


def _parse_source_image_ids(raw: Optional[str]) -> list[int]:
    """Parse a comma-separated id list ('12,34') into ints."""
    if not raw or not raw.strip():
        return []
    try:
        return [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source_image_ids must be a comma-separated list of integers.",
        )


@router.post(
    "/generate",
    response_model=EditorGenerateResponse,
    summary="Edit/transform existing character images (Editor Studio E1)",
)
async def editor_generate(
    character_id: int = Form(...),
    prompt: str = Form(...),
    provider: str = Form("gpt-image"),
    strength: float = Form(0.25),
    source_image_ids: Optional[str] = Form(
        None, description="Comma-separated existing character_image ids to use as sources"
    ),
    images: list[UploadFile] = File(
        default=[], description="Up to 3 uploaded source images (PNG/JPEG/WebP)"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EditorGenerateResponse:
    """Transform existing character image(s) per the prompt — same character,
    edited scene/outfit. Sources may be uploaded files, existing library image
    ids, or a mix; 1-3 total.
    """
    # ── Validation: prompt / provider / strength ──────────────────────
    prompt = (prompt or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Prompt must not be empty.",
        )
    if provider not in SUPPORTED_EDITOR_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported editor provider: {provider!r}. "
                f"Supported: {', '.join(SUPPORTED_EDITOR_PROVIDERS)}."
            ),
        )
    strength = clamp_strength(strength)

    # ── Auth + ownership (owner or admin) ─────────────────────────────
    character = (
        db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    )
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Character not found."
        )
    if character.owner_id != current_user.id and not bool(current_user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to use this character.",
        )

    # ── Weekly allowance (admins bypass inside the helper) ────────────
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    # ── Collect source images: uploads + library ids, 1-3 total ──────
    ids = _parse_source_image_ids(source_image_ids)
    total_sources = len(images) + len(ids)
    if total_sources == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one source image is required.",
        )
    if total_sources > MAX_SOURCE_IMAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"At most {MAX_SOURCE_IMAGES} source images are allowed.",
        )

    source_bytes: list[bytes] = []

    for upload in images:
        content_type = upload.content_type or ""
        if content_type not in _ACCEPTED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only PNG, JPEG, or WebP source images are accepted.",
            )
        raw = await upload.read()
        if not raw:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Uploaded source image {upload.filename!r} is empty.",
            )
        if len(raw) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Source image exceeds 10 MB limit.",
            )
        source_bytes.append(raw)

    for img_id in ids:
        record = (
            db.query(CharacterImage)
            .filter(
                CharacterImage.id == img_id,
                CharacterImage.character_id == character_id,
                CharacterImage.status == ImageStatusEnum.ACTIVE,
            )
            .first()
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source image id {img_id} not found for this character.",
            )
        try:
            source_bytes.append(load_image_bytes(record.file_path))
        except Exception as exc:
            logger.warning(
                "EDITOR_SOURCE_LOAD_FAILED character_id=%s image_id=%s error=%r",
                character_id, img_id, str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source image id {img_id} could not be read.",
            )

    # ── Editor backend ────────────────────────────────────────────────
    try:
        editor = get_editor(provider)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Editor provider unavailable: {exc}",
        )

    logger.info(
        "EDITOR_GENERATE_START character_id=%s user_id=%s provider=%s strength=%s "
        "fidelity=%s sources=%d (uploads=%d, library=%d) prompt_preview=%r",
        character_id, current_user.id, provider, strength,
        strength_to_input_fidelity(strength),
        len(source_bytes), len(images), len(ids), prompt[:80],
    )

    try:
        png_bytes = editor.edit(
            prompt=prompt,
            source_images=source_bytes,
            strength=strength,
        )
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "EDITOR_GENERATE_FAILED character_id=%s error=%r", character_id, str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Editor generation failed: {exc}",
        )

    # ── Persist via existing storage + image library ──────────────────
    # Schema gap (E1): ImageKindEnum has no editor-specific kind; SCENE_ONLY is
    # the closest safe kind (generated, never canon). Editor provenance lives
    # in metadata_json.
    file_path = save_image(png_bytes)
    img = CharacterImage(
        character_id=character_id,
        user_id=current_user.id,
        kind=ImageKindEnum.SCENE_ONLY,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider,
        prompt_summary=prompt[:200],
        metadata_json={
            "editor_generated": True,
            "editor_version": EDITOR_VERSION,
            "provider": provider,
            "prompt": prompt,
            "strength": strength,
            "input_fidelity": strength_to_input_fidelity(strength),
            "source_image_ids": ids,
            "uploaded_source_count": len(images),
        },
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    logger.info(
        "EDITOR_GENERATE_SUCCESS character_id=%s image_id=%s file_path=%s",
        character_id, img.id, file_path,
    )

    return EditorGenerateResponse(
        success=True,
        image_url=file_path_to_url(file_path),
        character_id=character_id,
        provider=provider,
        prompt=prompt,
        strength=strength,
        image=CharacterImageRead.model_validate(img),
    )
