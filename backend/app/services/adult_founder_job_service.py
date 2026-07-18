"""Adult Studio FOUNDER ASYNC LITE — job orchestration (Phase 3, Sprint 13).

Fire-and-poll founder Generate. ``start_founder_job`` runs the shared founder gates, then
(singleton) launches ONE detached RunPod masked-diffusion driver and returns immediately
with a ``queued``/``running`` job. ``get_latest_job`` reconciles a running job from the
run_id-scoped report file the driver writes (or times it out). The real final image is the
RunPod ``99_final`` — never the diagnostic montage.

Boundaries: Summer-only (character_id=60), admin-only (enforced at the route), $0.05 cap
(the driver carries the proof_lib safety profile), ONE active job at a time. No Canon
Studio, no normal image generator, no core-pipeline change — this is founder-only async
wiring around the already-proven driver + pod pipeline.

All side effects are injected (launcher / report reader / terminator / clock) so the whole
service is unit-testable with zero spend and zero subprocess.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from app.models.adult_founder_job import (
    ADULT_FOUNDER_ACTIVE_STATES,
    AdultFounderJob,
)
from app.services.adult_identity_founder_generate import (
    FOUNDER_SPEND_CAP_USD,
    SUMMER_CHARACTER_ID,
    FounderGenerateBlocked,
    build_founder_base_prompt,
    validate_founder_preconditions,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models.adult_identity import AdultIdentityModel

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = _REPO_ROOT / "scripts"
FOUNDER_REPORTS_DIR = SCRIPTS_DIR / "founder_reports"
DRIVER_PATH = SCRIPTS_DIR / "founder_async_runpod_driver.py"

# Hard backstop: if no terminal report appears within this wall-clock, the job is failed
# (the driver's own 700s in-pod watchdog + finally-terminate already cap spend; this is a
# generous reconciler-side timeout so a dead driver never leaves a job stuck "running").
JOB_TIMEOUT_S = 1500


# ── Run id ──────────────────────────────────────────────────────────────────────


def _new_run_id() -> str:
    import uuid
    return "founder_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


# ── Injected side effects (defaults wire the real driver / filesystem) ───────────


def _default_launcher(run_id: str, base_prompt: str, model: "AdultIdentityModel") -> None:
    """Spawn the detached founder RunPod driver. Returns once the process is started.

    The driver consumes the DB enforcement plan itself; we pass the founder prompt +
    run_id via env. stdout/stderr go to a run-scoped log. start_new_session detaches it
    from the API process so it outlives the request.
    """
    from app.services.detached_driver import spawn_detached_driver

    spawn_detached_driver(
        driver_path=DRIVER_PATH,
        log_dir=FOUNDER_REPORTS_DIR,
        log_name=run_id,
        extra_env={"FOUNDER_RUN_ID": run_id, "BASE_PROMPT": base_prompt},
        cwd=_REPO_ROOT,
    )
    logger.info("founder_job launched run_id=%s driver=%s", run_id, DRIVER_PATH)


def _default_report_reader(run_id: str) -> Optional[dict[str, Any]]:
    """Read the run_id-scoped driver report, or None if it doesn't exist yet."""
    path = FOUNDER_REPORTS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001 — a partially-written report just isn't terminal yet
        logger.warning("founder_job report parse failed run_id=%s: %r", run_id, e)
        return None


