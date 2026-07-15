#!/usr/bin/env python3
"""THROWAWAY inference-only lora_scale sweep on the existing v2 Summer LoRA.

NO training. NO Ficshon changes. Runs the already-trained summer-sdxl-lora-v2
version at lora_scale 0.78 / 0.82 / 0.88 across 3 prompts, fixed seed for
comparability.

Crash-safe persistence (this rerun):
  * the report is (atomically) rewritten after EVERY generation,
  * image URLs are recorded the instant a prediction succeeds,
  * the report is also flushed after every COMPLETED scale,
  * prediction ids + a line-buffered run log are written so an interrupted
    run can be inspected/resumed.
Writes scripts/summer_lora_sweep_report.json and scripts/summer_lora_sweep_run.log.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.replicate.com/v1"
# Trained v2 version (from summer_lora_v2_report.json) — inference only.
VERSION_HASH = "ce6df375ac0f7de1507ed92206436302dffece000caab9bfd15eb7d2ce1faea9"
HERE = Path(__file__).resolve().parent
REPORT_PATH = HERE / "summer_lora_sweep_report.json"
TMP_PATH = HERE / "summer_lora_sweep_report.json.tmp"
LOG_PATH = HERE / "summer_lora_sweep_run.log"
INFER_RATE = 0.000975  # gpu-l40s $/s

SCALES = [0.78, 0.82, 0.88]
SEED = 1234
PROMPTS = [
    ("bikini_waist_up", "a photo of TOK, an adult woman in a light blue bikini, waist-up portrait, upper body, head and shoulders clearly visible, looking at camera, sunny beach with ocean behind, natural daylight, photorealistic"),
    ("bikini_full_body", "a photo of TOK, an adult woman in a light blue bikini standing on a sandy beach, full body, ocean and blue sky background, both arms visible, natural daylight, photorealistic"),
    ("black_dress_portrait", "a photo of TOK, an adult woman wearing an elegant black dress, waist-up portrait, upper body, face clearly visible, looking at camera, soft studio lighting, photorealistic"),
]
NEGATIVE = "deformed, disfigured, extra limbs, extra fingers, bad anatomy, blurry, lowres, watermark, text, multiple people, grey background, plain background"

TOKEN = os.environ.get("REPLICATE_API_TOKEN")
if not TOKEN:
    print("FATAL: REPLICATE_API_TOKEN not set", flush=True)
    sys.exit(1)
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

_logf = open(LOG_PATH, "a", buffering=1)  # line-buffered: survives a hard crash


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    _logf.write(line + "\n")


def save(rep):
    """Atomic report write: write temp then rename so a crash mid-write
    can never leave a half-written/corrupt report."""
    TMP_PATH.write_text(json.dumps(rep, indent=2))
    os.replace(TMP_PATH, REPORT_PATH)


def recompute_totals(rep):
    ptime = sum((r.get("predict_time") or 0) for r in rep["results"])
    rep["total_predict_time_s"] = round(ptime, 2)
    rep["total_cost_usd_est"] = round(ptime * INFER_RATE, 4)


def poll(get_url, label, timeout_s=600):
    t0 = time.time()
    while True:
        obj = requests.get(get_url, headers={"Authorization": H["Authorization"]}, timeout=30).json()
        st = obj["status"]
        if st in ("succeeded", "failed", "canceled"):
            return obj
        if time.time() - t0 > timeout_s:
            raise SystemExit(f"{label} timed out")
        time.sleep(6)


def main():
    rep = {
        "version": f"summer-sdxl-lora-v2:{VERSION_HASH[:12]}",
        "version_hash": VERSION_HASH,
        "seed": SEED,
        "scales": SCALES,
        "status": "running",
        "completed_scales": [],
        "results": [],
        "image_urls": [],
    }
    save(rep)  # initial flush: a report file exists from t=0
    t0 = time.time()
    for scale in SCALES:
        for key, prompt in PROMPTS:
            body = {"version": VERSION_HASH, "input": {
                "prompt": prompt, "negative_prompt": NEGATIVE,
                "width": 832, "height": 1216, "num_outputs": 1,
                "num_inference_steps": 32, "guidance_scale": 7.5,
                "lora_scale": scale, "seed": SEED}}
            pred = requests.post(f"{API}/predictions", headers=H, json=body, timeout=60).json()
            pred_id = pred.get("id")
            # Persist submission immediately (prediction id captured before polling).
            entry = {"scale": scale, "key": key, "prediction_id": pred_id,
                     "status": "submitted", "image_url": None, "error": None,
                     "predict_time": None}
            rep["results"].append(entry)
            save(rep)
            log(f"submitted {key} @ lora_scale={scale} id={pred_id}")

            done = poll(pred["urls"]["get"], f"{key}@{scale}")
            out = done.get("output")
            url = out[0] if isinstance(out, list) and out else out
            entry["status"] = done["status"]
            entry["image_url"] = url
            entry["error"] = done.get("error")
            entry["predict_time"] = (done.get("metrics") or {}).get("predict_time")
            if url:
                rep["image_urls"].append(url)
            recompute_totals(rep)
            save(rep)  # image URL written the instant generation completes
            log(f"{key} @ lora_scale={scale} -> {done['status']} {url or done.get('error')}")
        rep["completed_scales"].append(scale)
        save(rep)  # report flushed after every completed scale
        log(f"COMPLETED scale {scale} ({len(rep['completed_scales'])}/{len(SCALES)})")

    recompute_totals(rep)
    rep["wall_clock_s"] = int(time.time() - t0)
    rep["status"] = "succeeded"
    save(rep)
    log("DONE")
    log(json.dumps(rep, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        try:
            partial = {"fatal_error": str(exc), "status": "crashed"}
            if REPORT_PATH.exists():
                partial = {**json.loads(REPORT_PATH.read_text()),
                           "fatal_error": str(exc), "status": "crashed"}
            REPORT_PATH.write_text(json.dumps(partial, indent=2))
        except Exception:
            pass
        sys.exit(1)
