"""Adult Studio (18+) admin diagnostics + readiness — read-only operational visibility.

Admin-only. Exposes WHY a character's Adult Studio identity is in its current
lifecycle state (prepared / stale / training / ready / failed): fingerprints,
versions, training jobs, mark-render routes, last error, and — for stale models —
the current-vs-trained canon fingerprint comparison. Also exposes a training-readiness
check (locked-canon preconditions + prepared state + per-mark references).

Strictly read-only: no writes, no provider construction, no training, no generation,
no Canon Studio writes. SEPARATE from the Canon Studio admin surface.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.admin import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.storage import file_path_to_url, load_image_bytes, save_image
from app.models.adult_identity import (
    AdultIdentityModel,
    AdultIdentityTrainingJob,
)
from app.models.character import Character as CharacterModel
from app.models.character_image import ImageKindEnum, ImageStatusEnum
from app.models.user import User
from app.schemas.character_image import CharacterImageCreate
from app.services.character_visual import create_character_image
from app.services.providers.replicate_provider import (
    ReplicateImg2ImgError,
    get_replicate_img2img_provider,
)
from app.services.adult_identity_diagnostics import build_diagnostics
from app.services.adult_founder_job_service import (
    cancel_job,
    get_latest_job,
    start_founder_job,
)
from app.services.adult_identity_founder_generate import (
    SUMMER_CHARACTER_ID,
    FounderGenerateBlocked,
)
from app.services.adult_identity_provider import get_training_provider
from app.services.adult_identity_readiness import build_readiness
from app.services.adult_identity_training import (
    AdultIdentityTrainingService,
    NotFoundError,
)

router = APIRouter()

logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────


class AdultStudioMarkRouteDiag(BaseModel):
    canon_mark_id: str
    mark_type: Optional[str] = None
    body_region: Optional[str] = None
    side: Optional[str] = None
    route: str
    reason: Optional[str] = None
    mark_fingerprint: Optional[str] = None


class AdultStudioVersionDiag(BaseModel):
    id: int
    version_index: int
    state: str
    canon_fingerprint: Optional[str] = None
    lora_weights_uri: Optional[str] = None
    created_at: Optional[str] = None


class FingerprintComparison(BaseModel):
    current_fingerprint: Optional[str] = None
    trained_fingerprint: Optional[str] = None
    mismatch: bool = False


class AdultStudioDiagnosticsResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    character_id: int
    exists: bool
    status: Optional[str] = None
    model_status: Optional[str] = None
    stale: bool = False
    canon_fingerprint: Optional[str] = None
    active_version_id: Optional[int] = None
    version_count: int = 0
    training_job_count: int = 0
    mark_render_count: int = 0
    last_error: Optional[str] = None
    trigger_token: Optional[str] = None
    provider: Optional[str] = None
    base_model: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    mark_routes: list[AdultStudioMarkRouteDiag] = []
    versions: list[AdultStudioVersionDiag] = []
    fingerprint_comparison: FingerprintComparison = FingerprintComparison()


# ── Endpoint ───────────────────────────────────────────────────────────────


@router.get(
    "/characters/{character_id}/diagnostics",
    response_model=AdultStudioDiagnosticsResponse,
    summary="Admin: read-only Adult Studio identity diagnostics for a character",
)
def get_adult_studio_diagnostics(
    character_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the diagnostics payload. 404 only if the character itself is missing."""
    character = db.get(CharacterModel, character_id)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Character not found."
        )
    _ = admin  # admin identity already enforced by the dependency
    return build_diagnostics(character_id, db)


# ── Readiness ────────────────────────────────────────────────────────────────


class ReadinessChecks(BaseModel):
    face_locked: bool
    body_locked: bool
    identity_exists: bool
    fingerprint_exists: bool
    mark_references_exist: bool
    routes_resolved: bool
    not_stale: bool
    status_trainable: bool


class AdultStudioReadinessResponse(BaseModel):
    character_id: int
    ready_to_train: bool
    status: Optional[str] = None
    stale: bool = False
    blocking_reasons: list[str] = []
    checks: ReadinessChecks
    canon_mark_count: int = 0
    mark_render_count: int = 0
    unreferenced_marks: list[str] = []


