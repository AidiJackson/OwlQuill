"""Identity Pack ASYNC JOBS (Sprint 35) — fire-and-poll for the v2 canon pack.

Mirrors the proven detached-driver pattern (editor_job_service.py /
adult_founder_job_service.py): ``start_identity_pack_job`` creates a job row
and launches ONE detached driver process (scripts/identity_pack_job_driver.py),
returning immediately. The driver calls ``run_identity_pack_job``, which
executes the existing synchronous pipeline (canon_pack_builder.build_v2_pack)
unchanged and writes status/stage/result directly to the job row. The frontend
polls the row.

Duplicate protection
--------------------
* DB level: partial unique index ``ux_identity_pack_jobs_one_active`` — at most
  one queued/running job per character; a losing racer gets IntegrityError and
  is handed the winner's job.
* Idempotency key: a resubmission carrying the key of an existing non-failed
  job returns that job instead of generating again.

Recovery policy (explicit — single-process Replit deployment)
-------------------------------------------------------------
The driver is a detached OS process (``start_new_session=True``): it survives
a uvicorn dev reload, but NOT a container restart/redeploy — full durability
across container death is not claimed. Stale jobs are therefore reconciled at
poll time instead of pretending to survive:

* ``queued`` with no start after LAUNCH_TIMEOUT_S       → failed (launch_timeout)
* ``running`` with a heartbeat older than STALL_TIMEOUT_S → failed (stalled)
* any active job older than HARD_TIMEOUT_S               → failed (timeout)

No automatic re-run — retry is a user action, so a dead driver can never cause
duplicate paid provider calls. build_v2_pack skips already-populated canon
slots, so a manual retry never re-buys cards that finished before the crash.

All side effects (launcher, session factory, pipeline, clock) are injectable so
tests run with zero subprocesses, zero spend, and zero live providers.
"""
from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from sqlalchemy.exc import IntegrityError

