"""Pod-side Sprint E8 — IMG2IMG PROVIDER BAKE-OFF (throwaway, founder-only).

NOT the mask-patch editor. This tests FULL image-to-image regeneration:
the whole frame is re-diffused from the Summer black-dress source at a
fixed strength — no SegFormer masks, no paste-back. The question under
test: can SDXL-class full img2img behave like GPT editing (same person,
new outfit/scene) when the Summer LoRA carries identity?

Matrix (4 images, fixed seed, 1 image per model per prompt — sprint rule):
  RealVisXL V4.0  x {blue bikini beach, black lace lingerie bed}
  Juggernaut XL v9 x {blue bikini beach, black lace lingerie bed}

Each result uploads to R2 immediately, so a watchdog kill preserves
partial results. Status streamed to proof/<RUN_ID>/status.json.
"""
import io
import json
import os
import tarfile
import time
import traceback
import urllib.request

LOG = []


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    LOG.append(line)


RUN_ID = os.environ.get("PROOF_RUN_ID", "e8run")
R2_PUBLIC = os.environ["R2_PUBLIC_URL"].rstrip("/")
SOURCE_URL = os.environ["SOURCE_URL"]
LORA_URL = os.environ["LORA_URL"]
HF_TOKEN = os.environ.get("HF_TOKEN") or None
SEED = 7
STEPS = 30
GUIDANCE = 7.0
STRENGTH = float(os.environ.get("E8_STRENGTH", "0.65"))

MODELS = [
    ("realvisxl", "SG161222/RealVisXL_V4.0"),
    ("juggernaut", "RunDiffusion/Juggernaut-XL-v9"),
]

# Descriptive prompts: full img2img has no instruction-following, so the
# sprint's "Preserve her face, body, tattoos, hair, and jewelry" becomes
# explicit canon descriptors (phrases proven in the S23 canon prompts).
SUMMER_DESC = (
    "a photo of TOK, an adult woman with long wavy blonde hair and blue eyes, "
    "intricate black-ink butterfly and floral sleeve tattoo on the right upper "
    "arm, black-and-white ballerina dancer tattoo on the left forearm, gold "
    "pendant necklace, "
)
PROMPTS = [
    ("bikini_beach", SUMMER_DESC +
     "wearing a blue two-piece bikini, standing on a luxury beach, white sand, "
     "turquoise ocean, golden sunlight, photorealistic, natural skin texture"),
    ("lingerie_bed", SUMMER_DESC +
     "wearing black lace lingerie, sitting on a bed in an elegant bedroom, "
     "soft warm light, photorealistic, natural skin texture"),
]
NEG = ("deformed, extra limbs, extra fingers, mutated hands, bad anatomy, "
       "asymmetric body, blurry, lowres, watermark, text, black dress, dress, "
       "gown, multiple people, cartoon, illustration")

import boto3  # noqa: E402

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)
BUCKET = os.environ["R2_BUCKET_NAME"]

status = {"run_id": RUN_ID, "stage": "start", "images": {}, "errors": [],
          "done": False, "strength": STRENGTH, "lora_loaded": {}}


def push_status(stage):
    status["stage"] = stage
    status["log"] = LOG
    try:
        s3.put_object(Bucket=BUCKET, Key=f"proof/{RUN_ID}/status.json",
                      Body=json.dumps(status, indent=2).encode(),
                      ContentType="application/json")
    except Exception as e:  # noqa: BLE001
        print("status push failed:", e, flush=True)


def upload_img(name, pil):
    b = io.BytesIO()
    pil.save(b, "PNG")
    key = f"proof/{RUN_ID}/{name}.png"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b.getvalue(), ContentType="image/png")
    url = f"{R2_PUBLIC}/{key}"
    status["images"][name] = url
    log(f"  uploaded {name}")
    push_status(status["stage"])
    return url


def fetch(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as out:
        out.write(r.read())
    return path


def fetch_r2(url_or_key, path):
    key = url_or_key
    if key.startswith(R2_PUBLIC + "/"):
        key = key[len(R2_PUBLIC) + 1:]
    s3.download_file(BUCKET, key, path)
    return path


def main():
    import torch
    from PIL import Image

    push_status("download_inputs")
    fetch_r2(SOURCE_URL, "/tmp/source.png")
    source = Image.open("/tmp/source.png").convert("RGB")
    W, H = source.size
    W8, H8 = W - W % 8, H - H % 8
    if (W8, H8) != (W, H):
        source = source.crop((0, 0, W8, H8))
        W, H = W8, H8
    log(f"source: {W}x{H}")
    upload_img("00_source", source)

    fetch(LORA_URL, "/tmp/lora.tar")
    lora_path = None
    try:
        with tarfile.open("/tmp/lora.tar") as t:
            t.extractall("/tmp/lora")
        for root, _, files in os.walk("/tmp/lora"):
            for f in files:
                if f.endswith(".safetensors"):
                    lora_path = os.path.join(root, f)
    except tarfile.ReadError:
        lora_path = "/tmp/lora.tar"
    log(f"lora: {lora_path}")

    from diffusers import StableDiffusionXLImg2ImgPipeline

    last_img = None
    for model_key, model_id in MODELS:
        push_status(f"load_{model_key}")
        log(f"loading {model_id}")
        try:
            try:
                pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                    model_id, torch_dtype=torch.float16, variant="fp16",
                    token=HF_TOKEN).to("cuda")
            except Exception as e:  # noqa: BLE001 — no fp16 variant shipped
                log(f"fp16 variant load failed ({e!r}); retrying without variant")
                pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                    model_id, torch_dtype=torch.float16, token=HF_TOKEN).to("cuda")
        except Exception as e:  # noqa: BLE001 — gated/missing repo: skip, keep going
            status["errors"].append(f"{model_key}_load: {e!r}")
            log(f"{model_key} base model load FAILED: {e!r} — skipping model")
            continue
        pipe.set_progress_bar_config(disable=True)
        try:
            pipe.load_lora_weights(lora_path)
            status["lora_loaded"][model_key] = True
            log("LoRA loaded OK")
        except Exception as e:  # noqa: BLE001
            status["lora_loaded"][model_key] = False
            status["errors"].append(f"{model_key}_lora: {e!r}")
            log(f"LoRA load FAILED: {e!r} — continuing without")

        for prompt_key, prompt in PROMPTS:
            push_status(f"gen_{model_key}_{prompt_key}")
            g = torch.Generator("cuda").manual_seed(SEED)
            try:
                img = pipe(prompt=prompt, negative_prompt=NEG, image=source,
                           strength=STRENGTH, num_inference_steps=STEPS,
                           guidance_scale=GUIDANCE, generator=g).images[0]
            except Exception as e:  # noqa: BLE001
                status["errors"].append(f"{model_key}_{prompt_key}: {e!r}")
                log(f"gen {model_key}/{prompt_key} FAILED: {e!r}")
                continue
            upload_img(f"{model_key}_{prompt_key}", img)
            last_img = img

        del pipe
        torch.cuda.empty_cache()

    if last_img is not None:
        upload_img("99_final", last_img)  # driver success sentinel
    else:
        status["errors"].append("fatal: no image generated by any model")
    status["done"] = True
    push_status("done")
    log("E8 bake-off pipeline complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"fatal: {e!r}")
        LOG.append(traceback.format_exc()[-1500:])
        push_status("fatal")
        raise