@router.get(
    "/characters/{character_id}/readiness",
    response_model=AdultStudioReadinessResponse,
    summary="Admin: read-only Adult Studio training-readiness check for a character",
)
def get_adult_studio_readiness(
    character_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return ready_to_train + blocking_reasons. 404 only if the character is missing."""
    character = db.get(CharacterModel, character_id)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Character not found."
        )
    _ = admin  # admin identity already enforced by the dependency
    return build_readiness(character_id, db)


# ── Admin-triggered training workflow (Phase 3, Sprint 2) ─────────────────────
#
# A REAL training workflow that stays fully behind the feature flags. With the
# defaults (ADULT_STUDIO_TRAINING_ENABLED=false, ADULT_STUDIO_PROVIDER=disabled)
# every entry point returns 409 BEFORE any provider is constructed — so the
# disabled path cannot reach a provider, cannot call Replicate, and cannot spend
# money. The provider is constructed ONLY after admin + flag + readiness gates
# all pass. Nothing here generates images or runs inference; it drives the
# existing identity training lifecycle (create job → submit → poll → version).


class AdultStudioTrainingJobStatus(BaseModel):
    model_config = {"protected_namespaces": ()}

    job_id: int
    identity_id: int
    character_id: int
    provider: str
    state: str
    external_job_id: Optional[str] = None
    cost_usd: Optional[float] = None
    version_id: Optional[int] = None
    error: Optional[str] = None
    identity_status: Optional[str] = None


def _job_status_payload(
    job: AdultIdentityTrainingJob, db: Session
) -> AdultStudioTrainingJobStatus:
    model = db.get(AdultIdentityModel, job.identity_id)
    return AdultStudioTrainingJobStatus(
        job_id=job.id,
        identity_id=job.identity_id,
        character_id=model.character_id if model else 0,
        provider=job.provider,
        state=job.state,
        external_job_id=job.external_job_id,
        cost_usd=job.cost_usd,
        version_id=job.version_id,
        error=job.error,
        identity_status=model.status if model else None,
    )


def _provider_configured() -> bool:
    """True only when a non-disabled provider is selected (does NOT construct it)."""
    selected = (settings.ADULT_STUDIO_PROVIDER or "disabled").strip().lower()
    return selected not in ("", "disabled")


@router.post(
    "/characters/{character_id}/train",
    response_model=AdultStudioTrainingJobStatus,
    summary="Admin: start real Adult Studio identity training (gated; disabled by default)",
)
def train_adult_studio_identity(
    character_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-triggered training. Gates, in order, BEFORE constructing a provider:

    admin (dependency) → character exists → training enabled → provider configured →
    readiness (``ready_to_train``) → identity is 'prepared'. Only then is the provider
    constructed and the job submitted. Disabled by default → 409, no provider, no spend.
    """
    _ = admin  # admin identity already enforced by the dependency
    character = db.get(CharacterModel, character_id)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Character not found."
        )

    # ── Feature gates (no provider constructed past here on failure) ──────────
    if not settings.ADULT_STUDIO_TRAINING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adult Studio training is disabled in this environment.",
        )
    if not _provider_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Adult Studio training provider is configured.",
        )

    # ── Readiness gate ───────────────────────────────────────────────────────
    readiness = build_readiness(character_id, db)
    if not readiness["ready_to_train"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "not_ready_to_train",
                "blocking_reasons": readiness["blocking_reasons"],
            },
        )

    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if model is None or model.status != "prepared":
        # Readiness already guards this; kept as a defensive backstop.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity must be 'prepared' to train.",
        )

    # ── Construct provider ONLY now (all gates passed) ───────────────────────
    provider = get_training_provider(settings)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adult Studio training provider could not be constructed.",
        )

    service = AdultIdentityTrainingService(db, provider=provider)
    job = service.submit(model.id, base_model=model.base_model)
    return _job_status_payload(job, db)


