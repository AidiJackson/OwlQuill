#!/usr/bin/env python3
"""ADMIN-ONLY inference validation for Summer's Adult Studio LoRA (Phase 3, Sprint 4).

Validates whether the newly trained Summer AdultIdentityModelVersion (active, id=1) can
be used for inference. Generates a TINY fixed validation set (4 images) against the
trained Replicate version resolved from the recorded training job — NOT the normal image
generator, NOT Canon Studio, NOT a UI, NOT user-facing. No tattoo inpaint (LoRA artifact
inference only). No RunPod, no ComfyUI.

Hard spend cap: $0.10 (stops before any generation that would cross it). The trained LoRA
trigger token is 'TOK' (training used token_string='TOK').

Writes scripts/summer_adult_studio_inference_report.json.
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

# 4 fixed validation prompts (portrait 832x1216).
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

rep = {"identity_id": IDENTITY_ID, "spend_cap_usd": SPEND_CAP_USD,
       "lora_scale": LORA_SCALE, "trigger_token": "TOK",
       "disable_safety_checker": DISABLE_SAFETY, "generations": []}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def resolve_version(db):
    """Resolve the runnable trained version handle from the recorded active version."""
    model = db.get(AdultIdentityModel, IDENTITY_ID)
    ver = db.get(AdultIdentityModelVersion, model.active_version_id)
    job = (db.query(AdultIdentityTrainingJob)
           .filter(AdultIdentityTrainingJob.version_id == ver.id).first())
    rep["model_version_id"] = ver.id
    rep["model_artifact_uri"] = ver.lora_weights_uri
    rep["provider"] = job.provider
    rep["provider_job_id"] = job.external_job_id
    rep["training_cost_usd"] = job.cost_usd
    # The .tar is the weights; the runnable handle is the training output.version.
    tr = requests.get(f"{API}/trainings/{job.external_job_id}", headers=H, timeout=30).json()
    version = (tr.get("output") or {}).get("version")
    if not version:
        raise SystemExit("FATAL: could not resolve runnable trained version handle")
    version_hash = version.split(":")[-1]
    rep["runnable_version"] = version
    log(f"resolved runnable version: {version}")
    return version_hash


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


def generate(version_hash):
    # Optional filter (comma-separated keys) to re-run only specific prompts.
    only = {k.strip() for k in os.environ.get("SUMMER_INFER_ONLY", "").split(",") if k.strip()}
    # Count any spend already recorded by a prior run (the hard cap is cumulative).
    running_cost = round(sum(g.get("cost_usd", 0.0) or 0.0 for g in rep["generations"]), 5)
    t0 = time.time()
    for key, prompt, w, h in PROMPTS:
        if only and key not in only:
            continue
        # Hard cap guard BEFORE spending on the next image.
        if running_cost >= SPEND_CAP_USD:
            log(f"SPEND CAP reached (${running_cost:.4f}); stopping before '{key}'")
            rep["generations"].append({"key": key, "status": "skipped_spend_cap"})
            continue
        body = {"version": version_hash, "input": {
            "prompt": prompt, "negative_prompt": NEGATIVE, "width": w, "height": h,
            "num_outputs": 1, "num_inference_steps": 30, "guidance_scale": 7.5,
            "lora_scale": LORA_SCALE, "seed": 1234,
            "disable_safety_checker": DISABLE_SAFETY,
        }}
        pred = submit_prediction(body, key)
        if "urls" not in pred:
            log(f"gen {key} submit error: {pred}")
            rep["generations"].append({"key": key, "status": "submit_error", "error": pred})
            continue
        log(f"gen {key} id={pred['id']} {w}x{h} lora_scale={LORA_SCALE}")
        done = poll(pred["urls"]["get"], f"gen:{key}")
        out = done.get("output")
        url = out[0] if isinstance(out, list) and out else out
        pt = (done.get("metrics") or {}).get("predict_time") or 0.0
        cost = round(pt * INFER_HW_RATE, 5)
        running_cost += cost
        rep["generations"].append({
            "key": key, "prompt": prompt, "size": f"{w}x{h}", "status": done["status"],
            "image_url": url, "predict_time_s": pt, "cost_usd": cost,
            "error": done.get("error"),
        })
        log(f"gen {key} {done['status']} predict={pt:.1f}s cost=${cost:.5f} running=${running_cost:.5f}")
    rep["generation_cost_usd_total"] = round(running_cost, 5)
    rep["runtime_s"] = round(time.time() - t0, 1)


def main():
    if not TOKEN:
        rep["result"] = "ABORTED"; rep["error"] = "REPLICATE_API_TOKEN not set"
        REPORT.write_text(json.dumps(rep, indent=2)); log("ABORT: no token"); return
    db = SessionLocal()
    try:
        version_hash = resolve_version(db)
        generate(version_hash)
        ok = [g for g in rep["generations"] if g.get("status") == "succeeded"]
        rep["images_succeeded"] = len(ok)
        rep["image_urls"] = [g["image_url"] for g in ok if g.get("image_url")]
        rep["result"] = "SUCCESS" if len(ok) == len(PROMPTS) else "PARTIAL"
    except SystemExit as e:
        rep.setdefault("result", "ABORTED"); rep.setdefault("error", str(e)); log(f"ABORT: {e}")
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        rep["result"] = "EXCEPTION"; rep["error"] = repr(e)
    finally:
        db.close()
        REPORT.write_text(json.dumps(rep, indent=2))
        log("REPORT:\n" + json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
