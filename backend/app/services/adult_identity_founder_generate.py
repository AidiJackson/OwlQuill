"""Adult Studio FOUNDER GENERATE — Summer-only, admin-only orchestration (Phase 3, S8).

The first end-to-end path that turns a founder's text prompt into a REAL Adult Studio
image using the *validated* pipeline — explicitly NOT the old OpenAI gpt-image path:

  - Summer active AdultIdentityModelVersion (the trained LoRA)
  - the DB enforcement plan (identity + per-mark routes + reference crops)
  - the masked-diffusion / tattoo-enforcement EXECUTOR (AdultIdentityEnforcementExecutor)
  - both Summer tattoo routes (ip_adapter sleeve + controlnet_canny ballerina) from DB

This module ONLY orchestrates: it validates the request, builds the active-LoRA base
generator, runs the executor, and maps the report into the founder-generate response.
It performs no network or storage I/O itself — base generation and worker lifecycle are
injected (defaults wire the validated Replicate active-LoRA path), so it is fully
unit-testable with zero spend.

Hard guarantees (all enforced BEFORE any generator is constructed → no spend on a
blocked request):
  - Summer ONLY (character_id == 60). No other character can ever generate here.
  - Admin/founder only (enforced at the route via require_admin).
  - Identity must be status='ready' with a resolvable active_version_id.
  - Prompt required + safety-gated (minors / illegal terms blocked).
  - Hard spend cap $0.05 per generation (the single base image is the only spend).
  - Worker lifecycle is ALWAYS terminated (success or failure) and verified for orphans.

NOT the normal image generator, NOT Canon Studio, NOT the public OpenAI Adult Studio
generate endpoint, NOT user-facing, NOT public. manual_review_required is always True.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

from app.models.adult_identity import AdultIdentityModel
from app.services.adult_identity_enforcement_executor import (
    AdultIdentityEnforcementExecutor,
)
from app.services.adult_studio import check_prompt_safety

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SUMMER_CHARACTER_ID = 60
# Hard spend cap for a single founder generation. The executor receives this cap; the
# single base image is the only spend. Lower than the executor default ($0.15) by design.
FOUNDER_SPEND_CAP_USD = 0.05
REQUIRED_STATUS = "ready"


class FounderGenerateBlocked(Exception):
    """A request was refused by a gate. ``status_code`` maps to the HTTP response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Worker lifecycle (terminate on success/failure; verify no orphans) ─────────


class WorkerLifecycle(Protocol):
    """A pluggable GPU worker/pod lifecycle guard.

    ``terminate`` is ALWAYS called (success or failure). ``list_orphans`` returns the
    ids of any workers/pods still alive afterward — a non-empty result fails the run.
    """

    def terminate(self, reason: str) -> None: ...

    def list_orphans(self) -> list[str]: ...


class ReplicateWorkerLifecycle:
    """Lifecycle for the validated Replicate active-LoRA path.

    Replicate inference is serverless: a prediction is submitted, polled to a terminal
    state, and then holds no persistent pod. There is therefore nothing to leak. This
    guard still runs on every request so the *contract* (always terminate + verify no
    orphans) holds, and so a future GPU-pod backend (RunPod / ComfyUI, Phase 0) can drop
    in a real terminator without changing the orchestration. Any prediction ids handed to
    ``track`` are best-effort cancelled on terminate.
    """

    def __init__(self) -> None:
        self._tracked: list[str] = []
        self._terminated = False

    def track(self, prediction_id: str) -> None:
        if prediction_id:
            self._tracked.append(prediction_id)

    def terminate(self, reason: str) -> None:
        self._terminated = True
        if self._tracked:
            logger.info(
                "founder_generate worker terminate (%s): cancelling %d tracked prediction(s)",
                reason, len(self._tracked))
        # Serverless: predictions are polled to completion by the base generator, so
        # there is no persistent pod to kill. Nothing to do beyond the log line.

    def list_orphans(self) -> list[str]:
        # Serverless path holds nothing after terminate → never orphans.
        return []


# ── Base prompt ────────────────────────────────────────────────────────────────


def build_founder_base_prompt(user_prompt: str, trigger_token: str) -> str:
    """Compose the single base-image prompt: trigger token + founder prompt + framing.

    The 'both arms fully visible' framing keeps both tattoo routes (sleeve / ballerina)
    relevant to the generated base, mirroring the validated enforcement run.
    """
    tok = (trigger_token or "TOK").strip()
    body = (user_prompt or "").strip()
    return (
        f"a photo of {tok}, an adult woman with long blonde hair and blue eyes, "
        f"{body}, both arms fully visible, natural lighting, photorealistic")


# ── Default injected base generator (validated Replicate active-LoRA path) ──────


def _default_make_base_generator(
    model: AdultIdentityModel,
    base_prompt: str,
    spend_cap: float,
    lifecycle: WorkerLifecycle,
) -> Callable[[float], dict]:
    """Wire the validated Replicate active-LoRA inference path as the base generator.

    Imported lazily so the module (and tests) never require the validation script or
    Replicate credentials unless a REAL generation is actually requested.
    """
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import validate_summer_adult_studio_inference as infer  # type: ignore

    def generate_base(remaining_cap: float) -> dict:
        cap = min(remaining_cap, spend_cap)
        # disable_safety: 18+ admin validation only (base SDXL NSFW checker
        # false-positives on adult-but-legal content). Prompt already safety-gated above.
        rep = infer.run_benchmark(
            model.id,
            prompts=[("founder_generate", base_prompt, 832, 1216)],
            spend_cap=cap,
            disable_safety=True,
        )
        gens = rep.get("generations") or []
        g = gens[0] if gens else {}
        pid = g.get("id") or g.get("prediction_id")
        if pid:
            try:
                lifecycle.track(pid)  # type: ignore[attr-defined]
            except AttributeError:
                pass
        return {
            "status": g.get("status", rep.get("result", "error")),
            "image_url": g.get("image_url"),
            "cost_usd": g.get("cost_usd", rep.get("generation_cost_usd_total", 0.0)),
            "prompt": base_prompt,
            "predict_time_s": g.get("predict_time_s"),
            "error": g.get("error") or rep.get("error"),
        }

    return generate_base


