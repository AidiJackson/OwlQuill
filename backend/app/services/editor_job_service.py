"""Editor Studio ASYNC JOBS — orchestration + quality gate (Sprint E5).

Fire-and-poll for the self_hosted editor provider, mirroring Founder Async Lite
(adult_founder_job_service.py): ``start_editor_job`` enforces a per-character
singleton and launches ONE detached driver process (scripts/editor_async_driver.py),
returning immediately. The driver runs the RunPod transform, applies the quality
gate, saves the image to the library, and writes a run_id-scoped report file;
``get_job``/``get_latest_job`` reconcile the row from that file on poll.

The quality gate (Part B) lives here as a pure function so it is unit-testable:
a transform only counts as a clean "pass" when the final image is valid AND the
pod's quality metrics (remnant_px_final, seam_ratio) are inside thresholds.

All side effects are injected (launcher / report reader / terminator / clock).
No Canon Studio, no Adult Studio, no sync /editor/generate change.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from app.models.editor_job import EDITOR_JOB_ACTIVE_STATES, EditorJob

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = _REPO_ROOT / "scripts"
EDITOR_JOB_REPORTS_DIR = SCRIPTS_DIR / "editor_job_reports"
DRIVER_PATH = SCRIPTS_DIR / "editor_async_driver.py"

# Reconciler-side wall-clock backstop. The driver's supervision already caps
# spend/time hard; this only guards against a dead driver leaving a stuck job.
JOB_TIMEOUT_S = 1500

# ── Quality gate thresholds (Part B; initial calibration, conservative) ─────
QUALITY_REMNANT_NEEDS_REVIEW_PX = 1500   # unchanged source-dress px in final
QUALITY_SEAM_RATIO_NEEDS_REVIEW = 2.5    # silhouette-band/global gradient ratio
QUALITY_MIN_DIM_PX = 64


class EditorJobError(Exception):
    """Service-level job failure with an HTTP status hint for the route."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Quality gate (pure) ─────────────────────────────────────────────────────


def evaluate_quality(
    pod_status: Optional[dict],
    png_bytes: Optional[bytes],
    source_size: Optional[tuple[int, int]] = None,
) -> tuple[str, list[str]]:
    """Part B gate: classify a transform as pass | needs_review | failed.

    failed       — output invalid (missing/corrupt image, wrong dimensions).
    needs_review — image valid but metrics suggest visible defects (remnants,
                   harsh person/background seam) or non-fatal pod errors.
    pass         — image valid, metrics inside thresholds, no pod errors.
    """
    reasons: list[str] = []

    if not png_bytes:
        return "failed", ["no final image bytes"]
    try:
        import io

        from PIL import Image

        Image.open(io.BytesIO(png_bytes)).verify()
        img = Image.open(io.BytesIO(png_bytes))  # verify() invalidates the handle
        w, h = img.size
    except Exception as exc:  # noqa: BLE001 — undecodable output is a hard fail
        return "failed", [f"final image failed to load: {exc!r}"]
    if w < QUALITY_MIN_DIM_PX or h < QUALITY_MIN_DIM_PX:
        return "failed", [f"output dimensions invalid: {w}x{h}"]
    if source_size is not None:
        # The pod crops the source to multiples of 8; the final must match that.
        exp_w, exp_h = source_size[0] - source_size[0] % 8, source_size[1] - source_size[1] % 8
        if (w, h) != (exp_w, exp_h):
            return "failed", [f"output {w}x{h} does not match source {exp_w}x{exp_h}"]

    metrics = (pod_status or {}).get("quality") or {}
    remnants = metrics.get("remnant_px_final")
    if remnants is not None and remnants >= QUALITY_REMNANT_NEEDS_REVIEW_PX:
        reasons.append(f"dress remnants suspected ({remnants}px unchanged from source)")
    seam = metrics.get("seam_ratio")
    if seam is not None and seam >= QUALITY_SEAM_RATIO_NEEDS_REVIEW:
        reasons.append(f"harsh person/background seam (ratio {seam})")
    if not metrics:
        reasons.append("pod returned no quality metrics")
    pod_errors = [e for e in ((pod_status or {}).get("errors") or [])
                  if "lora_load" not in str(e)]  # LoRA fallback is non-visual
    if pod_errors:
        reasons.append(f"pod errors: {'; '.join(str(e)[:120] for e in pod_errors)}")

    return ("needs_review" if reasons else "pass"), reasons


