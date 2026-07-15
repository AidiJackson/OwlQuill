"""Pod-side Sprint E3 — SELF-HOSTED EDITOR ENGINE (throwaway, founder-only).

INVERTS the 23-series flow: the SOURCE IMAGE IS STRUCTURAL TRUTH. Nothing is
generated from text alone. Face, hair, arms (tattoos), and the clutch bag are
never inside any inpaint mask, and every pass ends with a feathered composite
back onto the prior truth image (Sprint 14 paste-back guarantee).

Flow (single candidate, fixed seed — one validation image, $0.05 cap):
  1. fetch Summer black-dress source (CharacterImage 1778) from R2
  2. SegFormer clothes segmentation -> dress mask, background mask,
     protect union (face + hair + arms + sunglasses + bag)
  3. inpaint dress region only -> "blue bikini" (RealVisXL + Summer LoRA, TOK)
  4. inpaint background only   -> "luxury beach resort"
  5. outside the two edited masks the final equals the source bit-for-bit

Defensive: every stage wrapped; stage images + status.json streamed to R2 under
proof/<RUN_ID>/...; the startup wrapper self-terminates the pod (720s watchdog).
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


RUN_ID = os.environ.get("PROOF_RUN_ID", "e3run")
R2_PUBLIC = os.environ["R2_PUBLIC_URL"].rstrip("/")
SOURCE_URL = os.environ["SOURCE_URL"]
LORA_URL = os.environ["LORA_URL"]
BASE_MODEL_ID = os.environ.get("BASE_MODEL_ID", "SG161222/RealVisXL_V4.0")
SEED = 7
STEPS = 32
GUIDANCE = 7.0

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
          "done": False, "base_model": BASE_MODEL_ID, "lora_loaded": None,
          "mask_px": {}}


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
    import numpy as np
    import torch
    import torch.nn.functional as Fnn
    from PIL import Image, ImageChops, ImageFilter

    # ── inputs ────────────────────────────────────────────────────────
    push_status("download_inputs")
    fetch_r2(SOURCE_URL, "/tmp/source.png")
    source = Image.open("/tmp/source.png").convert("RGB")
    W, H = source.size
    # SDXL latent constraint: /8 dims (source 1778 is 1024x1024 — already fine)
    W8, H8 = W - W % 8, H - H % 8
    if (W8, H8) != (W, H):
        source = source.crop((0, 0, W8, H8))
        W, H = W8, H8
    log(f"source: {W}x{H}")
    upload_img("00_source", source)

    fetch(LORA_URL, "/tmp/lora.tar")  # replicate.delivery HTTPS — plain fetch (23C pattern)
    lora_path = None
    try:
        with tarfile.open("/tmp/lora.tar") as t:
            t.extractall("/tmp/lora")
        for root, _, files in os.walk("/tmp/lora"):
            for f in files:
                if f.endswith(".safetensors"):
                    lora_path = os.path.join(root, f)
    except tarfile.ReadError:
        lora_path = "/tmp/lora.tar"  # plain .safetensors, not a tar
    log(f"lora: {lora_path}")

    # ── pipeline: plain SDXL inpaint (no ControlNet needed — saves ~2.5GB
    #    download against the 720s watchdog; all other kwargs proven in 23C) ──
    push_status("load_pipeline")
    from diffusers import StableDiffusionXLInpaintPipeline

    log(f"base model: {BASE_MODEL_ID}")
    try:
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            BASE_MODEL_ID, torch_dtype=torch.float16, variant="fp16").to("cuda")
    except Exception as e:  # noqa: BLE001 — some checkpoints ship no fp16 variant
        log(f"fp16 variant load failed ({e!r}); retrying without variant")
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            BASE_MODEL_ID, torch_dtype=torch.float16).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    try:
        pipe.load_lora_weights(lora_path)
        status["lora_loaded"] = True
        log("LoRA loaded OK")
    except Exception as e:  # noqa: BLE001
        status["lora_loaded"] = False
        status["errors"].append(f"lora_load: {e!r}")
        log(f"LoRA load FAILED: {e!r} — continuing without (source is identity truth)")

    # ── SegFormer masks on the SOURCE ─────────────────────────────────
    push_status("segment")
    from transformers import AutoModelForSemanticSegmentation, SegformerImageProcessor
    seg_proc = SegformerImageProcessor.from_pretrained("mattmdjaga/segformer_b2_clothes")
    seg_model = AutoModelForSemanticSegmentation.from_pretrained(
        "mattmdjaga/segformer_b2_clothes").to("cuda")
    inp = seg_proc(images=source, return_tensors="pt").to("cuda")
    with torch.no_grad():
        logits = seg_model(**inp).logits
    seg = Fnn.interpolate(logits, size=(H, W), mode="bilinear",
                          align_corners=False).argmax(1)[0].cpu().numpy()

    # mattmdjaga/segformer_b2_clothes classes:
    # 0 bg, 2 hair, 3 sunglasses, 4 upper-clothes, 5 skirt, 7 dress, 8 belt,
    # 11 face, 14 left-arm, 15 right-arm, 16 bag
    dress_b = np.isin(seg, [4, 5, 7, 8])
    protect_b = np.isin(seg, [2, 3, 11, 14, 15, 16])
    bg_b = seg == 0
    status["mask_px"] = {"dress": int(dress_b.sum()),
                         "protect": int(protect_b.sum()),
                         "background": int(bg_b.sum())}
    log(f"mask px: {status['mask_px']}")
    if dress_b.sum() < 2000:
        status["errors"].append("fatal: dress mask too small — segmentation failed")
        push_status("fatal")
        return

    def bool_to_mask(b, grow, blur):
        m = Image.fromarray((b.astype("uint8") * 255), "L")
        if grow:
            m = m.filter(ImageFilter.MaxFilter(grow))
        return m.filter(ImageFilter.GaussianBlur(blur))

    # dress mask: grown + feathered, then HARD-ZEROED wherever the grown
    # protect union lives — face/hair/arms(tattoos)/bag can never repaint.
    dress_mask = bool_to_mask(dress_b, grow=9, blur=4)
    protect_grown = Image.fromarray((protect_b.astype("uint8") * 255), "L").filter(
        ImageFilter.MaxFilter(13))
    dress_mask = ImageChops.subtract(dress_mask, protect_grown)
    upload_img("01_mask_dress", dress_mask)
    upload_img("03_mask_protect", protect_grown)

    # background mask: grown slightly INTO the person edge so the new scene
    # blends her silhouette, feathered composite keeps the person herself.
    bg_mask = bool_to_mask(bg_b, grow=7, blur=5)
    bg_mask = ImageChops.subtract(bg_mask, protect_grown)  # never touch face/hair/arms
    upload_img("02_mask_bg", bg_mask)

    neg = ("deformed, extra limbs, extra fingers, mutated hands, bad anatomy, "
           "asymmetric body, blurry, lowres, watermark, text, black dress, "
           "dress, gown, fabric remnants, multiple people")

    def paste_back(new_img, base_img, mask_l):
        """Sprint 14 guarantee: outside the feathered mask, base bit-for-bit."""
        return Image.composite(new_img.convert("RGB"), base_img.convert("RGB"), mask_l)

    # ── pass 1: dress -> blue bikini (source is the init image) ──────
    push_status("inpaint_dress")
    dress_prompt = (
        "a photo of TOK, an adult woman wearing a blue bikini, two-piece blue "
        "bikini swimsuit, bare midriff, toned slim body, natural skin texture, "
        "photorealistic, natural light"
    )
    g = torch.Generator("cuda").manual_seed(SEED)
    raw = pipe(prompt=dress_prompt, negative_prompt=neg, image=source,
               mask_image=dress_mask, strength=0.99, num_inference_steps=STEPS,
               guidance_scale=GUIDANCE, width=W, height=H, generator=g).images[0]
    after_dress = paste_back(raw, source, dress_mask)
    upload_img("04_after_dress", after_dress)

    # ── pass 2: background -> luxury beach resort ─────────────────────
    push_status("inpaint_background")
    bg_prompt = (
        "luxury beach resort, white sand beach, turquoise ocean, palm trees, "
        "sun loungers and parasols in the distance, bright sunny day, golden "
        "light, photorealistic"
    )
    g2 = torch.Generator("cuda").manual_seed(SEED + 1)
    raw_bg = pipe(prompt=bg_prompt,
                  negative_prompt="people, person, crowd, deformed, blurry, "
                                  "lowres, watermark, text",
                  image=after_dress, mask_image=bg_mask, strength=0.99,
                  num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                  width=W, height=H, generator=g2).images[0]
    final = paste_back(raw_bg, after_dress, bg_mask)
    upload_img("05_after_bg", final)

    # outside dress_mask ∪ bg_mask the final IS the source (composite chain);
    # 99_final is the deliverable name the driver looks for.
    upload_img("99_final", final)
    status["done"] = True
    push_status("done")
    log("E3 editor pipeline complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"fatal: {e!r}")
        LOG.append(traceback.format_exc()[-1500:])
        push_status("fatal")
        raise