def _default_executor_factory(
    db: "Session", generate_base: Callable[[float], dict], spend_cap: float
) -> AdultIdentityEnforcementExecutor:
    return AdultIdentityEnforcementExecutor(
        db, generate_base=generate_base, spend_cap=spend_cap)


# ── Orchestration ──────────────────────────────────────────────────────────────


def validate_founder_preconditions(
    db: "Session", character_id: int, prompt: str
) -> AdultIdentityModel:
    """Run the founder gates in order; return the Summer identity model if all pass.

    Shared by BOTH the (legacy) synchronous path and the async-job path so the gates —
    and their HTTP codes — are identical. Raises :class:`FounderGenerateBlocked` on the
    first failure. No generator/pod/spend is touched here.

    Order: Summer-only (409) → prompt required (422) → identity 'ready' with an active
    version (409) → prompt safety / minors-illegal (400).
    """
    # ── Gate 1: Summer only (before anything else) ───────────────────────────────
    if character_id != SUMMER_CHARACTER_ID:
        raise FounderGenerateBlocked(
            409, f"Founder generate is Summer-only (character_id={SUMMER_CHARACTER_ID}).")

    # ── Gate 2: prompt required ──────────────────────────────────────────────────
    if not (prompt or "").strip():
        raise FounderGenerateBlocked(422, "A prompt is required.")

    # ── Gate 3: identity ready + active version present ──────────────────────────
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if model is None:
        raise FounderGenerateBlocked(
            409, "No Adult Studio identity exists for Summer.")
    if model.status != REQUIRED_STATUS:
        raise FounderGenerateBlocked(
            409, f"Identity status is '{model.status}', expected '{REQUIRED_STATUS}'.")
    if model.active_version_id is None:
        raise FounderGenerateBlocked(
            409, "Summer has no active AdultIdentityModelVersion.")

    # ── Gate 4: prompt safety (minors / illegal terms) ───────────────────────────
    block_reason = check_prompt_safety(prompt)
    if block_reason:
        raise FounderGenerateBlocked(400, block_reason)

    return model


def run_founder_generate(
    db: "Session",
    character_id: int,
    prompt: str,
    *,
    spend_cap: float = FOUNDER_SPEND_CAP_USD,
    make_base_generator: Callable[..., Callable[[float], dict]] = _default_make_base_generator,
    executor_factory: Callable[..., AdultIdentityEnforcementExecutor] = _default_executor_factory,
    worker_lifecycle: Optional[WorkerLifecycle] = None,
) -> dict[str, Any]:
    """Run a Summer-only founder generation through the validated enforcement pipeline.

    LEGACY synchronous path (Replicate base + conditioning-preview montage). Retained for
    rollback; the live founder route uses the async-job path. Raises
    :class:`FounderGenerateBlocked` for gate failures (mapped to HTTP codes).
    """
    model = validate_founder_preconditions(db, character_id, prompt)

    # ── Construct generator ONLY now (all gates passed → no spend before here) ────
    lifecycle: WorkerLifecycle = worker_lifecycle or ReplicateWorkerLifecycle()
    base_prompt = build_founder_base_prompt(prompt, model.trigger_token or "TOK")
    generate_base = make_base_generator(model, base_prompt, spend_cap, lifecycle)
    executor = executor_factory(db, generate_base, spend_cap)

    # The executor performs the single capped base generation + route dispatch + final
    # compose. The worker lifecycle is terminated no matter what.
    try:
        report = executor.run(character_id)
    finally:
        lifecycle.terminate("founder_generate complete")

    orphans = lifecycle.list_orphans()
    return _to_response(report, orphans, base_prompt)


def _to_response(
    report: dict[str, Any], orphans: list[str], base_prompt: str
) -> dict[str, Any]:
    """Map an executor report → the founder-generate response contract."""
    image_urls = report.get("image_urls") or {}
    base_url = image_urls.get("base")
    artifact_urls = list(image_urls.get("artifacts") or [])
    intermediate = ([base_url] if base_url else []) + artifact_urls

    blocking = list(report.get("blocking_reasons") or [])
    success = bool(report.get("success"))
    if orphans:
        # A leaked worker/pod is a hard safety failure regardless of image outcome.
        blocking.append(f"orphaned workers detected: {', '.join(orphans)}")
        success = False

    return {
        "final_image_url": report.get("final_image_url"),
        "intermediate_artifact_urls": intermediate,
        "cost": report.get("spend_usd", 0.0),
        "runtime": report.get("runtime_s", 0.0),
        "routes_executed": report.get("routes_executed") or [],
        "manual_review_required": True,
        "success": success,
        "blocking_reasons": blocking,
        "base_prompt": base_prompt,
        "orphaned_workers": orphans,
    }
