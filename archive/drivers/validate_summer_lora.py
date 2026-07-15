#!/usr/bin/env python3
"""THROWAWAY validation experiment — Summer SDXL LoRA on Replicate.

NOT part of Ficshon. Imports the app only to read Summer's prepared manifest and
load canon image bytes (read-only). Trains a per-character SDXL LoRA on Replicate
from the existing Adult Studio training-pack images, then generates 3 test images.

Run from backend/ with REPLICATE_API_TOKEN in the environment. Writes a JSON
report to scripts/summer_lora_report.json and streams progress to stdout.

Nothing here is wired into Ficshon. Delete after validation.
"""
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import requests

API = "https://api.replicate.com/v1"
SDXL_TRAINER_VERSION = "7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc"
OWNER = "aidijackson"
DEST_MODEL = f"{OWNER}/summer-sdxl-lora"
CHARACTER_ID = 60
REPORT_PATH = Path(__file__).resolve().parent / "summer_lora_report.json"

# Public Replicate per-second rates (USD) — used only to estimate cost from the
# returned predict_time. Raw predict_time is also reported for verification.
RATE = {"gpu-a100-large": 0.001400, "gpu-l40s": 0.000975, "gpu-t4": 0.000225}
TRAIN_HW = "gpu-a100-large"   # stability-ai/sdxl trainer runs on A100 80GB
INFER_HW = "gpu-l40s"         # destination model inference hardware

TOKEN = os.environ.get("REPLICATE_API_TOKEN")
if not TOKEN:
    print("FATAL: REPLICATE_API_TOKEN not set", flush=True)
    sys.exit(1)