def _default_terminator(pod_id: Optional[str]) -> None:
    """Best-effort terminate a RunPod pod by id (used on cancel / orphan)."""
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
        logger.info("founder_job terminate sent pod_id=%s", pod_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("founder_job terminate failed pod_id=%s: %r", pod_id, e)


# ── Public API ───────────────────────────────────────────────────────────────────


def get_active_job(db: "Session", character_id: int) -> Optional[AdultFounderJob]:
    """The current queued/running job for the character, if any."""
    return (
        db.query(AdultFounderJob)
        .filter(
            AdultFounderJob.character_id == character_id,
            AdultFounderJob.state.in_(ADULT_FOUNDER_ACTIVE_STATES),
        )
        .order_by(AdultFounderJob.id.desc())
        .first()
    )


def get_latest_job_row(db: "Session", character_id: int) -> Optional[AdultFounderJob]:
    return (
        db.query(AdultFounderJob)
        .filter(AdultFounderJob.character_id == character_id)
        .order_by(AdultFounderJob.id.desc())
        .first()
    )


def start_founder_job(
    db: "Session",
    character_id: int,
    prompt: str,
    *,
    launcher: Optional[Callable[[str, str, "AdultIdentityModel"], None]] = None,
) -> AdultFounderJob:
    """Validate, enforce the singleton, and launch ONE detached founder job.

    Raises :class:`FounderGenerateBlocked` (mapped to HTTP codes by the route):
    same gates as the sync path, plus 409 if a founder job is already active.
    """
    launcher = launcher or _default_launcher
    # Shared gates (Summer → prompt → ready+active → safety). No spend/pod touched.
    model = validate_founder_preconditions(db, character_id, prompt)

    # Singleton: at most one active founder job.
    if get_active_job(db, character_id) is not None:
        raise FounderGenerateBlocked(
            409, "A founder job is already running. Wait for it to finish or cancel it.")

    run_id = _new_run_id()
    base_prompt = build_founder_base_prompt(prompt, model.trigger_token or "TOK")

    job = AdultFounderJob(
        character_id=character_id, prompt=prompt, state="queued", run_id=run_id)
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        launcher(run_id, base_prompt, model)
    except Exception as e:  # noqa: BLE001 — a launch failure must not leave a stuck job
        job.state = "failed"
        job.error = f"launch_failed: {e}"
        db.commit()
        db.refresh(job)
        logger.warning("founder_job launch failed run_id=%s: %r", run_id, e)
        return job

    job.state = "running"
    db.commit()
    db.refresh(job)
    return job


def get_latest_job(
    db: "Session",
    character_id: int,
    *,
    report_reader: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
    terminator: Optional[Callable[[Optional[str]], None]] = None,
    now_utc: Callable[[], datetime] = datetime.utcnow,
    timeout_s: int = JOB_TIMEOUT_S,
) -> Optional[AdultFounderJob]:
    """Return the latest job, reconciling an active one from its driver report."""
    report_reader = report_reader or _default_report_reader
    terminator = terminator or _default_terminator
    job = get_latest_job_row(db, character_id)
    if job is None or job.state not in ADULT_FOUNDER_ACTIVE_STATES:
        return job
    return _reconcile(db, job, report_reader, terminator, now_utc, timeout_s)


def cancel_job(
    db: "Session",
    character_id: int,
    *,
    terminator: Optional[Callable[[Optional[str]], None]] = None,
) -> AdultFounderJob:
    """Cancel the active founder job: terminate its pod (best-effort) and mark failed."""
    terminator = terminator or _default_terminator
    job = get_active_job(db, character_id)
    if job is None:
        raise FounderGenerateBlocked(409, "No active founder job to cancel.")
    terminator(job.pod_id)
    job.state = "failed"
    job.error = "Canceled by founder."
    db.commit()
    db.refresh(job)
    return job


# ── Reconciliation ───────────────────────────────────────────────────────────────


def _reconcile(
    db: "Session",
    job: AdultFounderJob,
    report_reader: Callable[[str], Optional[dict[str, Any]]],
    terminator: Callable[[Optional[str]], None],
    now_utc: Callable[[], datetime],
    timeout_s: int,
) -> AdultFounderJob:
    report = report_reader(job.run_id)
    if report is not None and _is_terminal(report):
        result = _map_report_to_result(report)
        job.pod_id = report.get("pod_id") or job.pod_id
        job.final_image_url = result["final_image_url"]
        job.result_json = result
        if result["success"] and result["final_image_url"]:
            job.state = "completed"
            job.error = None
        else:
            job.state = "failed"
            job.error = "; ".join(result["blocking_reasons"]) or "Generation failed."
        db.commit()
        db.refresh(job)
        return job

    # No terminal report yet → enforce the wall-clock backstop.
    elapsed = (now_utc() - job.created_at).total_seconds() if job.created_at else 0.0
    if elapsed > timeout_s:
        terminator(job.pod_id)  # backstop kill in case the driver died with a live pod
        job.state = "failed"
        job.error = f"Timed out after {int(elapsed)}s with no completed result."
        db.commit()
        db.refresh(job)
    return job


def _is_terminal(report: dict[str, Any]) -> bool:
    """A driver report is terminal ONLY on a genuine end signal.

    The driver rewrites the report on every poll: it sets ``success=False`` and
    ``diffusion_pass="failed"`` for in-progress states too (the pass only flips to
    "completed" at the very end). So neither ``success is not None`` (always true) nor a
    bare ``diffusion_pass="failed"`` means the run finished — using them marked a still-
    loading pod (``pod_status_final="load_pipeline"``) as failed. Terminal is instead:
    a completed pass, a recorded pod error, or a true end-state stage. Otherwise the job
    stays running and is caught by the wall-clock timeout backstop in ``_reconcile``.
    """
    return (
        report.get("diffusion_pass") == "completed"
        or bool(report.get("pod_errors"))
        or report.get("pod_status_final") in ("done", "aborted_no_gpu", "rate_guard")
    )


def _map_report_to_result(report: dict[str, Any]) -> dict[str, Any]:
    """Map a driver report → the founder-generate response contract (the real 99_final)."""
    image_urls = report.get("image_urls") or {}
    final_url = report.get("final_image_url") or image_urls.get("final")
    artifacts = [u for u in (image_urls.get("artifacts") or []) if u and u != final_url]

    no_orphans = report.get("no_orphaned_pods")
    orphaned = [] if no_orphans else ([report.get("pod_id")] if report.get("pod_id") else [])

    blocking = list(report.get("pod_errors") or [])
    success = bool(report.get("success")) and bool(final_url)
    if orphaned:
        blocking.append(f"orphaned workers detected: {', '.join(orphaned)}")
        success = False
    if not final_url and not blocking:
        blocking.append(
            f"no final image (diffusion_pass={report.get('diffusion_pass')}).")

    return {
        "final_image_url": final_url,
        "intermediate_artifact_urls": artifacts,
        "cost": report.get("spend_usd", 0.0),
        "runtime": report.get("runtime_s", 0.0),
        "routes_executed": report.get("routes_executed") or [],
        "manual_review_required": True,
        "success": success,
        "blocking_reasons": blocking,
        "orphaned_workers": orphaned,
        "spend_cap_usd": report.get("spend_cap_usd", FOUNDER_SPEND_CAP_USD),
        "pod_id": report.get("pod_id"),
    }
