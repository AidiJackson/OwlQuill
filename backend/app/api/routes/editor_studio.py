"""Editor Studio routes — Sprint E1 foundation.

POST /editor/generate — edit/transform 1-3 existing character images with a
prompt via the gpt-image edit API. Character-preserving transformation only:
no Canon Studio generation, no Adult Studio pipeline, no LoRA/RunPod.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
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
from app.services.editor_job_service import (
    EditorJobError,
    cancel_job,
    get_job,
    get_latest_job,
    start_editor_job,
)
from app.services.editor_studio import (
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
    if provider == "self_hosted" and total_sources != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The self_hosted editor transforms exactly 1 source image.",
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
        # Worker thread: edits block for 30s (gpt-image/grok) up to ~10 min
        # (self_hosted RunPod transform) and must not stall the event loop.
        png_bytes = await run_in_threadpool(
            lambda: editor.edit(
                prompt=prompt,
                source_images=source_bytes,
                strength=strength,
            )
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
            "editor_version": editor.editor_version,
            "provider": provider,
            "editor_provider": provider,
            # self_hosted is a full source-truth transform (mask + inpaint);
            # the API providers are single-shot edits.
            "editor_mode": "transform" if provider == "self_hosted" else "edit",
            "prompt": prompt,
            "strength": strength,
            # gpt-image is the only backend with an API-level fidelity control;
            # grok accepts strength for interface parity but cannot apply it.
            "input_fidelity": (
                strength_to_input_fidelity(strength) if provider == "gpt-image" else None
            ),
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

    response = EditorGenerateResponse(
        success=True,
        image_url=file_path_to_url(file_path),
        character_id=character_id,
        provider=provider,
        prompt=prompt,
        strength=strength,
        image=CharacterImageRead.model_validate(img),
    )
    logger.info("EDITOR_GENERATE_RESPONSE %s", response.model_dump_json()[:600])
    return response


# ── Async editor jobs (Sprint E5) — self_hosted only, fire-and-poll ────────
# POST /editor/jobs starts ONE detached transform and returns 202 immediately;
# the UI polls GET /editor/jobs/{id}. No multi-minute blocking request, so no
# gateway timeout can fake a failure. Admin-only (matches the provider gate).

from datetime import datetime as _dt  # noqa: E402

from app.models.editor_job import EditorJob  # noqa: E402


class EditorJobRead(BaseModel):
    """Editor async job snapshot (queued|running|completed|failed)."""

    id: int
    character_id: int
    provider: str
    prompt: str
    state: str
    run_id: str
    quality_status: Optional[str] = None
    final_image_url: Optional[str] = None
    image_id: Optional[int] = None
    image: Optional[CharacterImageRead] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: Optional[_dt] = None
    updated_at: Optional[_dt] = None


class EditorJobEnvelope(BaseModel):
    """GET wrapper — ``job`` is null when none has ever been started."""

    job: Optional[EditorJobRead] = None


def _job_to_read(db: Session, job: EditorJob) -> EditorJobRead:
    image = None
    if job.image_id:
        record = db.query(CharacterImage).filter(CharacterImage.id == job.image_id).first()
        if record is not None:
            image = CharacterImageRead.model_validate(record)
    return EditorJobRead(
        id=job.id, character_id=job.character_id, provider=job.provider,
        prompt=job.prompt, state=job.state, run_id=job.run_id,
        quality_status=job.quality_status, final_image_url=job.final_image_url,
        image_id=job.image_id, image=image, result=job.result_json,
        error=job.error, created_at=job.created_at, updated_at=job.updated_at,
    )


def _require_admin_and_character(
    db: Session, current_user: User, character_id: int
) -> CharacterModel:
    from app.core.config import settings

    is_admin = bool(current_user.is_admin) or (
        current_user.email.lower() in settings.get_admin_emails()
    )
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-hosted editor jobs are admin-only for now.",
        )
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Character not found.")
    return character


@router.post(
    "/jobs",
    response_model=EditorJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an async self_hosted editor transform job (returns 202)",
)
async def editor_job_start(
    character_id: int = Form(...),
    prompt: str = Form(...),
    provider: str = Form("self_hosted"),
    strength: float = Form(0.25),
    source_image_ids: Optional[str] = Form(None),
    images: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EditorJobRead:
    """Fire-and-poll: validates inputs, snapshots the source image to storage,
    launches ONE detached driver, and returns the queued/running job."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Prompt must not be empty.")
    if provider != "self_hosted":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Async editor jobs support only the self_hosted provider; "
                   "use POST /editor/generate for gpt-image and grok.",
        )
    _require_admin_and_character(db, current_user, character_id)

    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    ids = _parse_source_image_ids(source_image_ids)
    total_sources = len(images) + len(ids)
    if total_sources != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The self_hosted editor transforms exactly 1 source image.",
        )

    if images:
        upload = images[0]
        if (upload.content_type or "") not in _ACCEPTED_CONTENT_TYPES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Only PNG, JPEG, or WebP source images are accepted.")
        source_bytes = await upload.read()
        if not source_bytes:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Uploaded source image is empty.")
        if len(source_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail="Source image exceeds 10 MB limit.")
    else:
        record = (
            db.query(CharacterImage)
            .filter(CharacterImage.id == ids[0],
                    CharacterImage.character_id == character_id,
                    CharacterImage.status == ImageStatusEnum.ACTIVE)
            .first()
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source image id {ids[0]} not found for this character.")
        try:
            source_bytes = load_image_bytes(record.file_path)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source image id {ids[0]} could not be read.")

    # Snapshot the source so the detached driver reads a stable path even if
    # the original is later deleted.
    source_file_path = save_image(source_bytes)

    try:
        job = start_editor_job(
            db,
            character_id=character_id,
            user_id=current_user.id,
            prompt=prompt,
            source_file_path=source_file_path,
            source_image_ids=ids,
            strength=clamp_strength(strength),
        )
    except EditorJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    logger.info("EDITOR_JOB_START job_id=%s run_id=%s character_id=%s user_id=%s",
                job.id, job.run_id, character_id, current_user.id)
    return _job_to_read(db, job)


@router.get(
    "/jobs/latest",
    response_model=EditorJobEnvelope,
    summary="Poll the latest editor job for a character (reconciles running→terminal)",
)
def editor_job_latest(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EditorJobEnvelope:
    _require_admin_and_character(db, current_user, character_id)
    job = get_latest_job(db, character_id)
    return EditorJobEnvelope(job=_job_to_read(db, job) if job else None)


@router.get(
    "/jobs/{job_id}",
    response_model=EditorJobRead,
    summary="Poll one editor job by id (reconciles running→terminal)",
)
def editor_job_get(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EditorJobRead:
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Editor job not found.")
    _require_admin_and_character(db, current_user, job.character_id)
    return _job_to_read(db, job)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=EditorJobRead,
    summary="Cancel an active editor job (terminate pod best-effort + mark failed)",
)
def editor_job_cancel(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EditorJobRead:
    existing = db.query(EditorJob).filter(EditorJob.id == job_id).first()
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Editor job not found.")
    _require_admin_and_character(db, current_user, existing.character_id)
    try:
        job = cancel_job(db, job_id)
    except EditorJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    logger.info("EDITOR_JOB_CANCEL job_id=%s pod_id=%s", job.id, job.pod_id)
    return _job_to_read(db, job)