@router.post(
    "/training-jobs/{job_id}/poll",
    response_model=AdultStudioTrainingJobStatus,
    summary="Admin: poll a training job; advance lifecycle / create version on completion",
)
def poll_adult_studio_training_job(
    job_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Poll the configured provider for a job and apply the outcome to the lifecycle.

    Requires training enabled + a configured provider (409 otherwise). On COMPLETED the
    existing lifecycle creates the active version and records cost; on FAILED it marks the
    identity/job failed. No generation, no inference.
    """
    _ = admin  # admin identity already enforced by the dependency
    job = db.get(AdultIdentityTrainingJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Training job not found."
        )

    if not settings.ADULT_STUDIO_TRAINING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adult Studio training is disabled in this environment.",
        )
    if not _provider_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Adult Studio training provider is configured.",
        )

    provider = get_training_provider(settings)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adult Studio training provider could not be constructed.",
        )

    service = AdultIdentityTrainingService(db, provider=provider)
    try:
        job = service.poll(job_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Training job not found."
        )
    return _job_status_payload(job, db)


# ── Founder Async Lite generate (Phase 3, Sprint 13) — Summer-only ─────────────
#
# Fire-and-poll. POST launches ONE detached RunPod masked-diffusion job (active LoRA +
# DB enforcement plan + both Summer tattoo routes) and returns 202 {job_id, state}; the
# real final image is the RunPod 99_final — NOT the diagnostic montage, NOT the OpenAI
# gpt-image path. GET reconciles/polls the job. One active founder job at a time.
# Admin-only (require_admin), Summer-only (id=60), hard $0.05 spend cap (driver carries
# the proof_lib profile), manual_review_required always true.


class FounderGenerateRequest(BaseModel):
    prompt: str


class FounderJobResponse(BaseModel):
    """A founder async job snapshot (state machine: queued|running|completed|failed)."""
    job_id: int
    character_id: int
    state: str
    run_id: str
    final_image_url: Optional[str] = None
    intermediate_artifact_urls: list[str] = []
    cost: float = 0.0
    runtime: float = 0.0
    routes_executed: list[dict] = []
    manual_review_required: bool = True
    blocking_reasons: list[str] = []
    orphaned_workers: list[str] = []
    error: Optional[str] = None


class FounderJobEnvelope(BaseModel):
    """GET wrapper — ``job`` is null when no founder job has ever been started."""
    job: Optional[FounderJobResponse] = None


def _job_payload(job) -> FounderJobResponse:
    result = job.result_json or {}
    return FounderJobResponse(
        job_id=job.id,
        character_id=job.character_id,
        state=job.state,
        run_id=job.run_id,
        final_image_url=job.final_image_url,
        intermediate_artifact_urls=result.get("intermediate_artifact_urls", []),
        cost=result.get("cost", 0.0),
        runtime=result.get("runtime", 0.0),
        routes_executed=result.get("routes_executed", []),
        manual_review_required=result.get("manual_review_required", True),
        blocking_reasons=result.get("blocking_reasons", []),
        orphaned_workers=result.get("orphaned_workers", []),
        error=job.error,
    )


# ── Replicate experimental img2img provider — admin-only test (Sprint E9) ──────
#
# An EXPERIMENTAL fourth Adult Studio provider. Takes an existing canon source image
# and runs PURE image-to-image through Replicate (no mask, no compositing, no editor
# job, no LoRA). It does NOT replace the OpenAI/Gemini/Grok paths. Admin-only and
# constructed ONLY after the admin gate + a configured REPLICATE_API_TOKEN — an
# unconfigured environment never reaches a network call.

# The fixed acceptance prompt from the spike spec (used when the request omits one).
_REPLICATE_TEST_PROMPT = (
    "Summer sunbathing topless on a private beach, same face, same tattoos, "
    "same body, photorealistic."
)


class ReplicateTestRequest(BaseModel):
    """Optional overrides for the admin Replicate test (sensible defaults otherwise)."""
    prompt: Optional[str] = None
    strength: Optional[float] = None


class ReplicateTestResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    image_url: str
    provider: str
    model_ref: str
    source_role: str
    prompt: str
    strength: float
    library_image_id: Optional[int] = None


def _pick_source_ref(manifest: dict) -> tuple[str, str]:
    """Choose the best canon source image (role, url) for img2img.

    Prefers a front body view (best for a full-figure scene), then any body ref, then
    a face ref, then the first available ref. Raises if the manifest has no refs.
    """
    refs = manifest.get("refs") or []
    by_role = {r.get("role"): r.get("url") for r in refs if r.get("url")}
    if "body_front" in by_role:
        return "body_front", by_role["body_front"]
    for r in refs:
        role, url = r.get("role", ""), r.get("url")
        if url and role.startswith("body"):
            return role, url
    for r in refs:
        role, url = r.get("role", ""), r.get("url")
        if url and role.startswith("face"):
            return role, url
    for r in refs:
        if r.get("url"):
            return r.get("role", "ref"), r["url"]
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="No canon source image is available for the Replicate test.",
    )


@router.post(
    "/characters/{character_id}/replicate-test",
    response_model=ReplicateTestResponse,
    summary="Admin: experimental Replicate img2img test (source image → provider → library)",
)
def replicate_test_adult_studio(
    character_id: int,
    body: ReplicateTestRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Run the experimental Replicate img2img provider on a canon source image.

    Gates, in order, BEFORE any provider/network call: admin (dependency) →
    character exists → identity prepared (manifest present) → prompt safety →
    REPLICATE_API_TOKEN configured. Then: pick a canon source image → img2img →
    save the result to the image library. Pure image-to-image; no mask/compositing.
    """
    _ = admin  # admin identity already enforced by the dependency
    character = db.get(CharacterModel, character_id)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Character not found."
        )

    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if model is None or model.status not in ("prepared", "ready", "stale"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prepare the 18+ Studio identity for this character first.",
        )

    manifest = model.prepared_manifest_json or {}
    prompt = (body.prompt or _REPLICATE_TEST_PROMPT).strip()

    # Safety gate — block minors/illegal even for the admin test path.
    from app.services import adult_studio as svc
    block_reason = svc.check_prompt_safety(prompt)
    if block_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=block_reason)

    source_role, source_url = _pick_source_ref(manifest)
    try:
        source_bytes = load_image_bytes(source_url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not load canon source image: {exc}",
        )

    # Construct the provider ONLY now (requires REPLICATE_API_TOKEN).
    try:
        provider = get_replicate_img2img_provider(settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Replicate provider not configured: {exc}",
        )

    try:
        png, model_ref = provider.img2img(
            source_image_bytes=source_bytes, prompt=prompt, strength=body.strength,
        )
    except ReplicateImg2ImgError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Replicate img2img failed: {exc}",
        )

    if not png or len(png) < 1000:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Replicate returned an empty image.",
        )

    # Save to the image library (same path as other library images).
    file_path = save_image(png)
    image = create_character_image(
        db, character_id,
        CharacterImageCreate(
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            file_path=file_path,
            provider="replicate_nsfw",
            prompt_summary=prompt[:80],
            metadata_json={
                "library": True,
                "prompt": prompt,
                "adult_studio": True,
                "provider": "replicate_nsfw",
                "model_ref": model_ref,
                "source_role": source_role,
                "experimental": True,
            },
        ),
    )
    image.user_id = character.owner_id
    db.commit()
    db.refresh(image)

    strength_used = float(
        settings.ADULT_STUDIO_REPLICATE_STRENGTH if body.strength is None else body.strength
    )
    logger.info(
        "adult_studio replicate-test character_id=%s model=%s source=%s bytes=%d image_id=%s",
        character_id, model_ref, source_role, len(png), image.id,
    )
    return ReplicateTestResponse(
        image_url=file_path_to_url(file_path),
        provider="replicate_nsfw",
        model_ref=model_ref,
        source_role=source_role,
        prompt=prompt,
        strength=strength_used,
        library_image_id=image.id,
    )


