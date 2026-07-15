"""Pod-side Sprint 23B — IDENTITY & QUALITY STACK (throwaway, founder-only).

Best-of-4 candidates (fixed seeds), each through the full commercial-style stack:

  1. base gen   : RealVisXL + Summer LoRA + canon grounding [face+body]@0.5
                  (EXACTLY the proven Sprint 23A variant-A config)
  2. tattoos    : UNCHANGED Sprint 15A enforcement (butterfly IP-Adapter,
                  ballerina ControlNet-Canny region-zoom, feathered paste-back)
  3. hires      : 1.5x upscale + low-strength img2img re-detail (832x1216 -> 1248x1824)
  4. face refine: IP-Adapter-FaceID (SDXL) inpaint on the SegFormer face region —
                  identity enters as a 512-d ArcFace embedding (FACE_EMBED_KEY on R2,
                  precomputed from Summer's canon face card), NOT a whole image, so
                  composition cannot be captured. Falls back to a plain detailer pass
                  if FaceID cannot load (status.faceid_loaded=false).

EXPERIMENT-ONLY LICENSING: IP-Adapter-FaceID weights + InsightFace embeddings are
non-commercial research artifacts. This path must NOT ship to production as-is.

Defensive: every stage wrapped; partial images + status.json streamed to R2 under
proof/<RUN_ID>/<candidate>/...; the startup wrapper self-terminates the pod.
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
FACE_EMBED_KEY = os.environ["FACE_EMBED_KEY"]
BASE_MODEL_ID = os.environ.get("BASE_MODEL_ID", "SG161222/RealVisXL_V4.0")
CANON_IP_SCALE = 0.5         # proven 23A-A base grounding
FACEID_SCALE = 0.8           # identity strength in the face-refine pass
HIRES_FACTOR = 1.5
HIRES_STRENGTH = 0.30
FACE_REFINE_STRENGTH = 0.45
SEEDS = [7, 1007, 2007, 3007]
W, H = 832, 1216
HW, HH = int(W * HIRES_FACTOR), int(H * HIRES_FACTOR)  # 1248x1824, /8 ok

import boto3  # noqa: E402

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)
BUCKET = os.environ["R2_BUCKET_NAME"]

status = {"run_id": RUN_ID, "stage": "start", "candidates": {}, "errors": [],
          "done": False, "base_model": BASE_MODEL_ID, "faceid_loaded": None}


def push_status(stage):
    status["stage"] = stage
    status["log"] = LOG
    try:
        s3.put_object(Bucket=BUCKET, Key=f"proof/{RUN_ID}/status.json",
                      Body=json.dumps(status, indent=2).encode(),
                      ContentType="application/json")
    except Exception as e:  # noqa: BLE001
        print("status push failed:", e, flush=True)


def upload_img(cand, name, pil):
    b = io.BytesIO()
    pil.save(b, "PNG")
    key = f"proof/{RUN_ID}/{cand}/{name}.png"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b.getvalue(), ContentType="image/png")
    url = f"{R2_PUBLIC}/{key}"
    status["candidates"][cand]["images"][name] = url
    log(f"  uploaded {cand}/{name}")
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
    fetch_r2(FACE_EMBED_KEY, "/tmp/face_embed.json")
    face_embed = json.load(open("/tmp/face_embed.json"))["embedding"]
    log(f"canon cards: face={canon_face.size} body={canon_body.size} "
        f"embed_dim={len(face_embed)}")

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
    pipe.set_progress_bar_config(disable=True)
    pipe.enable_vae_tiling()  # 1248x1824 hires pass on a 20GB card
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
    if not status.get("ip_adapter"):
        raise RuntimeError("IP-Adapter failed to load — canon grounding impossible")

    from transformers import AutoModelForSemanticSegmentation, SegformerImageProcessor
    seg_proc = SegformerImageProcessor.from_pretrained("mattmdjaga/segformer_b2_clothes")
    seg_model = AutoModelForSemanticSegmentation.from_pretrained(
        "mattmdjaga/segformer_b2_clothes").to("cuda")

    def segment(pil_img):
        inp = seg_proc(images=pil_img, return_tensors="pt").to("cuda")
        with torch.no_grad():
            logits = seg_model(**inp).logits
        return Fnn.interpolate(logits, size=(H, W), mode="bilinear",
                               align_corners=False).argmax(1)[0].cpu().numpy()

    blank_ctrl = Image.new("RGB", (W, H), (0, 0, 0))
    neg = ("hands on hips, arms akimbo, arms crossed, arms behind back, hands on waist, "
           "deformed, extra limbs, extra fingers, bad anatomy, blurry, lowres, watermark, "
           "text, multiple people")
    base_prompt = os.environ.get("BASE_PROMPT") or (
        "a photo of TOK, an adult woman with long blonde hair and blue eyes, wearing a "
        "blue bikini, standing straight facing camera, both arms straight and relaxed "
        "at her sides, arms hanging down alongside the body, forearms fully visible, "
        "palms near thighs, full body, plain studio background, natural light, photorealistic"
    )
    log(f"base_prompt[:80]={base_prompt[:80]!r}")
    grey = Image.new("RGB", (W, H), (127, 127, 127))
    full = Image.new("L", (W, H), 255)

    def mask_from_bool(b, grow=15, blur=6):
        m = Image.fromarray((b.astype("uint8") * 255), "L").filter(
            ImageFilter.MaxFilter(grow))
        return m.filter(ImageFilter.GaussianBlur(blur))

    def half(b, which, drop_bottom_frac=0.0):
        ys = np.where(b.any(axis=1))[0]
        if len(ys) == 0:
            return b
        ymin, ymax = int(ys.min()), int(ys.max())
        ymid = (ymin + ymax) // 2
        out = b.copy()
        if which == "upper":
            cut = ymin + int(0.40 * (ymax - ymin))  # elbow ~40% (Sprint 15A)
            out[cut:, :] = False
        else:
            out[:ymid, :] = False
            if drop_bottom_frac > 0:
                cut = ymax - int(drop_bottom_frac * (ymax - ymid))
                out[cut:, :] = False
        return out

    def paste_back(new_img, base_img, mask_l):
        """Sprint 14 quality guarantee: outside the feathered mask, base bit-for-bit."""
        return Image.composite(new_img.convert("RGB"), base_img.convert("RGB"), mask_l)

    # ════ PHASE 1 (regular IP-Adapter): base + tattoos + hires per candidate ════
    face_segs = {}  # cand -> face bool mask at base res (for the refine pass)
    pre_face = {}   # cand -> hires image awaiting the face-refine pass
    for seed in SEEDS:
        cand = f"seed{seed}"
        status["candidates"][cand] = {"images": {}, "errors": [], "seed": seed}

        # ── base gen: EXACT 23A variant-A grounding ──────────────────────
        push_status(f"{cand}:base_gen")
        g = torch.Generator("cuda").manual_seed(seed)
        pipe.set_ip_adapter_scale(CANON_IP_SCALE)
        base = pipe(prompt=base_prompt, negative_prompt=neg, image=grey, mask_image=full,
                    control_image=blank_ctrl, controlnet_conditioning_scale=0.0,
                    ip_adapter_image=[[canon_face, canon_body]], strength=1.0,
                    num_inference_steps=32, guidance_scale=7.0,
                    width=W, height=H, generator=g).images[0]
        pipe.set_ip_adapter_scale(0.0)
        upload_img(cand, "01_base", base)

        # ── SegFormer masks (arms for tattoos + face for the refine pass) ──
        push_status(f"{cand}:masks")
        masks = {}
        try:
            seg = segment(base)
            right_arm, left_arm, face_b = seg == 15, seg == 14, seg == 11
            face_segs[cand] = face_b
            log(f"px right={int(right_arm.sum())} left={int(left_arm.sum())} "
                f"face={int(face_b.sum())}")
            if right_arm.sum() > 400:
                masks["right_upper_arm"] = mask_from_bool(half(right_arm, "upper"))
            if left_arm.sum() > 400:
                masks["left_forearm"] = mask_from_bool(
                    half(left_arm, "lower", drop_bottom_frac=0.38))
        except Exception as e:  # noqa: BLE001
            status["candidates"][cand]["errors"].append(f"masks: {e!r}")
            log(f"masks FAILED: {e!r}")

        current = base

        # ── butterfly via IP-Adapter (UNCHANGED Sprint 15A) ──────────────
        if "right_upper_arm" in masks:
            push_status(f"{cand}:butterfly")
            try:
                pipe.set_ip_adapter_scale(0.7)
                raw = pipe(
                    prompt="a photo of TOK, blonde woman, blue bikini, intricate black-ink "
                           "butterfly and floral sleeve tattoo on the right upper arm, "
                           "photorealistic skin",
                    negative_prompt=neg, image=current,
                    mask_image=masks["right_upper_arm"],
                    control_image=blank_ctrl, controlnet_conditioning_scale=0.0,
                    ip_adapter_image=butterfly, strength=0.6, num_inference_steps=32,
                    guidance_scale=7.0, width=W, height=H,
                    generator=torch.Generator("cuda").manual_seed(21)).images[0]
                current = paste_back(raw, current, masks["right_upper_arm"])
                upload_img(cand, "03_after_butterfly", current)
            except Exception as e:  # noqa: BLE001
                status["candidates"][cand]["errors"].append(f"butterfly: {e!r}")
                log(f"butterfly FAILED: {e!r}")
            finally:
                pipe.set_ip_adapter_scale(0.0)

        # ── ballerina via ControlNet-Canny region-zoom (UNCHANGED) ────────
        if "left_forearm" in masks:
            push_status(f"{cand}:ballerina")
            try:
                mask_l = masks["left_forearm"]
                m = np.array(mask_l) > 127
                ys, xs = np.where(m)
                x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
                PAD, ZOOM = 48, 3
                cx0, cy0 = max(0, x0 - PAD), max(0, y0 - PAD)
                cw = min(W - cx0, ((x1 + 1 + PAD - cx0 + 7) // 8) * 8)
                ch = min(H - cy0, ((y1 + 1 + PAD - cy0 + 7) // 8) * 8)
                cw -= cw % 8
                ch -= ch % 8
                cx1, cy1 = cx0 + cw, cy0 + ch
                zw, zh = cw * ZOOM, ch * ZOOM
                crop_img = current.crop((cx0, cy0, cx1, cy1)).resize((zw, zh), Image.LANCZOS)
                crop_mask = mask_l.crop((cx0, cy0, cx1, cy1)).resize((zw, zh), Image.LANCZOS)
                mz = np.array(crop_mask) > 127
                zys, zxs = np.where(mz)
                zx0, zx1, zy0, zy1 = (int(zxs.min()), int(zxs.max()),
                                      int(zys.min()), int(zys.max()))
                bw, bh = max(8, zx1 - zx0), max(8, zy1 - zy0)
                edges = cv2.Canny(np.array(ballerina), 80, 180)
                ep = Image.fromarray(edges).convert("RGB")
                cr = ballerina.width / ballerina.height
                if bw / bh > cr:
                    nh, nw = bh, max(8, int(bh * cr))
                else:
                    nw, nh = bw, max(8, int(bw / cr))
                ep = ep.resize((nw, nh)).point(lambda v: 255 if v > 40 else 0)
                ctrl = Image.new("RGB", (zw, zh), (0, 0, 0))
                ctrl.paste(ep, (zx0 + (bw - nw) // 2, zy0 + (bh - nh) // 2))
                raw = pipe(
                    prompt="a photo of TOK, blonde woman, blue bikini, detailed "
                           "black-and-white ballerina dancer tattoo on the left forearm, "
                           "fine black linework, photorealistic skin",
                    negative_prompt=neg, image=crop_img, mask_image=crop_mask,
                    control_image=ctrl, controlnet_conditioning_scale=0.85,
                    ip_adapter_image=ballerina, strength=0.6, num_inference_steps=34,
                    guidance_scale=7.5, width=zw, height=zh,
                    generator=torch.Generator("cuda").manual_seed(33)).images[0]
                full_new = current.copy()
                full_new.paste(raw.resize((cw, ch), Image.LANCZOS), (cx0, cy0))
                current = paste_back(full_new, current, mask_l)
                upload_img(cand, "04_after_ballerina", current)
            except Exception as e:  # noqa: BLE001
                status["candidates"][cand]["errors"].append(f"ballerina: {e!r}")
                log(f"ballerina FAILED: {e!r}")

        # ── hires: 1.5x upscale + low-strength re-detail ──────────────────
        push_status(f"{cand}:hires")
        try:
            up = current.resize((HW, HH), Image.LANCZOS)
            full_h = Image.new("L", (HW, HH), 255)
            blank_h = Image.new("RGB", (HW, HH), (0, 0, 0))
            raw = pipe(prompt=base_prompt + ", highly detailed skin texture, sharp focus",
                       negative_prompt=neg, image=up, mask_image=full_h,
                       control_image=blank_h, controlnet_conditioning_scale=0.0,
                       ip_adapter_image=butterfly, strength=HIRES_STRENGTH,
                       num_inference_steps=30, guidance_scale=6.0, width=HW, height=HH,
                       generator=torch.Generator("cuda").manual_seed(seed + 100)).images[0]
            current = raw
            upload_img(cand, "05_hires", current)
        except Exception as e:  # noqa: BLE001
            status["candidates"][cand]["errors"].append(f"hires: {e!r}")
            log(f"hires FAILED: {e!r} — continuing at base res")
            current = current.resize((HW, HH), Image.LANCZOS)
        pre_face[cand] = current

    # ════ PHASE 2: swap to IP-Adapter-FaceID, refine each face ════
    push_status("load_faceid")
    faceid_ok = False
    try:
        pipe.unload_ip_adapter()
        pipe.load_ip_adapter("h94/IP-Adapter-FaceID", subfolder=None,
                             weight_name="ip-adapter-faceid_sdxl.bin",
                             image_encoder_folder=None)
        pipe.set_ip_adapter_scale(FACEID_SCALE)
        faceid_ok = True
        log("FaceID adapter loaded OK")
    except Exception as e:  # noqa: BLE001
        status["errors"].append(f"faceid_load: {e!r}")
        log(f"FaceID load FAILED ({e!r}) — falling back to plain face detailer")
        try:
            pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                 weight_name="ip-adapter_sdxl.bin")
            pipe.set_ip_adapter_scale(0.0)
        except Exception as e2:  # noqa: BLE001
            status["errors"].append(f"ipadapter_reload: {e2!r}")
    status["faceid_loaded"] = faceid_ok

    if faceid_ok:
        pos = torch.tensor(face_embed, dtype=torch.float16).reshape(1, 1, 512)
        id_embeds = torch.cat([torch.zeros_like(pos), pos]).to("cuda")

    refine_prompt = ("close-up portrait photo of TOK, an adult woman with long blonde "
                     "hair and blue eyes, beautiful detailed face, detailed blue eyes, "
                     "natural skin texture, soft natural light, photorealistic")
    refine_neg = ("deformed face, asymmetric eyes, crossed eyes, blurry, lowres, "
                  "oversmoothed skin, plastic skin, watermark, text")

    for seed in SEEDS:
        cand = f"seed{seed}"
        current = pre_face[cand]
        face_b = face_segs.get(cand)
        if face_b is None or face_b.sum() < 300:
            status["candidates"][cand]["errors"].append("face_refine: no face region")
            upload_img(cand, "99_final", current)
            continue
        push_status(f"{cand}:face_refine")
        try:
            ys, xs = np.where(face_b)
            fx0, fx1 = int(xs.min()), int(xs.max())
            fy0, fy1 = int(ys.min()), int(ys.max())
            # scale base-res bbox to hires coords, pad 60% for hair/jaw context
            s = HIRES_FACTOR
            bw, bh = (fx1 - fx0) * s, (fy1 - fy0) * s
            px, py = int(bw * 0.6), int(bh * 0.6)
            cx0 = max(0, int(fx0 * s) - px)
            cy0 = max(0, int(fy0 * s) - py)
            cx1 = min(HW, int(fx1 * s) + px)
            cy1 = min(HH, int(fy1 * s) + py)
            cw, ch = (cx1 - cx0) // 8 * 8, (cy1 - cy0) // 8 * 8
            cx1, cy1 = cx0 + cw, cy0 + ch
            # upscale crop so its long side is 1024 (multiple of 8)
            sc = 1024 / max(cw, ch)
            zw, zh = int(cw * sc) // 8 * 8, int(ch * sc) // 8 * 8
            crop_img = current.crop((cx0, cy0, cx1, cy1)).resize((zw, zh), Image.LANCZOS)
            # face mask at hires, generous feather to blend hairline
            fmask = mask_from_bool(face_b, grow=31, blur=10).resize((HW, HH), Image.LANCZOS)
            crop_mask = fmask.crop((cx0, cy0, cx1, cy1)).resize((zw, zh), Image.LANCZOS)
            blank_c = Image.new("RGB", (zw, zh), (0, 0, 0))
            kw = dict(prompt=refine_prompt, negative_prompt=refine_neg,
                      image=crop_img, mask_image=crop_mask, control_image=blank_c,
                      controlnet_conditioning_scale=0.0,
                      strength=FACE_REFINE_STRENGTH, num_inference_steps=32,
                      guidance_scale=6.5, width=zw, height=zh,
                      generator=torch.Generator("cuda").manual_seed(seed + 200))
            if faceid_ok:
                raw = pipe(ip_adapter_image_embeds=[id_embeds], **kw).images[0]
            else:
                raw = pipe(ip_adapter_image=butterfly, **kw).images[0]
            full_new = current.copy()
            full_new.paste(raw.resize((cw, ch), Image.LANCZOS), (cx0, cy0))
            current = paste_back(full_new, current, fmask)
            upload_img(cand, "06_face_refined", current)
        except Exception as e:  # noqa: BLE001
            status["candidates"][cand]["errors"].append(f"face_refine: {e!r}")
            log(f"face_refine FAILED for {cand}: {e!r}")
            traceback.print_exc()
        upload_img(cand, "99_final", current)
        status["candidates"][cand]["done"] = True

    status["done"] = True
    push_status("done")
    log("QUALITY STACK COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(f"FATAL: {e!r}")
        status["errors"].append(f"fatal: {e!r}")
        traceback.print_exc()
        status["done"] = True
        push_status("fatal")
