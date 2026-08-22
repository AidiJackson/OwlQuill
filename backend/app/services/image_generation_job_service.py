"""Image-generation ASYNC JOBS — fire-and-poll for the founder image workflow.

Mirrors the proven detached-driver pattern (identity_pack_job_service.py /
editor_job_service.py): :func:`start_image_generation_job` creates a job row and
launches ONE detached driver process (scripts/image_generation_job_driver.py),
returning immediately. The driver calls :func:`run_image_generation_job`, which
executes the existing pipeline (image_generation_pipeline.run_image_generation)
unchanged and writes status/result to the job row. The client polls the row.

Why the interactive generator became async
------------------------------------------
The published deployment target is Cloud Run (``.replit`` →
``deploymentTarget = "cloudrun"``), which enforces a request deadline. The
pipeline can legitimately issue four provider calls in one intent — first pass,
two escalated face-verification retries (``IDENTITY_FACE_VERIFY_MAX_RETRIES=2``),
and one cover-composition retry — each bounded by ``GOOGLE_IMAGE_TIMEOUT_S``
(180s). That is up to ~12 minutes inside one HTTP request. A tablet on mobile
data loses that request long before it completes, and it loses it AFTER the
provider has been paid. Reducing the verification retries to fit the deadline
was explicitly rejected: identity quality is the point of the feature.

Duplicate protection — the paid-spend guarantee
-----------------------------------------------
``idempotency_key`` is REQUIRED here (the route rejects a submission without
one) and is enforced by the unique index ``ux_image_generation_jobs_idem`` on
(user_id, idempotency_key):

* An identical resubmission — double-tap, browser retry, proxy retry, reconnect,
  refresh-and-resend — returns the EXISTING job with ``reused=True``. No second
  row, no second driver, no second provider call.
* The uniqueness is not conditional on status: a COMPLETED or FAILED job keeps
  its key reserved, so a retry after either outcome re-attaches to the original
  result instead of buying a new image. Generating again is a deliberate act —
  the client mints a NEW key for it.
* A lost insert race resolves the same way: the loser gets IntegrityError and is
  handed the winner's job.

Recovery policy (explicit — single-process Replit deployment)
-------------------------------------------------------------
The driver is a detached OS process (``start_new_session=True``): it survives a
uvicorn dev reload, but NOT a container restart/redeploy. Stale jobs are
reconciled at poll time rather than pretending to survive:

* ``queued`` with no start after LAUNCH_TIMEOUT_S        → failed (launch_timeout)
* ``running`` with a heartbeat older than STALL_TIMEOUT_S → failed (stalled)
* any active job older than HARD_TIMEOUT_S                → failed (timeout)

No automatic re-run — retry is a user action with a new key, so a dead driver
can never cause duplicate paid provider calls.

All side effects (launcher, session factory, pipeline, clock) are injectable so
tests run with zero subprocesses, zero spend and zero live providers.
"""
from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.image_generation_job import (
    IMAGE_GENERATION_JOB_ACTIVE_STATES,
    ImageGenerationJob,
)
from app.services.image_generation_pipeline import GenerationParams

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = _REPO_ROOT / "scripts"
DRIVER_PATH = SCRIPTS_DIR / "image_generation_job_driver.py"
DRIVER_LOG_DIR = SCRIPTS_DIR / "image_generation_job_logs"

# Stale-job reconciliation thresholds (seconds).
#
# STALL_TIMEOUT_S must exceed the pipeline's worst-case UNINTERRUPTED provider
# stretch, because the heartbeat only advances at stage boundaries: one Google
# call is bounded by GOOGLE_IMAGE_TIMEOUT_S (180s) and face verification can
# chain three of them back to back before the next boundary. 900s leaves margin
# without letting a genuinely dead driver hang around.
LAUNCH_TIMEOUT_S = 180
STALL_TIMEOUT_S = 900
HARD_TIMEOUT_S = 1800