# ── Injected side effects ───────────────────────────────────────────────────


def _new_run_id() -> str:
    import uuid

    return ("editor_job_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            + "_" + uuid.uuid4().hex[:8])


def _default_launcher(run_id: str, job_id: int) -> None:
    """Spawn the detached editor driver; returns once the process starts."""
    import subprocess

    EDITOR_JOB_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "EDITOR_RUN_ID": run_id, "EDITOR_JOB_ID": str(job_id)}
    logf = open(EDITOR_JOB_REPORTS_DIR / f"{run_id}.log", "ab")  # noqa: SIM115
    subprocess.Popen(
        [sys.executable, str(DRIVER_PATH)],
        env=env, stdout=logf, stderr=logf,
        start_new_session=True, cwd=str(_REPO_ROOT),
    )
    logger.info("editor_job launched run_id=%s job_id=%s", run_id, job_id)


def _default_report_reader(run_id: str) -> Optional[dict[str, Any]]:
    path = EDITOR_JOB_REPORTS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 — partial write isn't terminal yet
        logger.warning("editor_job report parse failed run_id=%s: %r", run_id, exc)
        return None


def _default_terminator(pod_id: Optional[str]) -> None:
    if not pod_id:
        return
    try:
        import requests

        key = os.environ.get("RUNPOD_API_KEY")
        if not key:
            return
        requests.post(
            f"https://api.runpod.io/graphql?api_key={key}",
            json={"query": "mutation($id:String!){ podTerminate(input:{podId:$id}) }",
                  "variables": {"id": pod_id}},
            timeout=30,
        )
        logger.info("editor_job terminate sent pod_id=%s", pod_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("editor_job terminate failed pod_id=%s: %r", pod_id, exc)


# ── Public API ──────────────────────────────────────────────────────────────


def get_active_job(db: "Session", character_id: int) -> Optional[EditorJob]:
    return (
        db.query(EditorJob)
        .filter(EditorJob.character_id == character_id,
                EditorJob.state.in_(EDITOR_JOB_ACTIVE_STATES))
        .order_by(EditorJob.id.desc())
        .first()
    )


def start_editor_job(
    db: "Session",
    *,
    character_id: int,
    user_id: int,
    prompt: str,
    source_file_path: str,
    source_image_ids: list[int],
    strength: float,
    launcher: Optional[Callable[[str, int], None]] = None,
) -> EditorJob:
    """Create + launch ONE detached self_hosted editor job (singleton-active)."""
    launcher = launcher or _default_launcher
    if get_active_job(db, character_id) is not None:
        raise EditorJobError(
            409, "An editor job is already running for this character. "
                 "Wait for it to finish or cancel it.")

    run_id = _new_run_id()
    job = EditorJob(
        character_id=character_id,
        user_id=user_id,
        prompt=prompt,
        provider="self_hosted",
        state="queued",
        run_id=run_id,
        params_json={
            "source_file_path": source_file_path,
            "source_image_ids": source_image_ids,
            "strength": strength,
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        launcher(run_id, job.id)
    except Exception as exc:  # noqa: BLE001 — a launch failure must not strand the job
        job.state = "failed"
        job.error = f"launch_failed: {exc}"
        db.commit()
        db.refresh(job)
        logger.warning("editor_job launch failed run_id=%s: %r", run_id, exc)
        return job

    job.state = "running"
    db.commit()
    db.refresh(job)
    return job


def get_job(
    db: "Session",
    job_id: int,
    *,
    report_reader: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    terminator: Optional[Callable[[Optional[str]], None]] = None,
    now_utc: Callable[[], datetime] = datetime.utcnow,
    timeout_s: int = JOB_TIMEOUT_S,
) -> Optional[EditorJob]:
    """Fetch one job by id, reconciling it from its driver report if active."""
    job = db.query(EditorJob).filter(EditorJob.id == job_id).first()
    if job is None or job.state not in EDITOR_JOB_ACTIVE_STATES:
        return job
    return _reconcile(db, job, report_reader or _default_report_reader,
                      terminator or _default_terminator, now_utc, timeout_s)


def get_latest_job(
    db: "Session",
    character_id: int,
    *,
    report_reader: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    terminator: Optional[Callable[[Optional[str]], None]] = None,
    now_utc: Callable[[], datetime] = datetime.utcnow,
    timeout_s: int = JOB_TIMEOUT_S,
) -> Optional[EditorJob]:
    """Latest job for a character (any state), reconciled if active."""
    job = (
        db.query(EditorJob)
        .filter(EditorJob.character_id == character_id)
        .order_by(EditorJob.id.desc())
        .first()
    )
    if job is None or job.state not in EDITOR_JOB_ACTIVE_STATES:
        return job
    return _reconcile(db, job, report_reader or _default_report_reader,
                      terminator or _default_terminator, now_utc, timeout_s)


def cancel_job(
    db: "Session",
    job_id: int,
    *,
    report_reader: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    terminator: Optional[Callable[[Optional[str]], None]] = None,
) -> EditorJob:
    """Cancel an active job: best-effort terminate its pod, mark failed."""
    terminator = terminator or _default_terminator
    report_reader = report_reader or _default_report_reader
    job = db.query(EditorJob).filter(EditorJob.id == job_id).first()
    if job is None:
        raise EditorJobError(404, "Editor job not found.")
    if job.state not in EDITOR_JOB_ACTIVE_STATES:
        raise EditorJobError(409, f"Job is already {job.state} — nothing to cancel.")
    # The driver publishes pod_id in a non-terminal progress report; pick it up
    # so cancel can actually kill the pod.
    report = report_reader(job.run_id) or {}
    pod_id = job.pod_id or report.get("pod_id")
    terminator(pod_id)
    job.pod_id = pod_id
    job.state = "failed"
    job.error = "Canceled by user."
    db.commit()
    db.refresh(job)
    return job


# ── Reconciliation ──────────────────────────────────────────────────────────


def _reconcile(
    db: "Session",
    job: EditorJob,
    report_reader: Callable[[str], Optional[dict[str, Any]]],
    terminator: Callable[[Optional[str]], None],
    now_utc: Callable[[], datetime],
    timeout_s: int,
) -> EditorJob:
    report = report_reader(job.run_id)
    if report is not None:
        job.pod_id = report.get("pod_id") or job.pod_id
        if report.get("terminal"):
            job.quality_status = report.get("quality_status")
            job.final_image_url = report.get("final_image_url")
            job.image_id = report.get("image_id")
            job.result_json = {
                k: report.get(k)
                for k in ("quality_status", "quality_reasons", "stage_images",
                          "spend_usd", "runtime_s", "gpu", "errors",
                          "no_orphaned_pods", "r2_final_url")
            }
            if report.get("success") and report.get("quality_status") != "failed":
                job.state = "completed"
                job.error = None
            else:
                job.state = "failed"
                job.error = report.get("error") or "; ".join(
                    str(e) for e in (report.get("errors") or [])) or "Transform failed."
            db.commit()
            db.refresh(job)
            return job
        # Non-terminal progress report: persist pod_id/stage, stay running.
        db.commit()
        db.refresh(job)

    elapsed = (now_utc() - job.created_at).total_seconds() if job.created_at else 0.0
    if elapsed > timeout_s:
        terminator(job.pod_id)
        job.state = "failed"
        job.error = f"Timed out after {int(elapsed)}s with no completed result."
        db.commit()
        db.refresh(job)
    return job
