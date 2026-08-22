"""Image generator routes — synchronous (legacy) and async submit-and-poll.

The generation pipeline itself lives in
``app.services.image_generation_pipeline``; this module is routing, auth and
job plumbing only. That split exists because the published deployment target is
Cloud Run, which enforces a request deadline the pipeline can legitimately
exceed (see the module docstring there and in
``app.services.image_generation_job_service``).

Routes
------
``POST /{id}/image-generator/generate``
    Synchronous. Preserved unchanged in behaviour and shape for existing
    callers. Suitable for short, provider-light generations; NOT the founder
    workflow, because a long generation can outlive the request.

``POST /{id}/image-generator/jobs``
    Founder/seeder. Submit one generation intent → 202 + job view. Requires an
    ``idempotency_key``: one intent can only ever produce one paid submission.

``GET /{id}/image-generator/jobs/{public_id}``
    Poll one job.

``GET /{id}/image-generator/jobs/latest``
    Refresh recovery — re-attach to the most recent job for this character
    without spending again.

Identity contract (unchanged): CharacterIdentityCanon is the only identity
truth, generated scenes save as SCENE_ONLY (or COVER), and canon is never
mutated by any route here.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, user_is_admin
from app.core.entitlements import is_founder_account, require_creator, require_founder
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage
from app.models.user import User
from app.schemas.character_image import CharacterImageRead
from app.services import image_generation_job_service as _jobs
from app.services.image_generation_pipeline import (
    MAX_MANUAL_REFERENCES,
    params_from_request,
    run_image_generation,
)
from app.services.image_quota import check_weekly_quota
from app.services.manual_references import ManualReferenceError, resolve_manual_references

logger = logging.getLogger(__name__)

router = APIRouter()

# Retained because the test suite repoints it alongside the other route modules
# that write generated media (see tests/conftest.py::generated_media_dir).
_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"


# ── Request schemas ───────────────────────────────────────────────────


ReferenceRoleLiteral = Literal[
    "character_appearance", "clothing", "environment", "other", "unspecified"
]


class ImageGenerateRequest(BaseModel):
    """Request body for the generate routes."""

    prompt: str = Field(..., min_length=1, max_length=800)
    include_character: bool = False
    # Beta: Google (option2) is the default Canon provider. OpenAI (option1) is
    # additionally available to founders/seeders. FLUX Pro (option3), FLUX Max
    # (option4), Together FLUX.2 (option5) and Grok (option6) stay admin-only and
    # fall back to Google otherwise (enforced server-side).
    provider_option: Literal["option1", "option2", "option3", "option4", "option5", "option6"] = "option2"
    is_cover: bool = False  # When True, saves with kind=COVER for use as a character cover banner

    # ── Manual references (founder/seeder only) ───────────────────────
    # Hand-picked CharacterImage ids used as EXTRA visual evidence for this one
    # generation. They augment canon conditioning and never replace it; ids are
    # re-validated server-side against this character (see
    # app.services.manual_references). Empty for every ordinary creator request,
    # and rejected outright for a non-founder account.
    reference_image_ids: list[int] = Field(default_factory=list, max_length=MAX_MANUAL_REFERENCES)
    reference_roles: list[ReferenceRoleLiteral] = Field(
        default_factory=list, max_length=MAX_MANUAL_REFERENCES
    )


class ImageGenerateJobRequest(ImageGenerateRequest):
    """Submission body for an async generation job.

    ``idempotency_key`` is REQUIRED and is the whole point: one generation
    intent maps to one job row (unique per account) and therefore to at most one
    paid provider submission. A double-tap, a browser or proxy retry, or a
    reconnect re-sends the same key and re-attaches to the same job. Generating
    a genuinely new image means minting a new key.
    """

    idempotency_key: str = Field(..., min_length=8, max_length=64)


# ── Job views ─────────────────────────────────────────────────────────


class ImageGenerationJobView(BaseModel):
    """Owner-visible job state. ``diag_json`` is internal and never serialised."""

    job_id: str
    character_id: int
    status: str  # queued | running | completed | failed
    stage: Optional[str] = None
    progress_message: Optional[str] = None
    attempt_count: int = 0
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    #: True when this submission was answered by an EXISTING job — nothing new
    #: was started and nothing further was spent.
    reused: bool = False
    #: Safe account of what actually reached the provider (reference counts,
    #: refs_source, anything dropped for budget, and a warning if so).
    result: Optional[dict] = None
    image: Optional[CharacterImageRead] = None


class ImageGenerationJobEnvelope(BaseModel):
    """GET wrapper — ``job`` is null when none has ever been started."""

    job: Optional[ImageGenerationJobView] = None


def _job_to_view(db: Session, job, *, reused: bool = False) -> ImageGenerationJobView:
    image = None
    if job.image_id:
        record = db.query(CharacterImage).filter(CharacterImage.id == job.image_id).first()
        if record is not None:
            image = CharacterImageRead.model_validate(record)
    return ImageGenerationJobView(
        job_id=job.public_id,
        character_id=job.character_id,
        status=job.status,
        stage=job.stage,
        progress_message=job.progress_message,
        attempt_count=job.attempt_count or 0,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        error_message=job.error_message,
        reused=reused,
        result=job.result_json,
        image=image,
    )


# ── Shared auth helpers ───────────────────────────────────────────────


def _owned_character(db: Session, character_id: int, user: User) -> CharacterModel:
    """Fetch a character and enforce ownership, with this route's own messages."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to use this character.",
        )
    return character