_SAFE_STALE_MESSAGE = (
    "This generation was interrupted before it could finish. "
    "Nothing further was charged — you can safely try again."
)
_SAFE_FAILURE_MESSAGE = "We couldn't generate that image right now. Please try again."

#: Maximum length of a client-supplied idempotency key (matches the column).
MAX_IDEMPOTENCY_KEY_LEN = 64


class ImageGenerationJobError(Exception):
    """Service-level job failure with an HTTP status hint for the route."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Injected side effects ───────────────────────────────────────────────────


def _default_launcher(job_public_id: str, job_id: int) -> None:
    """Spawn the detached image-generation driver; returns once it starts."""
    from app.services.detached_driver import spawn_detached_driver

    spawn_detached_driver(
        driver_path=DRIVER_PATH,
        log_dir=DRIVER_LOG_DIR,
        log_name=job_public_id,
        extra_env={"IMAGE_GENERATION_JOB_ID": str(job_id)},
        cwd=_REPO_ROOT,
    )
    logger.info("image_generation_job launched public_id=%s job_id=%s", job_public_id, job_id)


# ── Public API: submission ──────────────────────────────────────────────────


def get_job_by_key(
    db: "Session", *, user_id: int, idempotency_key: str
) -> Optional[ImageGenerationJob]:
    """The job already owning this (user, intent key), if any."""
    return (
        db.query(ImageGenerationJob)
        .filter(
            ImageGenerationJob.user_id == user_id,
            ImageGenerationJob.idempotency_key == idempotency_key,
        )
        .order_by(ImageGenerationJob.id.desc())
        .first()
    )


def start_image_generation_job(
    db: "Session",
    *,
    character_id: int,
    user_id: int,
    params: GenerationParams,
    idempotency_key: str,
    launcher: Optional[Callable[[str, int], None]] = None,
) -> tuple[ImageGenerationJob, bool]:
    """Create + launch ONE detached generation job.

    Returns ``(job, reused)``. ``reused=True`` means NO new generation was
    started and nothing further will be spent — the caller is being handed the
    job that already owns this intent key.

    Ownership and entitlement must already be validated by the route; ``params``
    must already be sanitised (its ``is_admin``/``is_founder`` fields come from
    the account, never from the client).
    """
    launcher = launcher or _default_launcher

    key = (idempotency_key or "").strip()
    if not key:
        raise ImageGenerationJobError(
            422,
            "An idempotency key is required so a retry cannot start a second "
            "paid generation.",
        )
    if len(key) > MAX_IDEMPOTENCY_KEY_LEN:
        raise ImageGenerationJobError(
            422, f"Idempotency key must be at most {MAX_IDEMPOTENCY_KEY_LEN} characters."
        )

    # THE spend guard: this intent already has a job, in any state. Hand it back.
    existing = get_job_by_key(db, user_id=user_id, idempotency_key=key)
    if existing is not None:
        logger.info(
            "image_generation_job reused public_id=%s status=%s (idempotent resubmit)",
            existing.public_id, existing.status,
        )
        return existing, True

    job = ImageGenerationJob(
        public_id=uuid.uuid4().hex,
        user_id=user_id,
        character_id=character_id,
        status="queued",
        stage="queued",
        progress_message="Waiting to start…",
        idempotency_key=key,
        params_json=params.to_json(),
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # Lost the insert race — the unique index guarantees the winner exists.
        db.rollback()
        winner = get_job_by_key(db, user_id=user_id, idempotency_key=key)
        if winner is not None:
            return winner, True
        raise ImageGenerationJobError(
            409, "That generation was just submitted. Please refresh."
        ) from None
    db.refresh(job)

    try:
        launcher(job.public_id, job.id)
    except Exception as exc:  # noqa: BLE001 — a launch failure must not strand the job
        job.status = "failed"
        job.error_code = "launch_failed"
        job.error_message = _SAFE_FAILURE_MESSAGE
        job.diag_json = {"launch_error": repr(exc)[:500]}
        job.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        logger.warning("image_generation_job launch failed public_id=%s: %r", job.public_id, exc)
        return job, False

    return job, False


# ── Public API: polling + stale reconciliation ──────────────────────────────


def get_job_for_owner(
    db: "Session",
    *,
    user_id: int,
    public_id: str,
    now_utc: Callable[[], datetime] = datetime.utcnow,
) -> Optional[ImageGenerationJob]:
    """Fetch one job by public id, scoped to its OWNER, reconciling staleness.

    Scoped by ``user_id`` rather than by character: the job belongs to the
    account that paid for it, and a public id must not be probeable by anyone
    else who happens to own the character.
    """
    job = (
        db.query(ImageGenerationJob)
        .filter(
            ImageGenerationJob.public_id == public_id,
            ImageGenerationJob.user_id == user_id,
        )
        .first()
    )
    if job is None:
        return None
    return _reconcile_stale(db, job, now_utc)


def get_latest_job_for_character(
    db: "Session",
    *,
    user_id: int,
    character_id: int,
    now_utc: Callable[[], datetime] = datetime.utcnow,
) -> Optional[ImageGenerationJob]:
    """Latest job this account started for this character — refresh recovery.

    This is how a tablet that lost its connection (or its tab) re-attaches to a
    generation in flight without spending again.
    """
    job = (
        db.query(ImageGenerationJob)
        .filter(
            ImageGenerationJob.user_id == user_id,
            ImageGenerationJob.character_id == character_id,
        )
        .order_by(ImageGenerationJob.id.desc())
        .first()
    )
    if job is None:
        return None
    return _reconcile_stale(db, job, now_utc)


def _reconcile_stale(
    db: "Session",
    job: ImageGenerationJob,
    now_utc: Callable[[], datetime],
) -> ImageGenerationJob:
    """Apply the documented stale-job policy to an active row. Terminal rows pass through."""
    if job.status not in IMAGE_GENERATION_JOB_ACTIVE_STATES:
        return job

    now = now_utc()
    age = (now - job.created_at).total_seconds() if job.created_at else 0.0
    heartbeat_age = (now - job.updated_at).total_seconds() if job.updated_at else age

    reason: Optional[str] = None
    if age > HARD_TIMEOUT_S:
        reason = "timeout"
    elif job.status == "queued" and age > LAUNCH_TIMEOUT_S:
        reason = "launch_timeout"
    elif job.status == "running" and heartbeat_age > STALL_TIMEOUT_S:
        reason = "stalled"

    if reason is None:
        return job

    job.status = "failed"
    job.error_code = reason
    job.error_message = _SAFE_STALE_MESSAGE
    job.diag_json = {
        **(job.diag_json or {}),
        "stale_reconciled": {
            "reason": reason,
            "age_s": int(age),
            "heartbeat_age_s": int(heartbeat_age),
        },
    }
    job.finished_at = now
    db.commit()
    db.refresh(job)
    logger.warning(
        "image_generation_job stale-reconciled public_id=%s reason=%s age=%ds",
        job.public_id, reason, int(age),
    )
    return job


# ── Job execution (driver + tests) ──────────────────────────────────────────


def _default_pipeline(job: ImageGenerationJob, db: "Session", on_progress) -> tuple[Any, dict]:
    """Run the shared generation pipeline for this job's stored params.

    Ownership was validated at submission; the character is re-read here because
    it may have been deleted since.
    """
    from app.models.character import Character as CharacterModel
    from app.models.user import User
    from app.services.image_generation_pipeline import run_image_generation

    params = GenerationParams.from_json(job.params_json or {})
    character = (
        db.query(CharacterModel).filter(CharacterModel.id == job.character_id).first()
    )
    if character is None:
        raise ImageGenerationJobError(404, "Character no longer exists.")
    user = db.query(User).filter(User.id == job.user_id).first()
    if user is None:
        raise ImageGenerationJobError(404, "Account no longer exists.")

    on_progress("generating", "Generating your image…")
    return run_image_generation(db, character=character, user=user, params=params)


def run_image_generation_job(
    job_id: int,
    *,
    session_factory: Optional[Callable[[], "Session"]] = None,
    pipeline: Optional[Callable[..., tuple[Any, dict]]] = None,
) -> None:
    """Execute one queued job to a terminal state. Called by the detached driver.

    Safe against double invocation: only a ``queued`` row is picked up, so a
    stray relaunch of an already-running or finished job is a no-op — which is
    the second half of the spend guarantee (the first being the unique key).

    A pipeline ``HTTPException`` is a real, classified user-facing outcome
    (canon incomplete, provider refusal, references unloadable), so its status
    and detail are preserved verbatim on the job rather than being flattened
    into a generic failure. Everything else is an internal error: the safe
    message goes to the user and the traceback goes to ``diag_json``.
    """
    if session_factory is None:
        from app.core.database import SessionLocal as session_factory  # type: ignore[no-redef]
    pipeline = pipeline or _default_pipeline

    db = session_factory()
    try:
        job = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job_id).first()
        if job is None:
            logger.error("image_generation_job runner: job %s not found", job_id)
            return
        if job.status != "queued":
            logger.warning(
                "image_generation_job runner: job %s is %s, not queued — skipping",
                job.public_id, job.status,
            )
            return

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.attempt_count = (job.attempt_count or 0) + 1
        job.stage = "preparing"
        job.progress_message = "Preparing your references…"
        db.commit()

        def _on_progress(stage: str, message: str) -> None:
            job.stage = stage
            job.progress_message = message
            job.updated_at = datetime.utcnow()  # heartbeat, even if stage repeats
            db.commit()

        try:
            image, summary = pipeline(job, db, _on_progress)
        except HTTPException as exc:
            db.rollback()
            _fail(
                db, job_id,
                error_code=f"http_{exc.status_code}",
                error_message=str(exc.detail)[:400],
                diag={"http_status": exc.status_code},
            )
            logger.info(
                "image_generation_job classified failure job_id=%s status=%s",
                job_id, exc.status_code,
            )
            return
        except ImageGenerationJobError as exc:
            db.rollback()
            _fail(
                db, job_id,
                error_code="precondition_failed",
                error_message=exc.detail[:400],
                diag={"http_status": exc.status_code},
            )
            return
        except Exception as exc:  # noqa: BLE001 — any crash is a clean failed job
            db.rollback()
            _fail(
                db, job_id,
                error_code="pipeline_error",
                error_message=_SAFE_FAILURE_MESSAGE,
                diag={
                    "exception": repr(exc)[:500],
                    "traceback": traceback.format_exc()[-2000:],
                },
            )
            logger.exception("image_generation_job pipeline failed job_id=%s", job_id)
            return

        job = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job_id).first()
        if job is None:  # pragma: no cover - defensive
            return
        job.status = "completed"
        job.stage = "completed"
        job.progress_message = "Image ready"
        job.image_id = int(image.id)
        job.result_json = summary
        job.finished_at = datetime.utcnow()
        db.commit()
        logger.info(
            "image_generation_job completed public_id=%s image_id=%s refs_source=%s",
            job.public_id, job.image_id, summary.get("refs_source"),
        )
    finally:
        db.close()


def _fail(
    db: "Session",
    job_id: int,
    *,
    error_code: str,
    error_message: str,
    diag: dict,
) -> None:
    """Write one terminal failure to a job row. Never raises."""
    job = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == job_id).first()
    if job is None:
        return
    job.status = "failed"
    job.error_code = error_code
    job.error_message = error_message
    job.diag_json = {**(job.diag_json or {}), **diag}
    job.finished_at = datetime.utcnow()
    db.commit()
