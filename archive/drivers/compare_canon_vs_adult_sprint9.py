#!/usr/bin/env python3
"""Sprint 9 — Canon Studio vs Adult Studio comparison generator (ADMIN/INTERNAL).

Product-validation, NOT architecture validation. Generates faithful CANON STUDIO
outputs via the real product pipeline (anchor-grounded gpt-image-1.5 images.edit on
the character's locked anchors) for Summer and Shadow, on equivalent scene prompts.
The Summer ADULT STUDIO output is REUSED from the Sprint-8 masked-diffusion run (real
LoRA identity + enforced tattoos) — no new pod, no new Adult spend. Shadow Adult is N/A.

NOT the normal generator code path (no code changes), NOT Canon Studio code changes,
NOT a UI, NOT public generation. Hard cumulative cap $0.25; aborts before any call that
would breach it. Writes summer_shadow_comparison_report.json (image URLs + system +
runtime + cost; scorecards filled in by the reviewer afterward).
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from openai import OpenAI  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.storage import load_image_bytes, save_image  # noqa: E402

SPEND_CAP = 0.25
GUARD = 0.22                # refuse a call if cumulative would exceed this (margin)
EST_PER_IMAGE = 0.09        # conservative pre-call estimate for the cap guard
SIZE = "1024x1536"
REPORT = Path(__file__).resolve().parent / "summer_shadow_comparison_report.json"

# gpt-image-1.5 token pricing (USD per 1M tokens) — used to price from response.usage.
PRICE = {"text_in": 5.0, "image_in": 10.0, "image_out": 40.0}

client = OpenAI()

# Sprint-8 Adult Studio output (real masked-diffusion enforcement, bikini/arms-at-sides).
SUMMER_ADULT = {
    "system": "Adult Studio (per-character LoRA + masked-diffusion tattoo enforcement)",
    "image_url": "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/proof/"
                 "summer_s8_20260608_171229/99_final.png",
    "runtime_s": 317.5, "cost_usd": 0.0141, "source": "reused from Sprint 8 (run summer_s8_20260608_171229)",
    "prompt": "blonde woman, blue bikini, standing arms relaxed at sides, full body, "
              "studio; butterfly/floral sleeve (right upper arm) + ballerina (left forearm) ENFORCED",
}

# Canon Studio (anchor-grounded gpt-image-1.5). Equivalent scene prompts; tattoos named
# explicitly for Summer to give Canon Studio its best shot at them via text.
CANON_JOBS = [
    {"label": "summer_canon", "character": "Summer", "character_id": 60,
     "anchors": [  # full-body + face_ref (the locked canon anchors)
         "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated/784ca2110cc7420f8391acd42ca8a56c.png",
         "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated/cab6d3fe9f2b45d8a68ad232c34ec735.png"],
     "prompt": ("Full-body photo of this exact woman: long blonde hair, blue eyes, tall slim build, "
                "wearing a sleeveless white tank top and denim shorts, standing straight facing the "
                "camera with both arms relaxed at her sides and forearms fully visible. She has a "
                "butterfly and floral sleeve tattoo on her RIGHT upper arm and a black-and-white "
                "ballerina tattoo on her LEFT forearm. Plain light studio background, soft natural "
                "light, photorealistic.")},
    {"label": "shadow_canon", "character": "Shadow", "character_id": 58,
     "anchors": [
         "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated/0be40b82c6c440759b1b112bdc141ad3.png",
         "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated/a6b32336f1cb429abd884ee2ad219099.png"],
     "prompt": ("Full-body photo of this exact man: short dark hair, standing straight facing the "
                "camera with both arms relaxed at his sides, wearing a fitted dark t-shirt and jeans. "
                "Plain studio background, soft natural light, photorealistic.")},
]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def price_from_usage(usage) -> float:
    if not usage:
        return EST_PER_IMAGE
    it = getattr(usage, "input_tokens_details", None)
    text_in = getattr(it, "text_tokens", 0) if it else 0
    image_in = getattr(it, "image_tokens", 0) if it else 0
    out = getattr(usage, "output_tokens", 0) or 0
    cost = (text_in * PRICE["text_in"] + image_in * PRICE["image_in"]
            + out * PRICE["image_out"]) / 1_000_000
    return round(cost, 5)


def gen_canon(job, spent):
    if spent + EST_PER_IMAGE > GUARD:
        log(f"SPEND GUARD: skipping {job['label']} (spent=${spent}, would exceed ${GUARD})")
        return None, spent
    import tempfile
    fhs, paths = [], []
    try:
        for a in job["anchors"]:
            b = load_image_bytes(a)
            tf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tf.write(b); tf.flush(); tf.close()
            paths.append(tf.name); fhs.append(open(tf.name, "rb"))
        t0 = time.time()
        resp = client.images.edit(model=settings.IMAGE_MODEL,
                                  image=fhs if len(fhs) > 1 else fhs[0],
                                  prompt=job["prompt"], n=1, size=SIZE)
        runtime = round(time.time() - t0, 1)
        import base64
        png = base64.b64decode(resp.data[0].b64_json)
        url = save_image(png)
        cost = price_from_usage(getattr(resp, "usage", None))
        spent = round(spent + cost, 5)
        log(f"{job['label']}: {url} runtime={runtime}s cost=${cost} cum=${spent}")
        return {"label": job["label"], "character": job["character"],
                "system": "Canon Studio (anchor-grounded gpt-image-1.5)",
                "image_url": url, "runtime_s": runtime, "cost_usd": cost,
                "prompt": job["prompt"], "anchors": job["anchors"]}, spent
    finally:
        for fh in fhs:
            try: fh.close()
            except Exception: pass
        for p in paths:
            try: os.unlink(p)
            except Exception: pass


def main():
    spent = 0.0
    canon_outputs = []
    for job in CANON_JOBS:
        out, spent = gen_canon(job, spent)
        if out:
            canon_outputs.append(out)

    report = {
        "sprint": "phase3-sprint9",
        "comparison": "Canon Studio vs Adult Studio",
        "spend_cap_usd": SPEND_CAP,
        "canon_generation_spend_usd": round(spent, 5),
        "adult_studio_spend_usd": 0.0,  # reused S8; no new Adult spend this sprint
        "total_spend_usd": round(spent, 5),
        "outputs": {
            "summer_canon": next((o for o in canon_outputs if o["label"] == "summer_canon"), None),
            "summer_adult": SUMMER_ADULT,
            "shadow_canon": next((o for o in canon_outputs if o["label"] == "shadow_canon"), None),
            "shadow_adult": {"system": "Adult Studio", "status": "N/A",
                             "reason": "no AdultIdentityModel, no active version, no mark plan "
                                       "for Shadow (id=58); Shadow has 0 permanent marks. Training "
                                       "is out of scope this sprint."},
        },
        "corroborating_real_canon_anchors": {
            "summer_full_body": "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated/784ca2110cc7420f8391acd42ca8a56c.png",
            "shadow_full_body": "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated/0be40b82c6c440759b1b112bdc141ad3.png",
        },
        "scorecards": "filled by reviewer after visual inspection",
        "manual_review_required": True,
    }
    REPORT.write_text(json.dumps(report, indent=2))
    log(f"TOTAL canon spend=${round(spent,5)} (cap ${SPEND_CAP}) — report: {REPORT.name}")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
