"""Pod-side script for the self-hosted Editor Studio provider (E5, production).

THIS FILE IS NOT IMPORTED BY THE BACKEND. editor_self_hosted.py ships it to a
RunPod instance (base64 in env) where it runs standalone. E4 fixes plus the
E5 quality work:

  E4.1  dress mask grow 9 -> 25  (cover dress silhouette wider than the body)
  E4.2  protect grow 13 -> 7     (stop protect from shielding dress slivers)
  E4.3  remnant cleanup micro-pass: detect surviving dark dress pixels near the
        torso after pass 1 and run a small local inpaint over just those
  E5.1  feathered compositing: paste-backs blend through a wide soft alpha
        instead of the sharp inpaint mask (kills the cut-out silhouette)
  E5.2  always-on low-strength harmonization pass over the FULL image to fuse
        person and scene lighting, followed by a feathered restore of the
        protect region (face/hair/arms/tattoos/bag) from the SOURCE pixels
  E5.3  quality metrics in status.json (remnant_px_final, seam_ratio) so the
        backend quality gate can mark pass | needs_review | failed

Architecture: the SOURCE IMAGE IS STRUCTURAL TRUTH. Face, hair, arms
(tattoos), and bag are never inside any inpaint mask; every pass composites
back onto the prior truth image (Sprint 14 paste-back guarantee), and the
harmonization restore re-asserts the source protect pixels at the very end.
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


RUN_ID = os.environ.get("PROOF_RUN_ID", "e4run")
R2_PUBLIC = os.environ["R2_PUBLIC_URL"].rstrip("/")
SOURCE_URL = os.environ["SOURCE_URL"]
LORA_URL = os.environ.get("LORA_URL", "")
USER_PROMPT = os.environ["USER_PROMPT"]
BASE_MODEL_ID = os.environ.get("BASE_MODEL_ID", "SG161222/RealVisXL_V4.0")
SEED = int(os.environ.get("SEED", "7"))
STEPS = 32
GUIDANCE = 7.0

# E4 mask geometry (PIL MaxFilter sizes must be odd)
DRESS_GROW = 25
PROTECT_GROW = 7
# E5: a remnant is a source DRESS pixel that survived inpainting unchanged —
# color-agnostic (works for black-bikini targets too, where dark != remnant).
REMNANT_DIFF_MAX = 12       # mean abs RGB diff from source below this = unchanged
REMNANT_MIN_PX = 300        # below this, skip the cleanup pass

# E5 compositing
COMPOSITE_FEATHER = 12      # GaussianBlur radius on paste-back alpha masks
HARMONIZE_STRENGTH = 0.18   # full-image fuse pass — low, identity-safe
PROTECT_RESTORE_BLUR = 5    # feather on the final source-truth protect restore
SEAM_RING_PX = 7            # boundary band width for the seam-harshness metric

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
          "mask_px": {}, "remnant_px": None, "quality": {},
          "editor_version": "e5"}


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
    W8, H8 = W - W % 8, H - H % 8
    if (W8, H8) != (W, H):
        source = source.crop((0, 0, W8, H8))
        W, H = W8, H8
    log(f"source: {W}x{H}")
    upload_img("00_source", source)

    lora_path = None
    if LORA_URL:
        fetch(LORA_URL, "/tmp/lora.tar")
        try:
            with tarfile.open("/tmp/lora.tar") as t:
                t.extractall("/tmp/lora")
            for root, _, files in os.walk("/tmp/lora"):
                for f in files:
                    if f.endswith(".safetensors"):
                        lora_path = os.path.join(root, f)
        except tarfile.ReadError:
            lora_path = "/tmp/lora.tar"  # plain .safetensors
        log(f"lora: {lora_path}")

    # ── pipeline: plain SDXL inpaint ──────────────────────────────────
    push_status("load_pipeline")
    from diffusers import StableDiffusionXLInpaintPipeline

    log(f"base model: {BASE_MODEL_ID}")
    try:
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            BASE_MODEL_ID, torch_dtype=torch.float16, variant="fp16").to("cuda")
    except Exception as e:  # noqa: BLE001
        log(f"fp16 variant load failed ({e!r}); retrying without variant")
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            BASE_MODEL_ID, torch_dtype=torch.float16).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    if lora_path:
        try:
            pipe.load_lora_weights(lora_path)
            status["lora_loaded"] = True
            log("LoRA loaded OK")
        except Exception as e:  # noqa: BLE001
            status["lora_loaded"] = False
            status["errors"].append(f"lora_load: {e!r}")
            log(f"LoRA load FAILED: {e!r} — continuing (source is identity truth)")

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

    # classes: 0 bg, 2 hair, 3 sunglasses, 4 upper-clothes, 5 skirt, 7 dress,
    #          8 belt, 11 face, 14 left-arm, 15 right-arm, 16 bag
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

    # E4.1/E4.2: WIDE dress mask, TIGHT protect — dress slivers near the arms
    # now fall inside the repaint zone instead of being shielded.
    dress_mask = bool_to_mask(dress_b, grow=DRESS_GROW, blur=4)
    protect_grown = Image.fromarray((protect_b.astype("uint8") * 255), "L").filter(
        ImageFilter.MaxFilter(PROTECT_GROW))
    dress_mask = ImageChops.subtract(dress_mask, protect_grown)
    upload_img("01_mask_dress", dress_mask)
    upload_img("03_mask_protect", protect_grown)

    bg_mask = bool_to_mask(bg_b, grow=7, blur=5)
    bg_mask = ImageChops.subtract(bg_mask, protect_grown)
    upload_img("02_mask_bg", bg_mask)

    neg = ("deformed, extra limbs, extra fingers, mutated hands, bad anatomy, "
           "asymmetric body, blurry, lowres, watermark, text, black dress, "
           "dress, gown, fabric remnants, straps, multiple people")

    def paste_back(new_img, base_img, mask_l):
        """Sprint 14 guarantee, E5-feathered: composite through a WIDE soft
        alpha so the new pixels fade into the base instead of cutting out.
        Far outside the mask the base remains bit-for-bit."""
        alpha = mask_l.filter(ImageFilter.GaussianBlur(COMPOSITE_FEATHER))
        return Image.composite(new_img.convert("RGB"), base_img.convert("RGB"), alpha)

    subject_prompt = (
        f"a photo of TOK, an adult woman, {USER_PROMPT}, natural skin texture, "
        "photorealistic, natural light"
    )
    scene_prompt = f"{USER_PROMPT}, photorealistic scene, detailed environment"

    # ── pass 1: outfit region (source is the init image) ─────────────
    push_status("inpaint_outfit")
    g = torch.Generator("cuda").manual_seed(SEED)
    raw = pipe(prompt=subject_prompt, negative_prompt=neg, image=source,
               mask_image=dress_mask, strength=0.99, num_inference_steps=STEPS,
               guidance_scale=GUIDANCE, width=W, height=H, generator=g).images[0]
    current = paste_back(raw, source, dress_mask)
    upload_img("04_after_outfit", current)

    # ── E4.3/E5: remnant cleanup micro-pass ───────────────────────────
    # Suspected remnants = source DRESS pixels that survived pass 1 nearly
    # unchanged (color-agnostic — valid even when the target outfit is dark).
    push_status("remnant_scan")
    src_arr = np.asarray(source).astype(np.int16)
    try:
        arr = np.asarray(current).astype(np.int16)
        unchanged = np.abs(arr - src_arr).mean(axis=2) < REMNANT_DIFF_MAX
        prot = np.array(protect_grown) > 127
        remnant_b = unchanged & dress_b & ~prot
        status["remnant_px"] = int(remnant_b.sum())
        log(f"remnant px: {status['remnant_px']}")
        if remnant_b.sum() >= REMNANT_MIN_PX:
            push_status("remnant_cleanup")
            remnant_mask = bool_to_mask(remnant_b, grow=15, blur=5)
            remnant_mask = ImageChops.subtract(remnant_mask, protect_grown)
            upload_img("05_mask_remnant", remnant_mask)
            g3 = torch.Generator("cuda").manual_seed(SEED + 2)
            raw = pipe(prompt=subject_prompt, negative_prompt=neg, image=current,
                       mask_image=remnant_mask, strength=0.95,
                       num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                       width=W, height=H, generator=g3).images[0]
            current = paste_back(raw, current, remnant_mask)
            upload_img("06_after_remnant_cleanup", current)
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"remnant_cleanup: {e!r}")
        log(f"remnant cleanup FAILED (continuing with pass-1 result): {e!r}")

    # ── pass 2: background/scene ──────────────────────────────────────
    push_status("inpaint_scene")
    g2 = torch.Generator("cuda").manual_seed(SEED + 1)
    raw_bg = pipe(prompt=scene_prompt,
                  negative_prompt="people, person, crowd, deformed, blurry, "
                                  "lowres, watermark, text",
                  image=current, mask_image=bg_mask, strength=0.99,
                  num_inference_steps=STEPS, guidance_scale=GUIDANCE,
                  width=W, height=H, generator=g2).images[0]
    current = paste_back(raw_bg, current, bg_mask)
    upload_img("07_after_scene", current)

    # ── E5.2: harmonization pass (always on) ──────────────────────────
    # One low-strength img2img over the WHOLE frame fuses person/scene
    # lighting and grain, then the protect region (face, hair, arms/tattoos,
    # bag) is restored from the SOURCE through a feathered alpha — identity
    # pixels survive harmonization bit-for-bit at the core, blended at edges.
    push_status("harmonize")
    try:
        full = Image.new("L", (W, H), 255)
        g4 = torch.Generator("cuda").manual_seed(SEED + 3)
        raw_h = pipe(prompt=subject_prompt + ", cohesive lighting, film grain, "
                     "seamless composition",
                     negative_prompt=neg, image=current, mask_image=full,
                     strength=HARMONIZE_STRENGTH, num_inference_steps=24,
                     guidance_scale=6.0, width=W, height=H,
                     generator=g4).images[0]
        protect_alpha = Image.fromarray(
            (protect_b.astype("uint8") * 255), "L").filter(
            ImageFilter.GaussianBlur(PROTECT_RESTORE_BLUR))
        current = Image.composite(source, raw_h.convert("RGB"), protect_alpha)
        upload_img("08_after_harmonize", current)
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"harmonize: {e!r}")
        log(f"harmonize FAILED (continuing with pre-harmonize result): {e!r}")

    # ── E5.3: quality metrics for the backend gate ────────────────────
    push_status("quality_metrics")
    try:
        farr = np.asarray(current).astype(np.int16)
        fluma = (farr[..., 0] * 299 + farr[..., 1] * 587 + farr[..., 2] * 114) // 1000

        # Remnants surviving to the FINAL image: source dress pixels unchanged.
        prot = np.array(protect_grown) > 127
        unchanged_f = np.abs(farr - src_arr).mean(axis=2) < REMNANT_DIFF_MAX
        remnant_final = int((unchanged_f & dress_b & ~prot).sum())

        # Seam harshness: gradient energy in a thin band around the person
        # silhouette vs. the whole frame. A hard cut-out spikes this ratio.
        person = Image.fromarray(((~bg_b).astype("uint8") * 255), "L")
        ring = np.array(ImageChops.subtract(
            person.filter(ImageFilter.MaxFilter(SEAM_RING_PX)),
            person.filter(ImageFilter.MinFilter(SEAM_RING_PX)))) > 127
        gy, gx = np.gradient(fluma.astype("float32"))
        gmag = np.sqrt(gx * gx + gy * gy)
        global_grad = float(gmag.mean()) or 1e-6
        seam_ratio = float(gmag[ring].mean() / global_grad) if ring.any() else 0.0

        status["quality"] = {"remnant_px_final": remnant_final,
                             "seam_ratio": round(seam_ratio, 3),
                             "seam_ring_px": int(ring.sum())}
        log(f"quality: {status['quality']}")
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"quality_metrics: {e!r}")
        log(f"quality metrics FAILED: {e!r}")

    upload_img("99_final", current)
    status["done"] = True
    push_status("done")
    log("E5 self-hosted editor pipeline complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"fatal: {e!r}")
        LOG.append(traceback.format_exc()[-1500:])
        push_status("fatal")
        raise
