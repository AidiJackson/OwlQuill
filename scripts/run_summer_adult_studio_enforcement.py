#!/usr/bin/env python3
"""Run the Adult Studio tattoo-enforcement EXECUTOR v1 — Summer only (Phase 3, S7).

ADMIN/INTERNAL ONLY. Wires the existing Replicate active-LoRA inference path as the
executor's single base-image generator, then runs the executor against Summer
(character_id=60): consume DB enforcement plan → generate ONE base image → dispatch the
ip_adapter + controlnet_canny routes → compose a final preview → save a structured
execution report.

NOT the normal image generator, NOT Canon Studio, NOT a UI, NOT user-facing, NOT public.
Hard spend cap $0.15 (the single base generation is the only spend). Stops immediately on
cap breach. The final image is a labeled PREVIEW (base + route conditioning artifacts);
the diffusion denoise pass is deferred to the GPU backend (diffusion_pass="deferred").
manual_review_required is always true.

Writes scripts/summer_adult_studio_enforcement_report.json. Exit 0 iff success.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import validate_summer_adult_studio_inference as infer  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.adult_identity import AdultIdentityModel  # noqa: E402
from app.models.character import Character  # noqa: E402
from app.services.adult_identity_enforcement_executor import (  # noqa: E402
    SUMMER_CHARACTER_ID,
    AdultIdentityEnforcementExecutor,
)

IDENTITY_ID = 1
SPEND_CAP_USD = 0.15
REPORT = Path(__file__).resolve().parent / "summer_adult_studio_enforcement_report.json"

# A single base prompt that exposes BOTH arms (Phase 0: "arms at sides" exposes the
# forearm) so the validation image is relevant to both tattoo routes. Trigger token TOK.
BASE_PROMPT = (
    "a photo of TOK, an adult woman with long blonde hair and blue eyes, standing, "
    "arms relaxed at her sides, both arms fully visible, wearing a sleeveless top, "
    "natural daylight, full body, photorealistic")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def make_base_generator():
    """Return a ``(spend_cap)->dict`` that generates ONE base image via the LoRA path."""
    def generate_base(spend_cap):
        # disable_safety: 18+ admin validation only (base SDXL NSFW checker false-positives).
        rep = infer.run_benchmark(
            IDENTITY_ID,
            prompts=[("enforcement_base", BASE_PROMPT, 832, 1216)],
            spend_cap=min(spend_cap, SPEND_CAP_USD),
            disable_safety=True,
        )
        gens = rep.get("generations") or []
        g = gens[0] if gens else {}
        return {
            "status": g.get("status", rep.get("result", "error")),
            "image_url": g.get("image_url"),
            "cost_usd": g.get("cost_usd", rep.get("generation_cost_usd_total", 0.0)),
            "prompt": BASE_PROMPT,
            "predict_time_s": g.get("predict_time_s"),
            "error": g.get("error") or rep.get("error"),
            "runnable_version": rep.get("runnable_version"),
        }
    return generate_base


def main():
    db = SessionLocal()
    try:
        ch = db.get(Character, SUMMER_CHARACTER_ID)
        model = (db.query(AdultIdentityModel)
                 .filter(AdultIdentityModel.character_id == SUMMER_CHARACTER_ID).first())
        if ch is None or model is None:
            raise SystemExit("FATAL: Summer (character_id=60) identity not found")
        log(f"target: {ch.name} (character_id={SUMMER_CHARACTER_ID}) — cap=${SPEND_CAP_USD}")

        executor = AdultIdentityEnforcementExecutor(
            db, generate_base=make_base_generator(), spend_cap=SPEND_CAP_USD)
        report = executor.run(SUMMER_CHARACTER_ID)
    finally:
        db.close()

    REPORT.write_text(json.dumps(report, indent=2))
    log(f"success={report['success']} spend=${report['spend_usd']} "
        f"runtime={report['runtime_s']}s")
    base = report.get("base_image") or {}
    log(f"base_image: status={base.get('status')} url={base.get('image_url')}")
    for r in report["routes_executed"]:
        log(f"  route {r['route']} [{r.get('region')}] status={r['status']} "
            f"artifact={r.get('artifact_url')}")
    log(f"final_image_url={report['final_image_url']}")
    if report["blocking_reasons"]:
        for r in report["blocking_reasons"]:
            log(f"  BLOCKED: {r}")
    log("REPORT written: " + REPORT.name)
    print(json.dumps(report, indent=2), flush=True)
    sys.exit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()
