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

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.storage import load_image_bytes
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
from app.services.manual_references import (
    REFERENCE_MODE_AUGMENT,
    REFERENCE_MODE_DELIBERATE,
    ManualReferenceError,
    board_is_self_describing,
    build_reference_notes,
    has_ambiguous_refinement_subject,
    parse_role,
    resolve_manual_references,
)
from app.services.reference_isolation import (
    IsolationError,
    isolate as isolate_reference,
    should_isolate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Retained because the test suite repoints it alongside the other route modules
# that write generated media (see tests/conftest.py::generated_media_dir).
_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"


# ── Request schemas ───────────────────────────────────────────────────


#: Mirror of app.services.manual_references.ReferenceRole. The first five are
#: what /images offers and compile exactly as they always have; the rest are the
#: Admin Creator vocabulary and only carry meaning under deliberate mode.
ReferenceRoleLiteral = Literal[
    "character_appearance",
    "character_1",
    "character_2",
    "clothing",
    "environment",
    "tattoo_mark",
    "pose_composition",
    # Attribute-authority roles: evidence for one named feature, never for
    # identity. Admin Creator / deliberate mode only — under augment they
    # compile to nothing, exactly like the roles above them.
    "eyes",
    "nose",
    "mouth_lips",
    "face_shape",
    "eyebrows",
    "hair",
    "facial_hair",
    "skin_complexion",
    "other",
    "unspecified",
]

#: What grounds this generation. "augment" is the long-standing canon-driven
#: policy and the default for every caller that does not name a mode.
#: "deliberate" is Admin Creator's reference-driven policy: the hand-picked
#: cards and the prompt are the only inputs, canon is bypassed entirely, and the
#: selected character owns the result without contributing to it. See
#: app.services.manual_references and the pipeline's canon bypass.
ReferenceModeLiteral = Literal["augment", "deliberate"]


class ImageGenerateRequest(BaseModel):
    """Request body for the generate routes."""

    # May be EMPTY, but only for an Admin Creator board that already states a
    # complete operation — enforced in _validate_prompt_presence, not here,
    # because the decision depends on the reference roles and this field cannot
    # see them. Every other caller (including /images) is still refused an empty
    # prompt, exactly as when this was min_length=1.
    prompt: str = Field(..., min_length=0, max_length=800)
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
    # Which merge policy applies to those references. Absent for every existing
    # caller — including the Image Generator on /images — which is why the
    # default is the unchanged canon-first behaviour. Only Admin Creator sends
    # "deliberate", and only a founder/seeder may (enforced below).
    reference_mode: ReferenceModeLiteral = REFERENCE_MODE_AUGMENT


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
    #: Optional since Phase 4C: a job outlives the character it ran for, so
    #: the record of who requested a generation survives the association.
    character_id: Optional[int] = None
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

    Three separate refusals, in order:

    * Asking for a non-default reference mode is a founder/seeder capability.
      Checked FIRST and independently of whether any ids were sent, because
      ``reference_mode`` changes how canon references are budgeted even on its
      own — it is not merely a modifier on a selection.
    * Selecting references at all is a founder/seeder capability — an ordinary
      creator who sends ids gets 403 rather than having them silently ignored,
      because silently ignoring them would produce an image that is not the one
      they asked for.
    * The ids themselves are then validated against the database (existence,
      this character, ACTIVE, selectable kind). Validating at submission means
      the founder learns immediately, instead of discovering it in a failed job.
    """
    if getattr(body, "reference_mode", REFERENCE_MODE_AUGMENT) != REFERENCE_MODE_AUGMENT:
        if not is_founder_account(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Deliberate reference mode is a founder tool.",
            )
    if not body.reference_image_ids:
        # No cards means nothing can describe the generation but the prompt.
        _validate_prompt_presence(body, [])
        return
    if not is_founder_account(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Selecting reference images is a founder tool.",
        )
    try:
        resolved = resolve_manual_references(
            db,
            character_id=character_id,
            image_ids=body.reference_image_ids,
            roles=[r for r in body.reference_roles],
        )
    except ManualReferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    _validate_refinement_subject(body, resolved)
    _validate_prompt_presence(body, resolved)


def _validate_refinement_subject(body, resolved: list) -> None:
    """Refuse a feature change that has no single starting image.

    Deliberate mode only. Under ``augment`` the feature roles compile to nothing
    at all, so the board carries no change instruction to be ambiguous about and
    /images keeps its existing behaviour exactly.

    See ``has_ambiguous_refinement_subject`` for why this is refused rather than
    resolved.
    """
    if getattr(body, "reference_mode", REFERENCE_MODE_AUGMENT) != REFERENCE_MODE_DELIBERATE:
        return
    if not has_ambiguous_refinement_subject([r.role for r in resolved]):
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "Feature refinement needs a single current Person A image. This board "
            "has more than one Character 1 reference, so there is no one starting "
            "image to change. Keep the most recent Character 1 card and remove the "
            "others, or drop the feature references to generate a scene instead."
        ),
    )


def _validate_prompt_presence(body, resolved: list) -> None:
    """Refuse a blank prompt unless the board itself states the operation.

    Two independent conditions, both required — the shape check alone would be
    a rule about roles, and this needs to be a guarantee about what the provider
    actually receives:

    1. the board is a self-describing shape (feature roles, or Person A with a
       pose), and
    2. compiling it actually yields reference instructions.

    (2) is what makes an empty compiled prompt unreachable rather than merely
    unlikely. It re-runs the real compiler, so it cannot drift from what the
    pipeline will send.

    Deliberate mode only. /images sends augment, where the Admin Creator roles
    compile to nothing at all, so a blank prompt there is refused exactly as it
    always was.
    """
    if body.prompt.strip():
        return

    mode = getattr(body, "reference_mode", REFERENCE_MODE_AUGMENT)
    roles = [r.role for r in resolved]
    if (
        mode == REFERENCE_MODE_DELIBERATE
        and resolved
        and board_is_self_describing(roles)
        and build_reference_notes(
            resolved,
            canon_ref_count=0,
            canon_grounded=False,
            refs_before_manual=0,
            mode=REFERENCE_MODE_DELIBERATE,
        ).strip()
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "Describe what you want generated. A prompt is optional only when "
            "the reference cards already state the change — a Character 1 card "
            "with feature references, feature references on their own, or "
            "Character 1 with a pose reference."
        ),
    )


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
    # ``job.character_id`` may be NULL since 4C (its character was deleted).
    # Compare without coercing — ``int(None)`` raises — and a job with no
    # character is correctly not found under a character-scoped route.
    if job is None or job.character_id != character_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return _job_to_view(db, job)


# ── Isolation preview ─────────────────────────────────────────────────


@router.get(
    "/{character_id}/image-generator/references/{image_id}/isolated",
    summary="Preview what the provider actually receives for a feature reference",
    dependencies=[Depends(require_founder)],
)
def preview_isolated_reference(
    character_id: int,
    image_id: int,
    role: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Re-derive one feature reference and return it as an image.

    "Original → what the model receives", answered by running the SAME
    deterministic transform generation runs. Nothing is persisted: there is no
    derived CharacterImage, no cache and no second copy of anyone's photograph
    — the bytes are computed on request and discarded. That is the whole reason
    the transform has to be deterministic.

    Access is the founder gate plus the ordinary ownership checks: the character
    must be this account's, and ``resolve_manual_references`` re-validates that
    the image belongs to that character and is a selectable kind — the same
    validation a generation submission passes. A founder therefore cannot
    preview an image they could not already have selected as a reference.
    """
    _owned_character(db, character_id, current_user)
    try:
        parsed = parse_role(role)
    except ManualReferenceError as exc:
        # An unrecognised role is a client bug, not a server fault — without
        # this it escaped as a 500.
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not should_isolate(parsed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That reference type is not isolated.",
        )
    try:
        resolved = resolve_manual_references(
            db, character_id=character_id, image_ids=[image_id], roles=[role]
        )
    except ManualReferenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    try:
        derived = isolate_reference(load_image_bytes(resolved[0].file_path), parsed)
    except IsolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"This reference could not be safely isolated. {exc.reason}",
        ) from exc

    return Response(
        content=derived,
        media_type="image/png",
        # Never cached: it is a derived view of someone's photograph, and the
        # transform may change with the derivation version.
        headers={"Cache-Control": "no-store"},
    )
