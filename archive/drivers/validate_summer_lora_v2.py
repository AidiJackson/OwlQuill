#!/usr/bin/env python3
"""THROWAWAY tuning pass #2 — Summer SDXL LoRA on Replicate.

NOT part of Ficshon. Reads Summer's prepared manifest (read-only) and trains a
SECOND LoRA into a NEW destination model (summer-sdxl-lora-v2) so the kept v1
model is untouched.

Changes vs v1 (baseline):
  - INCLUDE the 2 isolated tattoo crops (v1 dropped them) -> tattoo retention test
  - use_face_detection_instead=True               -> face-weighted masking
  - max_train_steps 1000 -> 700                    -> reduce grey-background overfit
  - inference lora_scale 0.85 -> 0.70             -> more prompt/background adherence
  - portrait aspect + waist-up framing             -> face is judgeable

Run from backend/ with REPLICATE_API_TOKEN set. Writes scripts/summer_lora_v2_report.json.
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
DEST_MODEL = f"{OWNER}/summer-sdxl-lora-v2"
CHARACTER_ID = 60
REPORT_PATH = Path(__file__).resolve().parent / "summer_lora_v2_report.json"

RATE = {"gpu-a100-large": 0.001400, "gpu-l40s": 0.000975, "gpu-t4": 0.000225}
TRAIN_HW = "gpu-a100-large"
INFER_HW = "gpu-l40s"

# Tuning knobs
MAX_TRAIN_STEPS = 700
USE_FACE_DETECTION = True
INCLUDE_MARK_CROPS = True
LORA_SCALE = 0.70

TOKEN = os.environ.get("REPLICATE_API_TOKEN")
if not TOKEN:
    print("FATAL: REPLICATE_API_TOKEN not set", flush=True)
    sys.exit(1)
H = {"Authorization": f"Bearer {TOKEN}"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def build_training_zip():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    from app.core.database import SessionLocal
    from app.models.adult_studio import AdultStudioIdentity
    from app.core.storage import load_image_bytes

    db = SessionLocal()
    rec = db.query(AdultStudioIdentity).filter(AdultStudioIdentity.character_id == CHARACTER_ID).first()
    manifest = rec.training_notes_json or {}
    db.close()

    refs = list(manifest.get("refs") or [])
    if not INCLUDE_MARK_CROPS:
        refs = [r for r in refs if not r.get("role", "").startswith("mark:")]

    used = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, r in enumerate(refs):
            role, url = r.get("role"), r.get("url")
            if not url:
                continue
            safe = role.replace(":", "_").replace(" ", "_")
            zf.writestr(f"{i:02d}_{safe}.png", load_image_bytes(url))
            used.append(role)
    log(f"training zip: {len(used)} images (include_marks={INCLUDE_MARK_CROPS}) {used}")
    return buf.getvalue(), used


def upload_zip(zip_bytes):
    r = requests.post(f"{API}/files", headers=H,
                      files={"content": ("summer_train_v2.zip", zip_bytes, "application/zip")}, timeout=120)
    r.raise_for_status()
    url = r.json()["urls"]["get"]
    log(f"uploaded zip ({len(zip_bytes)} bytes)")
    return url


def ensure_destination():
    r = requests.get(f"{API}/models/{DEST_MODEL}", headers=H, timeout=30)
    if r.status_code == 200:
        log(f"destination exists: {DEST_MODEL}")
        return
    r = requests.post(f"{API}/models", headers=H, json={
        "owner": OWNER, "name": "summer-sdxl-lora-v2", "visibility": "private",
        "hardware": INFER_HW, "description": "Throwaway Summer SDXL LoRA tuning pass v2.",
    }, timeout=30)
    if r.status_code not in (200, 201):
        raise SystemExit(f"create model failed: {r.status_code} {r.text}")
    log(f"created destination: {DEST_MODEL} (private)")


def start_training(images_url):
    body = {"destination": DEST_MODEL, "input": {
        "input_images": images_url,
        "input_images_filetype": "zip",
        "token_string": "TOK",
        "caption_prefix": "a photo of TOK, an adult woman with long blonde hair and blue eyes, ",
        "max_train_steps": MAX_TRAIN_STEPS,
        "resolution": 1024,
        "is_lora": True,
        "lora_rank": 32,
        "use_face_detection_instead": USE_FACE_DETECTION,
        "seed": 42,
    }}
    r = requests.post(f"{API}/models/stability-ai/sdxl/versions/{SDXL_TRAINER_VERSION}/trainings",
                      headers={**H, "Content-Type": "application/json"}, json=body, timeout=60)
    r.raise_for_status()
    t = r.json()
    log(f"training started id={t['id']} steps={MAX_TRAIN_STEPS} face_det={USE_FACE_DETECTION}")
    return t


def poll(get_url, label, interval=15, timeout_s=2700):
    t0 = time.time()
    while True:
        obj = requests.get(get_url, headers=H, timeout=30).json()
        st = obj["status"]
        if st in ("succeeded", "failed", "canceled"):
            log(f"{label} {st} after {int(time.time()-t0)}s")
            return obj
        if time.time() - t0 > timeout_s:
            raise SystemExit(f"{label} timed out")
        log(f"{label} {st}… ({int(time.time()-t0)}s)")
        time.sleep(interval)


# Portrait aspect (832x1216) so waist-up framing has room for the face.
PROMPTS = [
    ("bikini_waist_up", "a photo of TOK, an adult woman in a light blue bikini, waist-up portrait, upper body, head and shoulders clearly visible, looking at camera, sunny beach with ocean behind, natural daylight, photorealistic", 832, 1216),
    ("bikini_full_body", "a photo of TOK, an adult woman in a light blue bikini standing on a sandy beach, full body, ocean and blue sky background, both arms visible, natural daylight, photorealistic", 832, 1216),
    ("black_dress_portrait", "a photo of TOK, an adult woman wearing an elegant black dress, waist-up portrait, upper body, face clearly visible, looking at camera, soft studio lighting, photorealistic", 832, 1216),
]
NEGATIVE = "deformed, disfigured, extra limbs, extra fingers, bad anatomy, blurry, lowres, watermark, text, multiple people, grey background, plain background"


def generate(version_hash):
    results = []
    for key, prompt, w, h in PROMPTS:
        body = {"version": version_hash, "input": {
            "prompt": prompt, "negative_prompt": NEGATIVE, "width": w, "height": h,
            "num_outputs": 1, "num_inference_steps": 32, "guidance_scale": 7.5,
            "lora_scale": LORA_SCALE, "seed": 1234,
        }}
        pred = requests.post(f"{API}/predictions", headers={**H, "Content-Type": "application/json"},
                             json=body, timeout=60).json()
        log(f"gen {key} id={pred['id']} lora_scale={LORA_SCALE} {w}x{h}")
        done = poll(pred["urls"]["get"], f"gen:{key}", interval=8, timeout_s=600)
        out = done.get("output")
        url = out[0] if isinstance(out, list) and out else out
        results.append({"key": key, "prompt": prompt, "size": f"{w}x{h}",
                        "status": done["status"], "image_url": url,
                        "error": done.get("error"),
                        "predict_time": (done.get("metrics") or {}).get("predict_time")})
    return results


def main():
    rep = {"character_id": CHARACTER_ID, "destination_model": DEST_MODEL,
           "settings": {"max_train_steps": MAX_TRAIN_STEPS, "use_face_detection": USE_FACE_DETECTION,
                        "include_mark_crops": INCLUDE_MARK_CROPS, "lora_scale": LORA_SCALE,
                        "resolution": 1024, "lora_rank": 32}}
    t0 = time.time()
    zb, used = build_training_zip()
    rep["training_images"] = used
    url = upload_zip(zb)
    ensure_destination()
    tr = poll(start_training(url)["urls"]["get"], "training", interval=20, timeout_s=2700)
    rep["training_status"] = tr["status"]
    pt = (tr.get("metrics") or {}).get("predict_time")
    rep["training_predict_time_s"] = pt
    rep["training_cost_usd_est"] = round(pt * RATE[TRAIN_HW], 4) if pt else None
    if tr["status"] != "succeeded":
        rep["training_error"] = tr.get("error")
        REPORT_PATH.write_text(json.dumps(rep, indent=2)); log(f"TRAIN FAILED {tr.get('error')}"); return
    vf = tr["output"]["version"]; rep["trained_version"] = vf
    gens = generate(vf.split(":")[-1])
    rep["generations"] = gens
    gpt = sum((g["predict_time"] or 0) for g in gens)
    rep["generation_predict_time_total_s"] = round(gpt, 2)
    rep["generation_cost_usd_est"] = round(gpt * RATE[INFER_HW], 4)
    rep["image_urls"] = [g["image_url"] for g in gens if g.get("image_url")]
    rep["wall_clock_total_s"] = int(time.time() - t0)
    REPORT_PATH.write_text(json.dumps(rep, indent=2))
    log("DONE"); log(json.dumps(rep, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        import traceback; traceback.print_exc()
        try:
            partial = {"fatal_error": str(exc)}
            if REPORT_PATH.exists():
                partial = {**json.loads(REPORT_PATH.read_text()), "fatal_error": str(exc)}
            REPORT_PATH.write_text(json.dumps(partial, indent=2))
        except Exception:
            pass
        sys.exit(1)
