"""Adult Studio (18+) admin diagnostics + readiness — read-only operational visibility.

Admin-only. Exposes WHY a character's Adult Studio identity is in its current
lifecycle state (prepared / stale / training / ready / failed): fingerprints,
versions, training jobs, mark-render routes, last error, and — for stale models —
the current-vs-trained canon fingerprint comparison. Also exposes a training-readiness
check (locked-canon preconditions + prepared state + per-mark references).

Strictly read-only: no writes, no provider construction, no training, no generation,
no Canon Studio writes. SEPARATE from the Canon Studio admin surface.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.admin import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.adult_identity import (
    AdultIdentityModel,
    AdultIdentityTrainingJob,
)
from app.models.character import Character as CharacterModel
from app.models.user import User
from app.services.adult_identity_diagnostics import build_diagnostics
from app.services.adult_identity_provider import get_training_provider
from app.services.adult_identity_readiness import build_readiness
from app.services.adult_identity_training import (
    AdultIdentityTrainingService,
    NotFoundError,
)

router = APIRouter()


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