H = {"Authorization": f"Bearer {TOKEN}"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 1. Build images-only training zip from the existing pack ────────────
def build_training_zip():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.core.database import SessionLocal
    from app.models.adult_studio import AdultStudioIdentity
    from app.core.storage import load_image_bytes

    db = SessionLocal()
    rec = (
        db.query(AdultStudioIdentity)
        .filter(AdultStudioIdentity.character_id == CHARACTER_ID)
        .first()
    )
    if not rec or rec.status != "ready":
        raise SystemExit("Summer Adult Studio identity is not 'ready'")
    manifest = rec.training_notes_json or {}
    db.close()

    # Person photos only — drop isolated 'mark:*' tattoo crops (they teach the
    # model floating-tattoo artifacts). Tattoos are still learned from the body
    # shots that include them.
    refs = [r for r in (manifest.get("refs") or []) if not r.get("role", "").startswith("mark:")]
    used_roles, dropped = [], [r.get("role") for r in (manifest.get("refs") or []) if r.get("role", "").startswith("mark:")]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in refs:
            role, url = r.get("role"), r.get("url")
            if not url:
                continue
            data = load_image_bytes(url)
            zf.writestr(f"{role}.png", data)
            used_roles.append(role)
    log(f"training zip: {len(used_roles)} images {used_roles}; dropped marks {dropped}")
    return buf.getvalue(), used_roles, dropped


# ── 2. Upload zip to Replicate Files API ────────────────────────────────
def upload_zip(zip_bytes):
    r = requests.post(
        f"{API}/files", headers=H,
        files={"content": ("summer_train.zip", zip_bytes, "application/zip")},
        timeout=120,
    )
    r.raise_for_status()
    url = r.json()["urls"]["get"]
    log(f"uploaded training zip ({len(zip_bytes)} bytes) -> {url}")
    return url


# ── 3. Ensure destination model exists (private) ────────────────────────
def ensure_destination():
    r = requests.get(f"{API}/models/{DEST_MODEL}", headers=H, timeout=30)
    if r.status_code == 200:
        log(f"destination model exists: {DEST_MODEL}")
        return
    r = requests.post(
        f"{API}/models", headers=H,
        json={
            "owner": OWNER, "name": "summer-sdxl-lora", "visibility": "private",
            "hardware": INFER_HW,
            "description": "Throwaway Summer SDXL LoRA validation (delete after).",
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        raise SystemExit(f"could not create destination model: {r.status_code} {r.text}")
    log(f"created destination model: {DEST_MODEL} (private)")


# ── 4. Train ────────────────────────────────────────────────────────────
def start_training(images_url):
    body = {
        "destination": DEST_MODEL,
        "input": {
            "input_images": images_url,
            "input_images_filetype": "zip",
            "token_string": "TOK",
            "caption_prefix": "a photo of TOK, an adult woman, ",
            "max_train_steps": 1000,
            "resolution": 1024,
            "is_lora": True,
            "lora_rank": 32,
            "seed": 42,
        },
    }
    r = requests.post(
        f"{API}/models/stability-ai/sdxl/versions/{SDXL_TRAINER_VERSION}/trainings",
        headers={**H, "Content-Type": "application/json"},
        json=body, timeout=60,
    )
    r.raise_for_status()
    t = r.json()
    log(f"training started id={t['id']} status={t['status']}")
    return t


def poll(get_url, label, interval=15, timeout_s=2400):
    t0 = time.time()
    while True:
        r = requests.get(get_url, headers=H, timeout=30)
        r.raise_for_status()
        obj = r.json()
        st = obj["status"]
        if st in ("succeeded", "failed", "canceled"):
            log(f"{label} {st} after {int(time.time()-t0)}s")
            return obj
        if time.time() - t0 > timeout_s:
            raise SystemExit(f"{label} timed out after {timeout_s}s")
        log(f"{label} {st}… ({int(time.time()-t0)}s)")
        time.sleep(interval)


# ── 5. Generate ─────────────────────────────────────────────────────────
PROMPTS = [
    ("bikini_beach", "a photo of TOK, an adult woman in a light blue bikini standing on a sandy beach, ocean and sky background, full body, both arms visible, natural daylight, photorealistic"),
    ("black_dress", "a photo of TOK, an adult woman wearing an elegant black dress, full body, standing, studio lighting, photorealistic"),
    ("casual_jeans", "a photo of TOK, an adult woman wearing casual blue jeans and a white top, full body, standing outdoors, natural light, photorealistic"),
]
NEGATIVE = "deformed, disfigured, extra limbs, extra fingers, bad anatomy, blurry, lowres, watermark, text, multiple people"


def generate(trained_version_hash):
    results = []
    for key, prompt in PROMPTS:
        body = {
            "version": trained_version_hash,
            "input": {
                "prompt": prompt, "negative_prompt": NEGATIVE,
                "width": 1024, "height": 1024, "num_outputs": 1,
                "num_inference_steps": 30, "guidance_scale": 7.5,
                "lora_scale": 0.85, "seed": 1234,
            },
        }
        r = requests.post(f"{API}/predictions", headers={**H, "Content-Type": "application/json"},
                          json=body, timeout=60)
        r.raise_for_status()
        pred = r.json()
        log(f"prediction {key} started id={pred['id']}")
        done = poll(pred["urls"]["get"], f"gen:{key}", interval=8, timeout_s=600)
        out = done.get("output")
        url = out[0] if isinstance(out, list) and out else out
        results.append({
            "key": key, "prompt": prompt, "status": done["status"],
            "image_url": url, "error": done.get("error"),
            "predict_time": (done.get("metrics") or {}).get("predict_time"),
        })
    return results


def main():
    report = {"character_id": CHARACTER_ID, "destination_model": DEST_MODEL}
    overall0 = time.time()

    zip_bytes, used_roles, dropped = build_training_zip()
    report["training_images"] = used_roles
    report["dropped_mark_crops"] = dropped

    images_url = upload_zip(zip_bytes)
    ensure_destination()

    tr = start_training(images_url)
    tr_done = poll(tr["urls"]["get"], "training", interval=20, timeout_s=2700)
    report["training_status"] = tr_done["status"]
    tr_ptime = (tr_done.get("metrics") or {}).get("predict_time")
    report["training_predict_time_s"] = tr_ptime
    report["training_cost_usd_est"] = round(tr_ptime * RATE[TRAIN_HW], 4) if tr_ptime else None

    if tr_done["status"] != "succeeded":
        report["training_error"] = tr_done.get("error")
        REPORT_PATH.write_text(json.dumps(report, indent=2))
        log(f"TRAINING FAILED: {tr_done.get('error')}")
        return

    version_field = tr_done["output"]["version"]   # "owner/name:hash"
    trained_hash = version_field.split(":")[-1]
    report["trained_version"] = version_field
    log(f"trained version: {version_field}")

    gens = generate(trained_hash)
    report["generations"] = gens
    gptime = sum((g["predict_time"] or 0) for g in gens)
    report["generation_predict_time_total_s"] = round(gptime, 2)
    report["generation_cost_usd_est"] = round(gptime * RATE[INFER_HW], 4)
    report["image_urls"] = [g["image_url"] for g in gens if g.get("image_url")]
    report["wall_clock_total_s"] = int(time.time() - overall0)

    REPORT_PATH.write_text(json.dumps(report, indent=2))
    log(f"DONE. report -> {REPORT_PATH}")
    log(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        try:
            partial = {"fatal_error": str(exc)}
            if REPORT_PATH.exists():
                partial = {**json.loads(REPORT_PATH.read_text()), "fatal_error": str(exc)}
            REPORT_PATH.write_text(json.dumps(partial, indent=2))
        except Exception:
            pass
        sys.exit(1)
