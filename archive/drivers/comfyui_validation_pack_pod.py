"""Pod-side — Summer Adult Studio FOUNDER VALIDATION PACK (Sprint 10, 5 outfits).

Runs ON the RunPod GPU pod. Loads the SDXL+LoRA+IP-Adapter+ControlNet pipeline and
SegFormer ONCE, then for EACH of 5 outfits runs the full enforcement:
  base SDXL + Summer LoRA (outfit, arms at sides) -> SegFormer arm masks ->
  butterfly IP-Adapter pass (right upper arm) -> ballerina ControlNet-Canny pass (left
  forearm) -> 99_final. Every stage streamed to R2 under proof/<RUN_ID>/<outfit>/...

Defensive: each outfit and each stage is wrapped; partial images + status.json are
streamed so the orchestrator can observe/retrieve even on death. The startup wrapper
self-terminates the pod regardless of exit.
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

# 5 founder-validation outfits. All sleeveless / arms-exposed + arms-at-sides so BOTH
# tattoos (right upper arm sleeve, left forearm ballerina) are visible for review.
OUTFITS = [
    ("casual", "wearing a casual relaxed sleeveless cropped top and high-waisted blue jeans"),
    ("sleeveless_top", "wearing a fitted plain white ribbed sleeveless tank top and denim shorts"),
    ("cocktail_dress", "wearing an elegant sleeveless fitted black cocktail dress"),
    ("swimwear", "wearing a light blue bikini"),
    ("fitness", "wearing a sleeveless athletic sports bra and fitted gym leggings"),
]

import boto3  # noqa: E402

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)
BUCKET = os.environ["R2_BUCKET_NAME"]

status = {"run_id": RUN_ID, "stage": "start", "outfits": {}, "errors": [], "done": False}


def push_status(stage):
    status["stage"] = stage
    status["log"] = LOG
    try:
        s3.put_object(Bucket=BUCKET, Key=f"proof/{RUN_ID}/status.json",
                      Body=json.dumps(status, indent=2).encode(),
                      ContentType="application/json")
    except Exception as e:  # noqa: BLE001
        print("status push failed:", e, flush=True)


def upload_img(outfit, name, pil):
    b = io.BytesIO()
    pil.save(b, "PNG")
    key = f"proof/{RUN_ID}/{outfit}/{name}.png"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b.getvalue(), ContentType="image/png")
    url = f"{R2_PUBLIC}/{key}"
    status["outfits"][outfit]["images"][name] = url
    log(f"  uploaded {outfit}/{name}")
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

    # ── One-time loads ────────────────────────────────────────────────────────
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
    lora_ok = False
    try:
        pipe.load_lora_weights(lora_path)
        lora_ok = True
        log("LoRA loaded OK")
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"lora_load: {e!r}")
        log(f"LoRA load FAILED: {e!r}")
    status["lora_loaded"] = lora_ok
    ip_ok = False
    try:
        pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                             weight_name="ip-adapter_sdxl.bin")
        pipe.set_ip_adapter_scale(0.0)
        ip_ok = True
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"ip_adapter: {e!r}")
        log(f"IP-Adapter load FAILED: {e!r}")
    status["ip_adapter_loaded"] = ip_ok

    # SegFormer human-parsing (loaded once).
    from transformers import AutoModelForSemanticSegmentation, SegformerImageProcessor
    seg_proc = SegformerImageProcessor.from_pretrained("mattmdjaga/segformer_b2_clothes")
    seg_model = AutoModelForSemanticSegmentation.from_pretrained(
        "mattmdjaga/segformer_b2_clothes").to("cuda")

    blank_ctrl = Image.new("RGB", (W, H), (0, 0, 0))
    neg = ("hands on hips, arms akimbo, arms crossed, arms behind back, hands on waist, "
           "deformed, extra limbs, extra fingers, bad anatomy, blurry, lowres, watermark, "
           "text, multiple people")

    def seg_masks(base):
        inp = seg_proc(images=base, return_tensors="pt").to("cuda")
        with torch.no_grad():
            logits = seg_model(**inp).logits
        seg = Fnn.interpolate(logits, size=(H, W), mode="bilinear", align_corners=False
                              ).argmax(1)[0].cpu().numpy()
        right_arm = seg == 15
        left_arm = seg == 14

        def mask_from_bool(b):
            m = Image.fromarray((b.astype("uint8") * 255), "L").filter(ImageFilter.MaxFilter(15))
            return m.filter(ImageFilter.GaussianBlur(6))

        def half(b, which):
            ys = np.where(b.any(axis=1))[0]
            if len(ys) == 0:
                return b
            ymid = (ys.min() + ys.max()) // 2
            out = b.copy()
            if which == "upper":
                out[ymid:, :] = False
            else:
                out[:ymid, :] = False
            return out

        masks = {}
        if right_arm.sum() > 400:
            masks["right_upper_arm"] = mask_from_bool(half(right_arm, "upper"))
        if left_arm.sum() > 400:
            masks["left_forearm"] = mask_from_bool(half(left_arm, "lower"))
        return masks, int(right_arm.sum()), int(left_arm.sum())

    # ── Per-outfit enforcement ────────────────────────────────────────────────
    def run_outfit(key, desc):
        o = status["outfits"][key] = {"desc": desc, "images": {}, "routes": {},
                                      "started_at": time.time(), "errors": []}
        push_status(f"{key}:base")
        base_prompt = (
            f"a photo of TOK, an adult woman with long blonde hair and blue eyes, {desc}, "
            "standing straight facing camera, both arms straight and relaxed at her sides, "
            "arms hanging down alongside the body, forearms fully visible, palms near thighs, "
            "full body, plain studio background, natural light, photorealistic")
        grey = Image.new("RGB", (W, H), (127, 127, 127))
        full = Image.new("L", (W, H), 255)
        pipe.set_ip_adapter_scale(0.0)
        base = pipe(prompt=base_prompt, negative_prompt=neg, image=grey, mask_image=full,
                    control_image=blank_ctrl, controlnet_conditioning_scale=0.0,
                    ip_adapter_image=butterfly, strength=1.0, num_inference_steps=32,
                    guidance_scale=7.0, width=W, height=H,
                    generator=torch.Generator("cuda").manual_seed(7)).images[0]
        upload_img(key, "01_base", base)
        current = base

        # Masks
        try:
            push_status(f"{key}:masks")
            masks, rp, lp = seg_masks(base)
            o["arm_pixels"] = {"right": rp, "left": lp}
            for mk in masks:
                upload_img(key, f"02_mask_{mk}", masks[mk].convert("RGB"))
        except Exception as e:  # noqa: BLE001
            masks = {}
            o["errors"].append(f"masks: {e!r}")
            log(f"  {key} masks FAILED: {e!r}")

        # Butterfly via IP-Adapter (right upper arm)
        if "right_upper_arm" in masks and ip_ok:
            try:
                push_status(f"{key}:butterfly")
                pipe.set_ip_adapter_scale(0.7)
                current = pipe(
                    prompt=f"a photo of TOK, blonde woman, {desc}, intricate black-ink butterfly "
                           "and floral sleeve tattoo on the right upper arm, photorealistic skin",
                    negative_prompt=neg, image=current, mask_image=masks["right_upper_arm"],
                    control_image=blank_ctrl, controlnet_conditioning_scale=0.0,
                    ip_adapter_image=butterfly, strength=0.9, num_inference_steps=32,
                    guidance_scale=7.0, width=W, height=H,
                    generator=torch.Generator("cuda").manual_seed(21)).images[0]
                upload_img(key, "03_after_butterfly", current)
                o["routes"]["ip_adapter"] = "executed"
            except Exception as e:  # noqa: BLE001
                o["routes"]["ip_adapter"] = f"error: {e!r}"
                o["errors"].append(f"butterfly: {e!r}")
                log(f"  {key} butterfly FAILED: {e!r}")
        else:
            o["routes"]["ip_adapter"] = "skipped_no_mask" if ip_ok else "skipped_no_ipadapter"

        # Ballerina via ControlNet-Canny (left forearm)
        if "left_forearm" in masks:
            try:
                push_status(f"{key}:ballerina")
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
                upload_img(key, "03b_ballerina_canny_control", ctrl)
                # IP-Adapter is loaded on the UNet, so ip_adapter_image MUST be passed
                # even with scale 0.0 (else the UNet errors on missing image_embeds).
                pipe.set_ip_adapter_scale(0.0)
                current = pipe(
                    prompt=f"a photo of TOK, blonde woman, {desc}, detailed black-and-white "
                           "ballerina dancer tattoo on the left forearm, fine black linework, "
                           "photorealistic skin",
                    negative_prompt=neg, image=current, mask_image=masks["left_forearm"],
                    control_image=ctrl, controlnet_conditioning_scale=0.85,
                    ip_adapter_image=ballerina, strength=0.97,
                    num_inference_steps=34, guidance_scale=7.5, width=W, height=H,
                    generator=torch.Generator("cuda").manual_seed(33)).images[0]
                upload_img(key, "04_after_ballerina", current)
                o["routes"]["controlnet_canny"] = "executed"
            except Exception as e:  # noqa: BLE001
                o["routes"]["controlnet_canny"] = f"error: {e!r}"
                o["errors"].append(f"ballerina: {e!r}")
                log(f"  {key} ballerina FAILED: {e!r}")
        else:
            o["routes"]["controlnet_canny"] = "skipped_no_mask"

        upload_img(key, "99_final", current)
        o["ended_at"] = time.time()
        o["runtime_s"] = round(o["ended_at"] - o["started_at"], 1)
        o["final_done"] = True
        torch.cuda.empty_cache()
        log(f"outfit {key} DONE in {o['runtime_s']}s routes={o['routes']}")

    for key, desc in OUTFITS:
        try:
            run_outfit(key, desc)
        except Exception as e:  # noqa: BLE001
            status["errors"].append(f"outfit_{key}: {e!r}")
            log(f"outfit {key} FATAL: {e!r}")
            traceback.print_exc()

    status["done"] = True
    push_status("done")
    log("VALIDATION PACK COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"FATAL: {e!r}")
        status["errors"].append(f"fatal: {e!r}")
        traceback.print_exc()
        status["done"] = True
        push_status("fatal")
