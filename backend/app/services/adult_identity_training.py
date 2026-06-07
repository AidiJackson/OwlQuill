"""Adult Studio training lifecycle + orchestration state machine (Phase 1, Sprint 4).

Governs the identity-model status transitions and the training-job records. This is
ORCHESTRATION ONLY — it creates/advances job + version rows and enforces legal state
transitions. It does NOT train, call any provider, launch RunPod, or generate images;
the actual training execution is a later concern that drives these functions.

Identity status state machine (allowed transitions only):
    prepared -> training
    training -> ready
    training -> failed
    ready    -> stale
    stale    -> prepared

Training job state machine:
    queued  -> running
    running -> completed
    running -> failed

Any other transition raises InvalidTransitionError.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import func

from app.models.adult_identity import (
    AdultIdentityMarkRender,  # noqa: F401  (kept for module cohesion / future use)
    AdultIdentityModel,
    AdultIdentityModelVersion,
    AdultIdentityTrainingJob,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class InvalidTransitionError(Exception):
    """Raised on an illegal identity or job state transition."""


class NotFoundError(Exception):
    """Raised when a referenced identity model or job does not exist."""


_IDENTITY_TRANSITIONS: dict[str, set[str]] = {
    "prepared": {"training"},
    "training": {"ready", "failed"},
    "ready": {"stale"},
    "stale": {"prepared"},
}
_JOB_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "canceled"},
    "running": {"completed", "failed", "canceled"},
}


def _check(transitions: dict[str, set[str]], current: str, new: str, kind: str) -> None:
    if new not in transitions.get(current, set()):
        raise InvalidTransitionError(f"illegal {kind} transition: {current} -> {new}")


def can_transition_identity(current: str, new: str) -> bool:
    return new in _IDENTITY_TRANSITIONS.get(current, set())


def can_transition_job(current: str, new: str) -> bool:
    return new in _JOB_TRANSITIONS.get(current, set())


# ── lookups ──────────────────────────────────────────────────────────────────

def _get_model(identity_id: int, db: "Session") -> AdultIdentityModel:
    model = db.get(AdultIdentityModel, identity_id)
    if model is None:
        raise NotFoundError(f"AdultIdentityModel {identity_id} not found")
    return model


def _get_job(job_id: int, db: "Session") -> AdultIdentityTrainingJob:
    job = db.get(AdultIdentityTrainingJob, job_id)
    if job is None:
        raise NotFoundError(f"AdultIdentityTrainingJob {job_id} not found")
    return job


# ── identity transitions (explicit lifecycle helpers) ────────────────────────

def mark_identity_stale(identity_id: int, db: "Session") -> AdultIdentityModel:
    """ready -> stale (canon moved under a trained model)."""
    model = _get_model(identity_id, db)
    _check(_IDENTITY_TRANSITIONS, model.status, "stale", "identity")
    model.status = "stale"
    db.commit()
    db.refresh(model)
    return model


def recover_stale_identity(identity_id: int, db: "Session") -> AdultIdentityModel:
    """stale -> prepared (re-prepared against current canon; ready to retrain)."""
    model = _get_model(identity_id, db)
    _check(_IDENTITY_TRANSITIONS, model.status, "prepared", "identity")
    model.status = "prepared"
    db.commit()
    db.refresh(model)
    return model


# ── training job lifecycle ───────────────────────────────────────────────────

def create_training_job(identity_id: int, db: "Session",
                        provider: str = "stub") -> AdultIdentityTrainingJob:
    """Queue a training job for a PREPARED identity. No external work is started."""
    model = _get_model(identity_id, db)
    if model.status != "prepared":
        raise InvalidTransitionError(
            f"identity {identity_id} must be 'prepared' to create a training job "
            f"(is '{model.status}')"
        )
    job = AdultIdentityTrainingJob(identity_id=identity_id, provider=provider, state="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def start_training_job(job_id: int, db: "Session") -> AdultIdentityTrainingJob:
    """queued -> running; identity prepared -> training."""
    job = _get_job(job_id, db)
    model = _get_model(job.identity_id, db)
    _check(_JOB_TRANSITIONS, job.state, "running", "job")
    _check(_IDENTITY_TRANSITIONS, model.status, "training", "identity")
    job.state = "running"
    job.started_at = datetime.utcnow()
    model.status = "training"
    db.commit()
    db.refresh(job)
    return job


def complete_training_job(
    job_id: int,
    db: "Session",
    *,
    lora_weights_uri: Optional[str] = None,
    base_model: Optional[str] = None,
    training_config: Optional[dict] = None,
    metrics: Optional[dict] = None,
) -> AdultIdentityTrainingJob:
    """running -> completed; identity training -> ready; create an active version.

    The new version records the model's current canon_fingerprint (what it was trained
    against) and becomes the active version; any prior active version is superseded.
    """
    job = _get_job(job_id, db)
    model = _get_model(job.identity_id, db)
    _check(_JOB_TRANSITIONS, job.state, "completed", "job")
    _check(_IDENTITY_TRANSITIONS, model.status, "ready", "identity")

    last_index = (
        db.query(func.max(AdultIdentityModelVersion.version_index))
        .filter(AdultIdentityModelVersion.identity_id == model.id)
        .scalar()
    ) or 0
    for prev in (
        db.query(AdultIdentityModelVersion)
        .filter(AdultIdentityModelVersion.identity_id == model.id,
                AdultIdentityModelVersion.state == "active")
        .all()
    ):
        prev.state = "superseded"

    version = AdultIdentityModelVersion(
        identity_id=model.id,
        version_index=last_index + 1,
        lora_weights_uri=lora_weights_uri,
        base_model=base_model or model.base_model,
        training_config_json=training_config,
        source_manifest_json=model.prepared_manifest_json,
        canon_fingerprint=model.canon_fingerprint,
        metrics_json=metrics,
        state="active",
    )
    db.add(version)
    db.flush()  # assign version.id

    model.active_version_id = version.id
    model.status = "ready"
    job.state = "completed"
    job.version_id = version.id
    job.finished_at = datetime.utcnow()

    db.commit()
    db.refresh(job)
    return job


def fail_training_job(job_id: int, reason: str, db: "Session") -> AdultIdentityTrainingJob:
    """running -> failed; identity training -> failed."""
    job = _get_job(job_id, db)
    model = _get_model(job.identity_id, db)
    _check(_JOB_TRANSITIONS, job.state, "failed", "job")
    _check(_IDENTITY_TRANSITIONS, model.status, "failed", "identity")
    job.state = "failed"
    job.error = reason
    job.finished_at = datetime.utcnow()
    model.status = "failed"
    model.last_error = reason
    db.commit()
    db.refresh(job)
    return job


# ── Provider-driven orchestration ─────────────────────────────────────────────

class AdultIdentityTrainingService:
    """Drives the Sprint 4 lifecycle through a pluggable TrainingProvider.

    The provider is OPTIONAL: with no provider the service still creates/starts a local
    job (lifecycle-only). With a provider, submit/poll/cancel are mediated through the
    provider seam — which, in tests, is the in-memory FakeTrainingProvider (no external
    calls, no GPU, no spend). No real provider is invoked by this class.
    """

    def __init__(self, db: "Session", provider=None) -> None:
        self.db = db
        self.provider = provider

    def submit(self, identity_id: int, *, base_model: Optional[str] = None,
               training_config: Optional[dict] = None) -> AdultIdentityTrainingJob:
        """Create + start a training job, recording the provider's job id/cost."""
        model = _get_model(identity_id, self.db)
        provider_name = getattr(self.provider, "name", None) or "stub"
        job = create_training_job(identity_id, self.db, provider=provider_name)

        if self.provider is not None:
            pj = self.provider.create_training_job(
                identity_id=identity_id,
                trigger_token=model.trigger_token,
                base_model=base_model or model.base_model,
                training_config=training_config,
                source_manifest=model.prepared_manifest_json,
            )
            job.external_job_id = pj.provider_job_id
            job.cost_usd = pj.cost_estimate
            self.db.commit()

        start_training_job(job.id, self.db)
        self.db.refresh(job)
        return job

    def poll(self, job_id: int) -> AdultIdentityTrainingJob:
        """Poll the provider and apply the outcome to the lifecycle."""
        from app.services.adult_identity_provider import ProviderStatus

        job = _get_job(job_id, self.db)
        if self.provider is None or not job.external_job_id:
            return job

        pj = self.provider.poll_training_job(job.external_job_id)
        if pj.status == ProviderStatus.COMPLETED:
            complete_training_job(
                job.id, self.db,
                lora_weights_uri=pj.model_artifact_uri,
                base_model=getattr(self.provider, "base_model", None),
            )
            job = _get_job(job_id, self.db)
            if pj.cost_estimate is not None:
                job.cost_usd = pj.cost_estimate
                self.db.commit()
        elif pj.status == ProviderStatus.FAILED:
            fail_training_job(job.id, pj.error or "provider reported failure", self.db)
        # RUNNING / SUBMITTED → no state change yet.
        return _get_job(job_id, self.db)

    def cancel(self, job_id: int) -> AdultIdentityTrainingJob:
        """Cancel a job via the provider; mark the local job canceled."""
        job = _get_job(job_id, self.db)
        if self.provider is not None and job.external_job_id:
            self.provider.cancel_training_job(job.external_job_id)
        _check(_JOB_TRANSITIONS, job.state, "canceled", "job")
        job.state = "canceled"
        job.finished_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job
