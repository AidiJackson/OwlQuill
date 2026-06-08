#!/usr/bin/env python3
"""ADMIN-ONLY inference validation for an Adult Studio LoRA (Phase 3, Sprint 4; refactored S5).

Validates whether a trained AdultIdentityModelVersion can be used for inference. Generates a
TINY fixed validation set against the trained Replicate version resolved from the recorded
training job — NOT the normal image generator, NOT Canon Studio, NOT a UI, NOT user-facing.
No tattoo inpaint (LoRA artifact inference only). No RunPod, no ComfyUI.

Hard spend cap: $0.10 (stops before any generation that would cross it). The trained LoRA
trigger token is 'TOK' (training used token_string='TOK').

Sprint 5 refactor: the generation path is exposed as importable functions
(``resolve_runnable_version`` / ``generate_set`` / ``run_benchmark``) so the automated
validation harness generates "through the existing validation/inference script path" rather
than duplicating it. Running this module directly preserves the original Sprint 4 CLI.

Writes scripts/summer_adult_studio_inference_report.json when run as a CLI.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.database import SessionLocal  # noqa: E402
from app.models.adult_identity import (  # noqa: E402
    AdultIdentityModel,
    AdultIdentityModelVersion,
    AdultIdentityTrainingJob,
)

API = "https://api.replicate.com/v1"
IDENTITY_ID = 1
SPEND_CAP_USD = 0.10
INFER_HW_RATE = 0.000975  # gpu-l40s $/s (matches proven Summer runs)
LORA_SCALE = 0.70
# 18+ admin validation only: optionally bypass the base SDXL NSFW safety checker, which
# false-positives on benign clothed prompts. Default OFF; opt in via env for this gated,
# non-user-facing validation. Never wired to any UI or public path.
DISABLE_SAFETY = os.environ.get("SUMMER_INFER_DISABLE_SAFETY", "").lower() in ("1", "true", "yes")
REPORT = Path(__file__).resolve().parent / "summer_adult_studio_inference_report.json"

TOKEN = os.environ.get("REPLICATE_API_TOKEN")
H = {"Authorization": f"Bearer {TOKEN}"}

# Summer identity description (from the proven Summer LoRA runs). Trigger token = TOK.
SUBJECT = "an adult woman with long blonde hair and blue eyes"
NEGATIVE = ("deformed, disfigured, extra limbs, extra fingers, bad anatomy, blurry, "
            "lowres, watermark, text, multiple people, child, minor")

# 4 fixed validation prompts (portrait 832x1216). This IS the benchmark set.
PROMPTS = [
    ("portrait_headshot",
     f"a photo of TOK, {SUBJECT}, headshot portrait, face clearly visible, looking at "
     f"camera, soft natural lighting, photorealistic", 832, 1216),
    ("casual_sleeveless",
     f"a photo of TOK, {SUBJECT}, wearing a casual sleeveless top, arms visible, "
     f"waist-up, natural daylight, photorealistic", 832, 1216),
    ("blue_bikini_full_body",
     f"a photo of TOK, {SUBJECT}, in a light blue bikini standing on a sandy beach, "
     f"full body, ocean and blue sky background, natural daylight, photorealistic", 832, 1216),
    ("black_dress_portrait",
     f"a photo of TOK, {SUBJECT}, wearing an elegant black dress, waist-up portrait, "
     f"face clearly visible, soft studio lighting, photorealistic", 832, 1216),
]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def resolve_runnable_version(db, identity_id):
    """Resolve the runnable trained version handle from the recorded active version.

    Returns a metadata dict (model_version_id, active_version_id, runnable_version,
    version_hash, provider, etc.). Raises SystemExit if no runnable version exists.
    """
    model = db.get(AdultIdentityModel, identity_id)
    if model is None:
        raise SystemExit(f"FATAL: AdultIdentityModel {identity_id} not found")
    ver = db.get(AdultIdentityModelVersion, model.active_version_id)
    if ver is None:
        raise SystemExit(f"FATAL: identity {identity_id} has no active version")
    job = (db.query(AdultIdentityTrainingJob)
           .filter(AdultIdentityTrainingJob.version_id == ver.id).first())
    if job is None or not job.external_job_id:
        raise SystemExit(f"FATAL: no training job recorded for version {ver.id}")
    # The .tar is the weights; the runnable handle is the training output.version.
    tr = requests.get(f"{API}/trainings/{job.external_job_id}", headers=H, timeout=30).json()
    version = (tr.get("output") or {}).get("version")
    if not version:
        raise SystemExit("FATAL: could not resolve runnable trained version handle")
    log(f"resolved runnable version: {version}")
    return {
        "identity_id": identity_id,
        "model_version_id": ver.id,
        "active_version_id": model.active_version_id,
        "model_artifact_uri": ver.lora_weights_uri,
        "provider": job.provider,
        "provider_job_id": job.external_job_id,
        "training_cost_usd": job.cost_usd,
        "runnable_version": version,
        "version_hash": version.split(":")[-1],
    }


def submit_prediction(body, key, max_retries=4):
    """POST a prediction, retrying on HTTP 429 throttling (respects retry_after)."""
    for attempt in range(max_retries + 1):
        pred = requests.post(f"{API}/predictions",
                             headers={**H, "Content-Type": "application/json"},
                             json=body, timeout=60).json()
        if "urls" in pred:
            return pred
        if pred.get("status") == 429 and attempt < max_retries:
            wait = int(pred.get("retry_after", 6)) + 2
            log(f"gen {key} throttled (429); retrying in {wait}s "
                f"(attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        return pred  # non-retryable / out of retries
    return pred


def poll(get_url, label, timeout_s=600):
    t0 = time.time()
    while True:
        obj = requests.get(get_url, headers=H, timeout=30).json()
        st = obj["status"]
        if st in ("succeeded", "failed", "canceled"):
            return obj
        if time.time() - t0 > timeout_s:
            raise SystemExit(f"{label} timed out")
        time.sleep(6)


def generate_set(version_hash, prompts, *, spend_cap=SPEND_CAP_USD,
                 disable_safety=DISABLE_SAFETY, only=None, prior_cost=0.0):
    """Generate one image per prompt against ``version_hash``.

    Enforces a cumulative hard spend cap. Returns
    {generations, generation_cost_usd_total, runtime_s}. Never raises on a single
    generation failure — failures are recorded per-item so the caller/harness can judge.
    """
    only = set(only or [])
    running_cost = round(prior_cost, 5)
    generations = []
    t0 = time.time()
    for key, prompt, w, h in prompts:
        if only and key not in only:
            continue
        if running_cost >= spend_cap:  # hard cap guard BEFORE spending
            log(f"SPEND CAP reached (${running_cost:.4f}); stopping before '{key}'")
            generations.append({"key": key, "status": "skipped_spend_cap"})
            continue
        body = {"version": version_hash, "input": {
            "prompt": prompt, "negative_prompt": NEGATIVE, "width": w, "height": h,
            "num_outputs": 1, "num_inference_steps": 30, "guidance_scale": 7.5,
            "lora_scale": LORA_SCALE, "seed": 1234,
            "disable_safety_checker": disable_safety,
        }}
        pred = submit_prediction(body, key)
        if "urls" not in pred:
            log(f"gen {key} submit error: {pred}")
            generations.append({"key": key, "prompt": prompt, "status": "submit_error",
                                "image_url": None, "cost_usd": 0.0, "error": pred})
            continue
        log(f"gen {key} id={pred['id']} {w}x{h} lora_scale={LORA_SCALE}")
        done = poll(pred["urls"]["get"], f"gen:{key}")
        out = done.get("output")
        url = out[0] if isinstance(out, list) and out else out
        pt = (done.get("metrics") or {}).get("predict_time") or 0.0
        cost = round(pt * INFER_HW_RATE, 5)
        running_cost += cost
        generations.append({
            "key": key, "prompt": prompt, "size": f"{w}x{h}", "status": done["status"],
            "image_url": url, "predict_time_s": pt, "cost_usd": cost,
            "error": done.get("error"),
        })
        log(f"gen {key} {done['status']} predict={pt:.1f}s cost=${cost:.5f} running=${running_cost:.5f}")
    return {
        "generations": generations,
        "generation_cost_usd_total": round(running_cost, 5),
        "runtime_s": round(time.time() - t0, 1),
    }


def run_benchmark(identity_id=IDENTITY_ID, *, prompts=None, spend_cap=SPEND_CAP_USD,
                  disable_safety=DISABLE_SAFETY, only=None):
    """Resolve the active version and run the benchmark set. Returns a structured dict.

    This is the single reusable entry point used by both this CLI and the validation
    harness. Opens and closes its own DB session.
    """
    if not TOKEN:
        return {"result": "ABORTED", "error": "REPLICATE_API_TOKEN not set",
                "identity_id": identity_id, "generations": []}
    prompts = prompts if prompts is not None else PROMPTS
    db = SessionLocal()
    try:
        meta = resolve_runnable_version(db, identity_id)
        gen = generate_set(meta["version_hash"], prompts, spend_cap=spend_cap,
                           disable_safety=disable_safety, only=only)
        ok = [g for g in gen["generations"] if g.get("status") == "succeeded"]
        report = {
            **meta,
            "spend_cap_usd": spend_cap,
            "lora_scale": LORA_SCALE,
            "trigger_token": "TOK",
            "disable_safety_checker": disable_safety,
            **gen,
            "images_succeeded": len(ok),
            "image_urls": [g["image_url"] for g in ok if g.get("image_url")],
            "prompt_count": len([p for p in prompts if not only or p[0] in set(only)]),
        }
        report["result"] = "SUCCESS" if len(ok) == report["prompt_count"] else "PARTIAL"
        return report
    except SystemExit as e:
        return {"result": "ABORTED", "error": str(e), "identity_id": identity_id,
                "generations": []}
    finally:
        db.close()


def main():
    only = {k.strip() for k in os.environ.get("SUMMER_INFER_ONLY", "").split(",") if k.strip()}
    rep = run_benchmark(IDENTITY_ID, only=only or None)
    REPORT.write_text(json.dumps(rep, indent=2))
    log("REPORT:\n" + json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
