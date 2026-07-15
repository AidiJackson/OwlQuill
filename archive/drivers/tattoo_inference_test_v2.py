"""Option B — tattoo-specific inference test against the EXISTING Summer v2 LoRA.

NO retraining, NO RunPod, NO ComfyUI, NO Ficshon imports. Pure Replicate inference
against aidijackson/summer-sdxl-lora-v2 to measure whether the already-trained LoRA
renders Summer's two tattoos on the correct limbs.

Trigger note: the LoRA was trained with token_string="TOK" + caption_prefix
"a photo of TOK, an adult woman with long blonde hair and blue eyes,". So prompts
use the TOK trigger to invoke Summer's identity; the user's tattoo descriptors are
kept verbatim. lora_scale=0.82. 3 prompts x 2 images = 6 images. Filtered (NSFW)
outputs are NOT retried.
"""
import json
import os
import sys
import time

import requests

API = "https://api.replicate.com/v1"
TOKEN = os.environ["REPLICATE_API_TOKEN"]
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

VERSION = "ce6df375ac0f7de1507ed92206436302dffece000caab9bfd15eb7d2ce1faea9"
LORA_SCALE = 0.82
TRIGGER = "a photo of TOK, an adult woman with long blonde hair and blue eyes, "
NEGATIVE = ("deformed, disfigured, extra limbs, extra fingers, bad anatomy, blurry, "
            "lowres, watermark, text, multiple people, plain background")

PROMPTS = [
    ("tank_denim", TRIGGER + "wearing a sleeveless white tank top and denim shorts, "
        "both arms visible, right upper arm butterfly and floral sleeve tattoo clearly "
        "visible, left forearm black-and-white ballerina tattoo clearly visible, photorealistic"),
    ("black_sleeveless_dress", TRIGGER + "standing in a fitted black sleeveless dress, "
        "both arms visible, right upper arm butterfly and floral sleeve tattoo clearly "
        "visible, left forearm black-and-white ballerina tattoo clearly visible, photorealistic"),
    ("gym_crop_top", TRIGGER + "in a gym-style sleeveless crop top, arms relaxed at her "
        "sides, right upper arm butterfly and floral sleeve tattoo visible, left forearm "
        "black-and-white ballerina tattoo visible, photorealistic"),
]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def poll(get_url, label, interval=6, timeout_s=600):
    t0 = time.time()
    while True:
        obj = requests.get(get_url, headers=H, timeout=30).json()
        st = obj["status"]
        if st in ("succeeded", "failed", "canceled"):
            log(f"{label} {st} after {int(time.time()-t0)}s")
            return obj
        if time.time() - t0 > timeout_s:
            raise SystemExit(f"{label} timed out")
        time.sleep(interval)


def main():
    results = []
    total_predict = 0.0
    for key, prompt in PROMPTS:
        body = {"version": VERSION, "input": {
            "prompt": prompt, "negative_prompt": NEGATIVE,
            "width": 832, "height": 1216,
            "num_outputs": 2, "num_inference_steps": 32, "guidance_scale": 7.5,
            "lora_scale": LORA_SCALE, "seed": 1234,
        }}
        pred = requests.post(f"{API}/predictions", headers=H, json=body, timeout=60).json()
        log(f"gen {key} id={pred.get('id')} lora_scale={LORA_SCALE}")
        done = poll(pred["urls"]["get"], f"gen:{key}")
        out = done.get("output")
        urls = out if isinstance(out, list) else ([out] if out else [])
        pt = (done.get("metrics") or {}).get("predict_time") or 0.0
        total_predict += pt
        results.append({
            "key": key, "prompt": prompt, "status": done["status"],
            "image_urls": urls, "error": done.get("error"), "predict_time": pt,
        })
        for u in urls:
            log(f"  -> {u}")
        if done.get("error"):
            log(f"  FILTERED/ERROR (no retry per instruction): {done.get('error')}")

    # Replicate SDXL inference on a10g ~= $0.00115/s billed; estimate from predict_time.
    cost_est = round(total_predict * 0.00115, 4)
    report = {
        "model": "aidijackson/summer-sdxl-lora-v2",
        "version_hash": VERSION,
        "lora_scale": LORA_SCALE,
        "images_per_prompt": 2,
        "results": results,
        "total_predict_time_s": round(total_predict, 2),
        "generation_cost_usd_est": cost_est,
    }
    out_path = os.path.join(os.path.dirname(__file__), "tattoo_inference_test_v2_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    log(f"DONE  predict={report['total_predict_time_s']}s  cost_est=${cost_est}")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    sys.exit(main())
