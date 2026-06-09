"""Pod-side headless proof v2 — ControlNet-Canny ballerina + arms-at-sides pose.

Runs ON the RunPod GPU pod. Defensive: every stage wrapped, partial images +
status.json streamed to R2 so the orchestrator can observe/retrieve even on death.
The startup wrapper self-terminates the pod regardless of exit.

Pipeline (rough proof):
  base SDXL + Summer v2 LoRA  -> base image (Summer, blue bikini, arms at sides)
  SegFormer human-parsing     -> right-upper-arm + left-forearm masks
  butterfly pass : IP-Adapter (butterfly/floral crop)         on right upper arm
  ballerina pass : ControlNet-Canny (edges of ballerina crop) on left forearm
One StableDiffusionXLControlNetInpaintPipeline serves all roles by toggling
controlnet_conditioning_scale and ip_adapter_scale.
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

    push_status("load_pipeline")
    from diffusers import ControlNetModel, StableDiffusionXLControlNetInpaintPipeline

    cn = ControlNetModel.from_pretrained(
        "diffusers/controlnet-canny-sdxl-1.0", torch_dtype=torch.float16)
    pipe = StableDiffusionXLControlNetInpaintPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0", controlnet=cn,
        torch_dtype=torch.float16, variant="fp16").to("cuda")
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

    # ── Stage 1: base, arms straight & relaxed at sides ──────────────────
    push_status("base_gen")
    # Founder run: scene comes from BASE_PROMPT (env). The composed prompt MUST retain
    # the 'TOK' LoRA trigger + arms-at-sides/forearms-visible framing so the Summer LoRA
    # fires and SegFormer can build both arm masks for tattoo enforcement. Falls back to
    # the original hardcoded studio prompt if BASE_PROMPT is unset.
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
    base = pipe(prompt=base_prompt, negative_prompt=neg, image=grey, mask_image=full,
                control_image=blank_ctrl, controlnet_conditioning_scale=0.0,
                ip_adapter_image=butterfly, strength=1.0, num_inference_steps=32,
                guidance_scale=7.0, width=W, height=H, generator=g).images[0]
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
                out[ymid:, :] = False
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
            masks["right_upper_arm"] = mask_from_bool(half(right_arm, "upper"))
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
            m = np.array(masks["left_forearm"]) > 127
            ys, xs = np.where(m)
            x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
            bw, bh = max(8, x1 - x0), max(8, y1 - y0)
            edges = cv2.Canny(np.array(ballerina), 80, 180)
            ep = Image.fromarray(edges).convert("RGB")
            cr = ballerina.width / ballerina.height
            if bw / bh > cr:
                nh, nw = bh, max(8, int(bh * cr))
            else:
                nw, nh = bw, max(8, int(bw / cr))
            ep = ep.resize((nw, nh))
            ctrl = Image.new("RGB", (W, H), (0, 0, 0))
            ctrl.paste(ep, (x0 + (bw - nw) // 2, y0 + (bh - nh) // 2))
            upload_img("03b_ballerina_canny_control", ctrl)

            pipe.set_ip_adapter_scale(0.0)
            raw = pipe(
                prompt="a photo of TOK, blonde woman, blue bikini, detailed black-and-white "
                       "ballerina dancer tattoo on the left forearm, fine black linework, photorealistic skin",
                negative_prompt=neg, image=current, mask_image=masks["left_forearm"],
                control_image=ctrl, controlnet_conditioning_scale=0.85,
                ip_adapter_image=ballerina, strength=0.6, num_inference_steps=34,
                guidance_scale=7.5, width=W, height=H,
                generator=torch.Generator("cuda").manual_seed(33)).images[0]
            # Keep ONLY the forearm tattoo zone; preserve the hand + everything else.
            current = paste_back(raw, current, masks["left_forearm"])
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