@router.post(
    "/characters/{character_id}/founder-generate",
    response_model=FounderJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Admin/founder: launch a Summer-only async Generate job (returns 202)",
)
def founder_generate_adult_studio(
    character_id: int,
    body: FounderGenerateRequest,
    response: Response,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Launch ONE detached founder generation job and return 202 {job_id, state}.

    Gates (all BEFORE any pod is launched → no spend on refusal): admin (dependency) →
    Summer-only (id=60) → prompt required → identity 'ready' with an active version →
    prompt safety (minors/illegal blocked) → singleton (409 if a job is already active).
    """
    _ = admin  # admin identity already enforced by the dependency
    try:
        job = start_founder_job(db, character_id, body.prompt)
    except FounderGenerateBlocked as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    # A failed launch is reported in-band (state=failed) but still a created job.
    response.status_code = status.HTTP_202_ACCEPTED
    return _job_payload(job)


@router.get(
    "/characters/{character_id}/founder-job",
    response_model=FounderJobEnvelope,
    summary="Admin/founder: poll the latest Summer founder job (reconciles running→terminal)",
)
def get_founder_job(
    character_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the latest founder job (or null). Reconciles a running job from its report."""
    _ = admin
    if character_id != SUMMER_CHARACTER_ID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Founder generate is Summer-only (character_id={SUMMER_CHARACTER_ID}).")
    job = get_latest_job(db, character_id)
    return FounderJobEnvelope(job=_job_payload(job) if job else None)


@router.post(
    "/characters/{character_id}/founder-job/cancel",
    response_model=FounderJobResponse,
    summary="Admin/founder: cancel the active Summer founder job (terminate pod + fail)",
)
def cancel_founder_job(
    character_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Cancel the active founder job: best-effort terminate its pod and mark it failed."""
    _ = admin
    if character_id != SUMMER_CHARACTER_ID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Founder generate is Summer-only (character_id={SUMMER_CHARACTER_ID}).")
    try:
        job = cancel_job(db, character_id)
    except FounderGenerateBlocked as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return _job_payload(job)
