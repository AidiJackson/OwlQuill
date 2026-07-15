"""Pod-side Sprint 22 — CANON-CARD GROUNDING proof-of-concept.

Copy of the proven comfyui_proof_pod_inpaint.py (Sprint 14/15A) with EXACTLY two
deltas, so the comparison isolates "show the model Summer" vs "ask it to remember":
  1. Base checkpoint is RealVisXL (BASE_MODEL_ID env, default SG161222/RealVisXL_V4.0)
     — matching the Sprint 20 RealVisXL baseline this run is compared against.
  2. The BASE generation pass is visually grounded on Summer's locked canon cards:
     the already-loaded IP-Adapter gets [face_front, body_front] (FACE_REF_URL /
     BODY_REF_URL envs) at CANON_IP_SCALE (default 0.5) instead of scale 0.0.
The tattoo passes (butterfly IP-Adapter 0.7, ballerina ControlNet-Canny region-zoom)
are byte-identical to Sprint 15A — no tattoo changes, no face-detail pass.

Runs ON the RunPod GPU pod. Defensive: every stage wrapped, partial images +
status.json streamed to R2 so the orchestrator can observe/retrieve even on death.
The startup wrapper self-terminates the pod regardless of exit.
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


RUN_ID = os.environ.get("PROOF_RUN_ID", "run")
R2_PUBLIC = os.environ["R2_PUBLIC_URL"].rstrip("/")
LORA_URL = os.environ["LORA_URL"]
BUTTERFLY_URL = os.environ["BUTTERFLY_URL"]
BALLERINA_URL = os.environ["BALLERINA_URL"]
FACE_REF_URL = os.environ["FACE_REF_URL"]
BODY_REF_URL = os.environ["BODY_REF_URL"]
BASE_MODEL_ID = os.environ.get("BASE_MODEL_ID", "SG161222/RealVisXL_V4.0")
CANON_IP_SCALE = float(os.environ.get("CANON_IP_SCALE", "0.5"))
W, H = 832, 1216

import boto3  # noqa: E402

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)
BUCKET = os.environ["R2_BUCKET_NAME"]

status = {"run_id": RUN_ID, "stage": "start", "images": {}, "errors": [], "done": False}


def push_status(stage):
    status["stage"] = stage
    status["log"] = LOG
    try:
        s3.put_object(Bucket=BUCKET, Key=f"proof/{RUN_ID}/status.json",
                      Body=json.dumps(status, indent=2).encode(), ContentType="application/json")
    except Exception as e:  # noqa: BLE001
        print("status push failed:", e, flush=True)


def upload_img(name, pil):
    b = io.BytesIO()
    pil.save(b, "PNG")
    key = f"proof/{RUN_ID}/{name}.png"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b.getvalue(), ContentType="image/png")
    url = f"{R2_PUBLIC}/{key}"
    status["images"][name] = url
    log(f"uploaded {name}: {url}")
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
    import cv2
    import numpy as np
    import torch
    import torch.nn.functional as Fnn
    from PIL import Image, ImageFilter

    push_status("download_inputs")
    fetch(LORA_URL, "/tmp/lora.tar")
    with tarfile.open("/tmp/lora.tar") as t:
        t.extractall("/tmp/lora")
    lora_path = None
    for root, _, files in os.walk("/tmp/lora"):
        for f in files:
            if f.endswith(".safetensors"):
                lora_path = os.path.join(root, f)
    log(f"lora: {lora_path}")
    fetch_r2(BUTTERFLY_URL, "/tmp/butterfly.png")
    fetch_r2(BALLERINA_URL, "/tmp/ballerina.png")
    butterfly = Image.open("/tmp/butterfly.png").convert("RGB")
    ballerina = Image.open("/tmp/ballerina.png").convert("RGB")
    fetch_r2(FACE_REF_URL, "/tmp/canon_face.png")
    fetch_r2(BODY_REF_URL, "/tmp/canon_body.png")
    canon_face = Image.open("/tmp/canon_face.png").convert("RGB")
    canon_body = Image.open("/tmp/canon_body.png").convert("RGB")
    log(f"canon cards: face={canon_face.size} body={canon_body.size} "
        f"ip_scale={CANON_IP_SCALE}")

    push_status("load_pipeline")
    from diffusers import ControlNetModel, StableDiffusionXLControlNetInpaintPipeline

    cn = ControlNetModel.from_pretrained(
        "diffusers/controlnet-canny-sdxl-1.0", torch_dtype=torch.float16)
    log(f"base model: {BASE_MODEL_ID}")
    try:
        pipe = StableDiffusionXLControlNetInpaintPipeline.from_pretrained(
            BASE_MODEL_ID, controlnet=cn,
            torch_dtype=torch.float16, variant="fp16").to("cuda")
    except Exception as e:  # noqa: BLE001 — some checkpoints ship no fp16 variant
        log(f"fp16 variant load failed ({e!r}); retrying without variant")
        pipe = StableDiffusionXLControlNetInpaintPipeline.from_pretrained(
            BASE_MODEL_ID, controlnet=cn, torch_dtype=torch.float16).to("cuda")
    status["base_model"] = BASE_MODEL_ID
    pipe.set_progress_bar_config(disable=True)
    try:
        pipe.load_lora_weights(lora_path)
        status["lora_loaded"] = True
        log("LoRA loaded OK")
    except Exception as e:  # noqa: BLE001
        status["lora_loaded"] = False
        status["errors"].append(f"lora_load: {e!r}")
        log(f"LoRA load FAILED: {e!r}")
    try:
        pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                             weight_name="ip-adapter_sdxl.bin")
        pipe.set_ip_adapter_scale(0.0)
        status["ip_adapter"] = True
    except Exception as e:  # noqa: BLE001
        status["ip_adapter"] = False
        status["errors"].append(f"ip_adapter: {e!r}")
        log(f"IP-Adapter load FAILED: {e!r}")

    blank_ctrl = Image.new("RGB", (W, H), (0, 0, 0))
    neg = ("hands on hips, arms akimbo, arms crossed, arms behind back, hands on waist, "
           "deformed, extra limbs, extra fingers, bad anatomy, blurry, lowres, watermark, "
           "text, multiple people")

    # ── Stage 1: base, CANON-GROUNDED (Sprint 22 delta) ──────────────────
    # Instead of asking the LoRA to *remember* Summer, the base pass also *sees* her:
    # the single loaded IP-Adapter receives both locked canon cards ([[face, body]] =
    # two images for one adapter) at CANON_IP_SCALE. The prompt still retains the
    # 'TOK' trigger + arms-at-sides framing so the LoRA fires and SegFormer can build
    # both arm masks for the (unchanged) tattoo passes.
    push_status("base_gen")
    if not status.get("ip_adapter"):
        raise RuntimeError("IP-Adapter failed to load — canon grounding impossible")
    base_prompt = os.environ.get("BASE_PROMPT") or (
        "a photo of TOK, an adult woman with long blonde hair and blue eyes, wearing a "
        "blue bikini, standing straight facing camera, both arms straight and relaxed "
        "at her sides, arms hanging down alongside the body, forearms fully visible, "
        "palms near thighs, full body, plain studio background, natural light, photorealistic"
    )
    log(f"base_prompt[:80]={base_prompt[:80]!r}")
    grey = Image.new("RGB", (W, H), (127, 127, 127))
    full = Image.new("L", (W, H), 255)
    g = torch.Generator("cuda").manual_seed(7)
    pipe.set_ip_adapter_scale(CANON_IP_SCALE)
    base = pipe(prompt=base_prompt, negative_prompt=neg, image=grey, mask_image=full,
                control_image=blank_ctrl, controlnet_conditioning_scale=0.0,
                ip_adapter_image=[[canon_face, canon_body]], strength=1.0,
                num_inference_steps=32,
                guidance_scale=7.0, width=W, height=H, generator=g).images[0]
    pipe.set_ip_adapter_scale(0.0)
    status["canon_grounding"] = {"ip_scale": CANON_IP_SCALE,
                                 "face_ref": FACE_REF_URL, "body_ref": BODY_REF_URL}
    upload_img("01_base", base)

    # ── Stage 2: SegFormer per-arm masks ─────────────────────────────────
    push_status("arm_masks")
    masks = {}
    try:
        from transformers import AutoModelForSemanticSegmentation, SegformerImageProcessor

        proc = SegformerImageProcessor.from_pretrained("mattmdjaga/segformer_b2_clothes")
        seg_model = AutoModelForSemanticSegmentation.from_pretrained(
            "mattmdjaga/segformer_b2_clothes").to("cuda")
        inp = proc(images=base, return_tensors="pt").to("cuda")
        with torch.no_grad():
            logits = seg_model(**inp).logits
        seg = Fnn.interpolate(logits, size=(H, W), mode="bilinear", align_corners=False
                              ).argmax(1)[0].cpu().numpy()
        right_arm = seg == 15   # Right-arm
        left_arm = seg == 14    # Left-arm
        log(f"arm pixels right={int(right_arm.sum())} left={int(left_arm.sum())}")

        def mask_from_bool(b):
            m = Image.fromarray((b.astype("uint8") * 255), "L").filter(ImageFilter.MaxFilter(15))
            return m.filter(ImageFilter.GaussianBlur(6))

        def half(b, which, drop_bottom_frac=0.0):
            ys = np.where(b.any(axis=1))[0]
            if len(ys) == 0:
                return b
            ymin, ymax = int(ys.min()), int(ys.max())
            ymid = (ymin + ymax) // 2
            out = b.copy()
            if which == "upper":
                # The anatomical elbow sits at ~38-40% of the shoulder->fingertip
                # span, not the midpoint: a 50% cut leaks ~100px below the elbow
                # onto the forearm (Sprint 14 butterfly drift). Cut at 40% so the
                # upper-arm mask stops at the elbow.
                cut = ymin + int(0.40 * (ymax - ymin))
                out[cut:, :] = False
            else:  # lower (forearm) — keep the forearm band, DROP the wrist + hand
                out[:ymid, :] = False
                if drop_bottom_frac > 0:
                    # The hand/fingers sit at the very bottom of the arm bbox (SegFormer
                    # has no hand class). Cut the bottom fraction of the lower-arm span so
                    # the mask targets the forearm tattoo zone only — never the hand.
                    cut = ymax - int(drop_bottom_frac * (ymax - ymid))
                    out[cut:, :] = False
            return out

        if right_arm.sum() > 400:
            ub = half(right_arm, "upper")
            uys, uxs = np.where(ub)
            log(f"right_upper_arm cut bbox: x={int(uxs.min())}-{int(uxs.max())} "
                f"y={int(uys.min())}-{int(uys.max())}")
            masks["right_upper_arm"] = mask_from_bool(ub)
            upload_img("02_mask_right_upper_arm", masks["right_upper_arm"].convert("RGB"))
        if left_arm.sum() > 400:
            # Exclude the bottom ~38% of the lower arm (wrist + hand + fingers).
            masks["left_forearm"] = mask_from_bool(half(left_arm, "lower", drop_bottom_frac=0.38))
            upload_img("02_mask_left_forearm", masks["left_forearm"].convert("RGB"))
        log(f"arm masks: {list(masks.keys())}")
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"arm_mask: {e!r}")
        log(f"arm-mask FAILED: {e!r}")

    current = base

    def paste_back(new_img, base_img, mask_l):
        """Quality-preserving composite: keep base pixels OUTSIDE the (feathered) tattoo
        mask, use the inpaint ONLY inside it. The whole-frame inpaint regenerates the full
        image (and would globally degrade face/eyes/hands/background via the VAE round-trip),
        so we discard everything except the masked tattoo zone. The feathered mask edge
        blends the seam. Guarantees non-tattoo pixels == base, bit-for-bit where mask==0.
        """
        return Image.composite(new_img.convert("RGB"), base_img.convert("RGB"), mask_l)

    # ── Stage 3a: butterfly via IP-Adapter on right upper arm ────────────
    if "right_upper_arm" in masks and status.get("ip_adapter"):
        push_status("inpaint_butterfly")
        try:
            pipe.set_ip_adapter_scale(0.7)
            raw = pipe(
                prompt="a photo of TOK, blonde woman, blue bikini, intricate black-ink "
                       "butterfly and floral sleeve tattoo on the right upper arm, photorealistic skin",
                negative_prompt=neg, image=current, mask_image=masks["right_upper_arm"],
                control_image=blank_ctrl, controlnet_conditioning_scale=0.0,
                ip_adapter_image=butterfly, strength=0.6, num_inference_steps=32,
                guidance_scale=7.0, width=W, height=H,
                generator=torch.Generator("cuda").manual_seed(21)).images[0]
            # Keep ONLY the masked tattoo zone; preserve all other pixels from base.
            current = paste_back(raw, current, masks["right_upper_arm"])
            upload_img("03_after_butterfly", current)
        except Exception as e:  # noqa: BLE001
            status["errors"].append(f"butterfly: {e!r}")
            log(f"butterfly FAILED: {e!r}")
            traceback.print_exc()

    # ── Stage 3b: ballerina via ControlNet-Canny on left forearm ─────────
    if "left_forearm" in masks:
        push_status("inpaint_ballerina")
        try:
            mask_l = masks["left_forearm"]
            m = np.array(mask_l) > 127
            ys, xs = np.where(m)
            x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())

            # Region-zoom (Sprint 15A): the forearm bbox is ~107x249px — ~13x31 SDXL
            # latents, far too small to render a recognisable figure, which is why the
            # whole-frame pass produced faint generic linework. Inpaint a 3x-upscaled
            # crop around the bbox instead, then downscale + paste back. The final
            # feathered composite is unchanged, so pixels outside the tattoo mask still
            # come from `current` bit-for-bit (Sprint 14 quality guarantee).
            PAD, ZOOM = 48, 3
            cx0, cy0 = max(0, x0 - PAD), max(0, y0 - PAD)
            cw = min(W - cx0, ((x1 + 1 + PAD - cx0 + 7) // 8) * 8)
            ch = min(H - cy0, ((y1 + 1 + PAD - cy0 + 7) // 8) * 8)
            cw -= cw % 8
            ch -= ch % 8
            cx1, cy1 = cx0 + cw, cy0 + ch
            zw, zh = cw * ZOOM, ch * ZOOM
            log(f"ballerina zoom: mask bbox=({x0},{y0})-({x1},{y1}) "
                f"crop=({cx0},{cy0})+{cw}x{ch} -> {zw}x{zh}")

            crop_img = current.crop((cx0, cy0, cx1, cy1)).resize((zw, zh), Image.LANCZOS)
            crop_mask = mask_l.crop((cx0, cy0, cx1, cy1)).resize((zw, zh), Image.LANCZOS)

            # Fit the reference edges inside the ZOOMED mask bbox (3x the pixels the
            # whole-frame pass offered the figure).
            mz = np.array(crop_mask) > 127
            zys, zxs = np.where(mz)
            zx0, zx1, zy0, zy1 = int(zxs.min()), int(zxs.max()), int(zys.min()), int(zys.max())
            bw, bh = max(8, zx1 - zx0), max(8, zy1 - zy0)
            edges = cv2.Canny(np.array(ballerina), 80, 180)
            ep = Image.fromarray(edges).convert("RGB")
            cr = ballerina.width / ballerina.height
            if bw / bh > cr:
                nh, nw = bh, max(8, int(bh * cr))
            else:
                nw, nh = bw, max(8, int(bw / cr))
            # Re-binarize after resize: resampling averages the 0/255 edge map toward
            # grey (max ~112/255 in Sprint 14), halving the ControlNet signal.
            ep = ep.resize((nw, nh)).point(lambda v: 255 if v > 40 else 0)
            ctrl = Image.new("RGB", (zw, zh), (0, 0, 0))
            ctrl.paste(ep, (zx0 + (bw - nw) // 2, zy0 + (bh - nh) // 2))
            upload_img("03b_ballerina_canny_control", ctrl)

            pipe.set_ip_adapter_scale(0.0)
            raw = pipe(
                prompt="a photo of TOK, blonde woman, blue bikini, detailed black-and-white "
                       "ballerina dancer tattoo on the left forearm, fine black linework, photorealistic skin",
                negative_prompt=neg, image=crop_img, mask_image=crop_mask,
                control_image=ctrl, controlnet_conditioning_scale=0.85,
                ip_adapter_image=ballerina, strength=0.6, num_inference_steps=34,
                guidance_scale=7.5, width=zw, height=zh,
                generator=torch.Generator("cuda").manual_seed(33)).images[0]
            # Downscale the inpainted crop into place, then composite through the
            # feathered mask: only the forearm tattoo zone changes; the hand and
            # everything else stay base pixels.
            full_new = current.copy()
            full_new.paste(raw.resize((cw, ch), Image.LANCZOS), (cx0, cy0))
            current = paste_back(full_new, current, mask_l)
            upload_img("04_after_ballerina", current)
        except Exception as e:  # noqa: BLE001
            status["errors"].append(f"ballerina: {e!r}")
            log(f"ballerina FAILED: {e!r}")
            traceback.print_exc()

    upload_img("99_final", current)
    status["done"] = True
    push_status("done")
    log("PROOF COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"FATAL: {e!r}")
        status["errors"].append(f"fatal: {e!r}")
        traceback.print_exc()
        status["done"] = True
        push_status("fatal")