def _guard_manual_references(
    db: Session, *, body: ImageGenerateRequest, character_id: int, user: User
) -> None:
    """Reject a manual-reference selection this account may not make.

    Two separate refusals, in order:

    * Selecting references at all is a founder/seeder capability — an ordinary
      creator who sends ids gets 403 rather than having them silently ignored,
      because silently ignoring them would produce an image that is not the one
      they asked for.
    * The ids themselves are then validated against the database (existence,
      this character, ACTIVE, selectable kind). Validating at submission means
      the founder learns immediately, instead of discovering it in a failed job.
    """
    if not body.reference_image_ids:
        return
    if not is_founder_account(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Selecting reference images is a founder tool.",
        )
    try:
        resolve_manual_references(
            db,
            character_id=character_id,
            image_ids=body.reference_image_ids,
            roles=[r for r in body.reference_roles],
        )
    except ManualReferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ── Synchronous route (preserved) ─────────────────────────────────────


@router.post(
    "/{character_id}/image-generator/generate",
    response_model=CharacterImageRead,
    summary="Generate an image synchronously (legacy; prefer the job routes)",
    dependencies=[Depends(require_creator)],
)
def generate_image(
    character_id: int,
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate one image and return it, blocking until the pipeline finishes.

    Behaviour is unchanged from before the pipeline was extracted — this is the
    same code path, now shared with the job runner. It stays because existing
    callers depend on it, but it is NOT the founder workflow: a generation that
    triggers face-verification retries can outlive the Cloud Run request
    deadline, and the client would lose an image it had already paid for. Use
    ``POST /{id}/image-generator/jobs`` for that.
    """
    character = _owned_character(db, character_id, current_user)

    # ── B22: Weekly allowance check (founders bypass; deducted on success) ──
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    _guard_manual_references(db, body=body, character_id=character_id, user=current_user)

    params = params_from_request(
        body,
        is_admin=user_is_admin(current_user),
        is_founder=is_founder_account(current_user),
    )
    try:
        image, _summary = run_image_generation(
            db, character=character, user=current_user, params=params
        )
    except ManualReferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return CharacterImageRead.model_validate(image)


# ── Async job routes (founder workflow) ───────────────────────────────


@router.post(
    "/{character_id}/image-generator/jobs",
    response_model=ImageGenerationJobView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an async image-generation job (founder/seeder)",
    dependencies=[Depends(require_founder)],
)
def submit_generation_job(
    character_id: int,
    body: ImageGenerateJobRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImageGenerationJobView:
    """Validate, create (or return the existing) job, respond immediately.

    The provider pipeline runs in a detached driver process; this request only
    writes the job row and launches the driver, so it always returns well inside
    the request deadline however long the generation takes.

    If a job already exists for this account and ``idempotency_key``, it is
    returned with ``reused=true`` — no new generation, no additional spend.
    """
    character = _owned_character(db, character_id, current_user)

    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    _guard_manual_references(db, body=body, character_id=character_id, user=current_user)

    params = params_from_request(
        body,
        is_admin=user_is_admin(current_user),
        is_founder=is_founder_account(current_user),
    )
    try:
        job, reused = _jobs.start_image_generation_job(
            db,
            character_id=character.id,
            user_id=current_user.id,
            params=params,
            idempotency_key=body.idempotency_key,
        )
    except _jobs.ImageGenerationJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    logger.info(
        "IMAGE_GEN_JOB_SUBMIT character_id=%s user_id=%s job=%s reused=%s status=%s refs=%d",
        character_id, current_user.id, job.public_id, reused, job.status,
        len(body.reference_image_ids),
    )
    return _job_to_view(db, job, reused=reused)


@router.get(
    "/{character_id}/image-generator/jobs/latest",
    response_model=ImageGenerationJobEnvelope,
    summary="Latest generation job for this character (refresh recovery)",
    dependencies=[Depends(require_founder)],
)
def latest_generation_job(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImageGenerationJobEnvelope:
    """Re-attach to the most recent generation this account started here.

    This is what makes a tablet survive a reconnect: the client reloads, asks
    for the latest job, and resumes polling — or collects a result that finished
    while it was away — without submitting anything.
    """
    _owned_character(db, character_id, current_user)
    job = _jobs.get_latest_job_for_character(
        db, user_id=current_user.id, character_id=character_id
    )
    if job is None:
        return ImageGenerationJobEnvelope(job=None)
    return ImageGenerationJobEnvelope(job=_job_to_view(db, job))


@router.get(
    "/{character_id}/image-generator/jobs/{public_id}",
    response_model=ImageGenerationJobView,
    summary="Poll one image-generation job",
    dependencies=[Depends(require_founder)],
)
def get_generation_job(
    character_id: int,
    public_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImageGenerationJobView:
    """Poll a job by its public id. Scoped to the submitting account."""
    _owned_character(db, character_id, current_user)
    job = _jobs.get_job_for_owner(db, user_id=current_user.id, public_id=public_id)
    if job is None or int(job.character_id) != int(character_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return _job_to_view(db, job)