from app.models.identity_pack_job import (
    IDENTITY_PACK_JOB_ACTIVE_STATES,
    IdentityPackJob,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = _REPO_ROOT / "scripts"
DRIVER_PATH = SCRIPTS_DIR / "identity_pack_job_driver.py"
DRIVER_LOG_DIR = SCRIPTS_DIR / "identity_pack_job_logs"

# Stale-job reconciliation thresholds (seconds). The heartbeat advances at
# every card boundary; a single card (gen + gate + retry) stays far below the
# stall window.
LAUNCH_TIMEOUT_S = 180
STALL_TIMEOUT_S = 600
HARD_TIMEOUT_S = 2700

_SAFE_STALE_MESSAGE = (
    "Generation was interrupted before it could finish. "
    "Your completed images are kept — you can safely retry."
)
_SAFE_FAILURE_MESSAGE = (
    "We couldn't generate the identity pack right now. Please try again."
)

# Human-readable stage lines, keyed by the stage keys build_v2_pack emits.
_SLOT_LABELS: dict[str, str] = {
    "face_front": "front portrait",
    "face_left_3q": "left three-quarter portrait",
    "face_right_3q": "right three-quarter portrait",
    "face_profile": "profile portrait",
    "face_expression": "expression portrait",
    "body_front": "front body reference",
    "body_left": "left body reference",
    "body_right": "right body reference",
    "body_back": "back body reference",
    "torso_front": "torso reference",
    "torso_side": "side torso reference",
    "standing_relaxed": "standing pose",
    "seated_relaxed": "seated pose",
}


class IdentityPackJobError(Exception):
    """Service-level job failure with an HTTP status hint for the route."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Injected side effects ───────────────────────────────────────────────────


def _default_launcher(job_public_id: str, job_id: int) -> None:
    """Spawn the detached identity-pack driver; returns once it starts."""
    from app.services.detached_driver import spawn_detached_driver

    spawn_detached_driver(
        driver_path=DRIVER_PATH,
        log_dir=DRIVER_LOG_DIR,
        log_name=job_public_id,
        extra_env={"IDENTITY_PACK_JOB_ID": str(job_id)},
        cwd=_REPO_ROOT,
    )
    logger.info("identity_pack_job launched public_id=%s job_id=%s", job_public_id, job_id)


# ── Public API: submission ──────────────────────────────────────────────────


def get_active_job(db: "Session", character_id: int) -> Optional[IdentityPackJob]:
    return (
        db.query(IdentityPackJob)
        .filter(IdentityPackJob.character_id == character_id,
                IdentityPackJob.status.in_(IDENTITY_PACK_JOB_ACTIVE_STATES))
        .order_by(IdentityPackJob.id.desc())
        .first()
    )


def get_latest_job(db: "Session", character_id: int) -> Optional[IdentityPackJob]:
    return (
        db.query(IdentityPackJob)
        .filter(IdentityPackJob.character_id == character_id)
        .order_by(IdentityPackJob.id.desc())
        .first()
    )


def start_identity_pack_job(
    db: "Session",
    *,
    character_id: int,
    user_id: int,
    params: dict[str, Any],
    idempotency_key: Optional[str] = None,
    launcher: Optional[Callable[[str, int], None]] = None,
) -> tuple[IdentityPackJob, bool]:
    """Create + launch ONE detached v2-pack job for a character.

    Returns ``(job, reused)`` — ``reused=True`` when an existing job was
    returned instead of creating a new one (active job present, idempotent
    resubmission, or a lost insert race).

    ``params`` must already be sanitised by the route (provider_option,
    max_spend, admin flags only — never credentials).
    """
    launcher = launcher or _default_launcher

    # Fast path: an active job already exists → hand it back, charge nothing.
    active = get_active_job(db, character_id)
    if active is not None:
        return active, True

    # Idempotent resubmission: same key on any non-failed job → return it, so
    # a refresh-and-resubmit after completion cannot silently regenerate.
    if idempotency_key:
        prior = (
            db.query(IdentityPackJob)
            .filter(IdentityPackJob.character_id == character_id,
                    IdentityPackJob.idempotency_key == idempotency_key,
                    IdentityPackJob.status != "failed")
            .order_by(IdentityPackJob.id.desc())
            .first()
        )
        if prior is not None:
            return prior, True

    job = IdentityPackJob(
        public_id=uuid.uuid4().hex,
        user_id=user_id,
        character_id=character_id,
        status="queued",
        stage="queued",
        progress_message="Waiting to start…",
        progress_percent=0,
        idempotency_key=idempotency_key,
        params_json=params,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # Lost the insert race — the partial unique index guarantees exactly
        # one active row, so the winner must exist. Return it.
        db.rollback()
        winner = get_active_job(db, character_id)
        if winner is not None:
            return winner, True
        raise IdentityPackJobError(
            409, "Another generation for this character just started. Please refresh."
        )
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
        logger.warning("identity_pack_job launch failed public_id=%s: %r", job.public_id, exc)
        return job, False

    return job, False


# ── Public API: polling + stale reconciliation ──────────────────────────────


def get_job_for_owner(
    db: "Session",
    *,
    character_id: int,
    public_id: str,
    now_utc: Callable[[], datetime] = datetime.utcnow,
) -> Optional[IdentityPackJob]:
    """Fetch one job by public id (scoped to the character), reconciling staleness."""
    job = (
        db.query(IdentityPackJob)
        .filter(IdentityPackJob.public_id == public_id,
                IdentityPackJob.character_id == character_id)
        .first()
    )
    if job is None:
        return None
    return _reconcile_stale(db, job, now_utc)


def get_latest_job_reconciled(
    db: "Session",
    character_id: int,
    *,
    now_utc: Callable[[], datetime] = datetime.utcnow,
) -> Optional[IdentityPackJob]:
    job = get_latest_job(db, character_id)
    if job is None:
        return None
    return _reconcile_stale(db, job, now_utc)


def _reconcile_stale(
    db: "Session",
    job: IdentityPackJob,
    now_utc: Callable[[], datetime],
) -> IdentityPackJob:
    """Apply the documented stale-job policy to an active row. Terminal rows pass through."""
    if job.status not in IDENTITY_PACK_JOB_ACTIVE_STATES:
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
        "identity_pack_job stale-reconciled public_id=%s reason=%s age=%ds",
        job.public_id, reason, int(age),
    )
    return job


# ── Job execution (driver + tests) ──────────────────────────────────────────


def _stage_view(stage_key: str, done: int, total: int) -> tuple[str, str, int]:
    """Map a build_v2_pack stage key to (stage, message, percent)."""
    if stage_key.startswith("card:"):
        slot = stage_key.split(":", 1)[1]
        label = _SLOT_LABELS.get(slot, slot.replace("_", " "))
        return stage_key, f"Generating {label} ({done + 1}/{total})", int(done * 100 / max(total, 1))
    if stage_key == "mark_details":
        return stage_key, "Rendering body-mark detail crops", 95
    return stage_key, stage_key.replace("_", " ").capitalize(), 0


def _default_pipeline(job: IdentityPackJob, db: "Session", on_progress) -> dict:
    """Run the existing synchronous v2 pack pipeline, unchanged.

    This is the exact sequence the sync route performs (ownership was already
    validated at submission): assemble identity → SpendTracker → build_v2_pack.
    """
    from app.models.character import Character as CharacterModel
    from app.services.canon_card_generator import SpendTracker
    from app.services.canon_pack_builder import (
        DEFAULT_MAX_SPEND_USD,
        build_v2_pack,
        founder_identity_from_character,
    )
    from app.services.canon_service import get_or_create_canon

    params = job.params_json or {}
    char = db.query(CharacterModel).filter(CharacterModel.id == job.character_id).first()
    if char is None:
        raise IdentityPackJobError(404, "Character no longer exists.")

    canon = get_or_create_canon(job.character_id, db)
    identity = founder_identity_from_character(char, canon, db)

    ceiling = DEFAULT_MAX_SPEND_USD
    cap = max(0.5, min(float(params.get("max_spend") or ceiling), ceiling))
    spend = SpendTracker(cap_usd=cap)

    is_admin = bool(params.get("is_admin"))
    return build_v2_pack(
        canon=canon,
        identity=identity,
        db=db,
        spend=spend,
        provider_option=params.get("provider_option") or "option2",
        is_admin=is_admin,
        admin_fallback=bool(params.get("admin_fallback")) and is_admin,
        dry_run=False,
        on_progress=on_progress,
    )


def run_identity_pack_job(
    job_id: int,
    *,
    session_factory: Optional[Callable[[], "Session"]] = None,
    pipeline: Optional[Callable[..., dict]] = None,
) -> None:
    """Execute one queued job to a terminal state. Called by the detached driver.

    Safe against double invocation: only a ``queued`` row is picked up, so a
    stray relaunch of an already-running/completed job is a no-op.
    """
    if session_factory is None:
        from app.core.database import SessionLocal as session_factory  # type: ignore[no-redef]
    pipeline = pipeline or _default_pipeline

    db = session_factory()
    try:
        job = db.query(IdentityPackJob).filter(IdentityPackJob.id == job_id).first()
        if job is None:
            logger.error("identity_pack_job runner: job %s not found", job_id)
            return
        if job.status != "queued":
            logger.warning(
                "identity_pack_job runner: job %s is %s, not queued — skipping",
                job.public_id, job.status,
            )
            return

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.attempt_count = (job.attempt_count or 0) + 1
        job.stage = "preparing"
        job.progress_message = "Preparing identity specification"
        job.progress_percent = 0
        db.commit()

        def _on_progress(stage_key: str, done: int, total: int) -> None:
            stage, message, percent = _stage_view(stage_key, done, total)
            job.stage = stage
            job.progress_message = message
            job.progress_percent = percent
            job.updated_at = datetime.utcnow()  # heartbeat, even if % unchanged
            db.commit()

        try:
            report = pipeline(job, db, _on_progress)
        except Exception as exc:  # noqa: BLE001 — any pipeline crash is a clean failed job
            db.rollback()
            job = db.query(IdentityPackJob).filter(IdentityPackJob.id == job_id).first()
            if job is not None:
                job.status = "failed"
                job.error_code = "pipeline_error"
                job.error_message = _SAFE_FAILURE_MESSAGE
                job.diag_json = {
                    "exception": repr(exc)[:500],
                    "traceback": traceback.format_exc()[-2000:],
                }
                job.finished_at = datetime.utcnow()
                db.commit()
            logger.exception("identity_pack_job pipeline failed job_id=%s", job_id)
            return

        job.stage = "finalising"
        job.progress_message = "Finalising candidates"
        job.progress_percent = 99
        db.commit()

        job.status = "completed"
        job.stage = "completed"
        job.progress_message = "Identity pack ready"
        job.progress_percent = 100
        job.result_json = report
        job.finished_at = datetime.utcnow()
        db.commit()
        logger.info(
            "identity_pack_job completed public_id=%s cards=%d spend=$%.3f clean=%s",
            job.public_id, len(report.get("cards", [])),
            report.get("total_spend", 0.0), report.get("clean_pass"),
        )
    finally:
        db.close()
