#!/usr/bin/env python3
"""Automated Adult Studio inference validation harness (Phase 3, Sprint 5).

The SYSTEM — not the user — decides whether a validation run *technically* passed. This
harness runs the fixed benchmark set for an existing AdultIdentityModelVersion through the
existing inference/validation script path (validate_summer_adult_studio_inference), then
applies automatic NON-VISION checks and emits a structured report with a machine verdict.

Scope guards (Sprint 5 rules):
  - Summer ONLY (character_id=60, AdultIdentityModel id=1). Refuses any other character.
  - Admin/internal only. NOT the normal image generator, NOT Canon Studio, NOT a UI,
    NOT user-facing. No tattoo inpaint. No RunPod, no ComfyUI. No training.
  - Hard spend cap $0.10 (enforced inside the generation path).

The harness does NOT score visual quality — there is no computer-vision scoring yet. Every
run is marked ``manual_review_required=true`` and each image carries a ``visual_pass``
placeholder (null) + ``manual_notes`` for a human to fill in later.

Modes:
  live   (default) — generate via the inference path (spends, capped).
  replay --report <path> — apply checks to an existing inference report (NO spend).

Writes scripts/summer_adult_studio_validation_report.json.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import validate_summer_adult_studio_inference as infer  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.adult_identity import AdultIdentityModel  # noqa: E402
from app.models.character import Character  # noqa: E402

IDENTITY_ID = 1
EXPECTED_CHARACTER_ID = 60          # Summer ONLY
SPEND_CAP_USD = 0.10
BENCHMARK_KEYS = [p[0] for p in infer.PROMPTS]
HARNESS_REPORT = Path(__file__).resolve().parent / "summer_adult_studio_validation_report.json"

NOTES = ("Automatic checks cover TECHNICAL completion only (prompts ran, URLs returned, "
         "cost within cap, no provider errors, active version used). Visual fidelity, "
         "identity likeness, and anatomy are NOT auto-scored and require manual review.")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _enforce_summer(identity_id):
    """Refuse to validate anything but Summer (character_id=60)."""
    db = SessionLocal()
    try:
        model = db.get(AdultIdentityModel, identity_id)
        if model is None:
            raise SystemExit(f"FATAL: AdultIdentityModel {identity_id} not found")
        if model.character_id != EXPECTED_CHARACTER_ID:
            raise SystemExit(
                f"FATAL: harness is Summer-only (expected character_id="
                f"{EXPECTED_CHARACTER_ID}, got {model.character_id})")
        ch = db.get(Character, model.character_id)
        return model.character_id, (ch.name if ch else None), model.active_version_id
    finally:
        db.close()


def build_benchmark_rows(report):
    """One row per benchmark prompt with pass/fail placeholders + notes."""
    by_key = {g.get("key"): g for g in report.get("generations", [])}
    rows = []
    for key in BENCHMARK_KEYS:
        g = by_key.get(key, {})
        rows.append({
            "key": key,
            "prompt": g.get("prompt"),
            "size": g.get("size"),
            "status": g.get("status", "missing"),
            "image_url": g.get("image_url"),
            "predict_time_s": g.get("predict_time_s"),
            "cost_usd": g.get("cost_usd"),
            "error": g.get("error"),
            # placeholders — NOT auto-scored this sprint:
            "visual_pass": None,
            "manual_notes": "",
        })
    return rows


def run_checks(report, rows):
    """Automatic NON-VISION checks. Returns (checks_dict, verdict)."""
    succeeded = {r["key"] for r in rows if r["status"] == "succeeded"}
    total_cost = report.get("generation_cost_usd_total") or 0.0
    checks = {
        "all_prompts_completed": all(k in succeeded for k in BENCHMARK_KEYS),
        "all_urls_returned": all(
            (r["status"] == "succeeded" and bool(r["image_url"])) for r in rows),
        "cost_under_cap": total_cost <= SPEND_CAP_USD,
        "no_errors": all(
            (r["status"] == "succeeded" and not r["error"]) for r in rows),
        "active_version_id_used": (
            report.get("model_version_id") is not None
            and report.get("model_version_id") == report.get("active_version_id")),
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"
    return checks, verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["live", "replay"], default="live")
    ap.add_argument("--report", help="inference report path for replay mode")
    ap.add_argument("--no-disable-safety", action="store_true",
                    help="do NOT bypass the base SDXL NSFW safety checker")
    args = ap.parse_args()

    t0 = time.time()
    character_id, character_name, active_version_id = _enforce_summer(IDENTITY_ID)
    log(f"target: {character_name} (character_id={character_id}, identity={IDENTITY_ID}, "
        f"active_version_id={active_version_id})")

    if args.mode == "replay":
        path = Path(args.report or infer.REPORT)
        inference_report = json.loads(path.read_text())
        log(f"replay mode — checks only, no spend (source: {path.name})")
    else:
        # 18+ admin benchmark: bypass base NSFW false-positives by default (deterministic).
        disable_safety = not args.no_disable_safety
        log(f"live mode — generating benchmark (disable_safety={disable_safety}, cap=${SPEND_CAP_USD})")
        inference_report = infer.run_benchmark(
            IDENTITY_ID, spend_cap=SPEND_CAP_USD, disable_safety=disable_safety)

    rows = build_benchmark_rows(inference_report)
    checks, verdict = run_checks(inference_report, rows)

    harness_report = {
        "harness": "adult_studio_validation_harness",
        "mode": args.mode,
        "identity_id": IDENTITY_ID,
        "character_id": character_id,
        "character_name": character_name,
        "provider": inference_report.get("provider"),
        "model_version_id": inference_report.get("model_version_id"),
        "active_version_id": inference_report.get("active_version_id", active_version_id),
        "runnable_version": inference_report.get("runnable_version"),
        "trigger_token": inference_report.get("trigger_token"),
        "disable_safety_checker": inference_report.get("disable_safety_checker"),
        "spend_cap_usd": SPEND_CAP_USD,
        "generation_cost_usd_total": inference_report.get("generation_cost_usd_total"),
        "generation_runtime_s": inference_report.get("runtime_s"),
        "harness_runtime_s": round(time.time() - t0, 1),
        "benchmark": rows,
        "automatic_checks": checks,
        "technical_verdict": verdict,
        "manual_review_required": True,   # visual quality never auto-passed this sprint
        "inference_result": inference_report.get("result"),
        "inference_error": inference_report.get("error"),
        "notes": NOTES,
    }
    HARNESS_REPORT.write_text(json.dumps(harness_report, indent=2))
    log(f"technical_verdict={verdict} manual_review_required=True "
        f"cost=${harness_report['generation_cost_usd_total']}")
    log("CHECKS: " + json.dumps(checks))
    log("HARNESS_REPORT written: " + str(HARNESS_REPORT.name))
    print(json.dumps(harness_report, indent=2), flush=True)


if __name__ == "__main__":
    main()
