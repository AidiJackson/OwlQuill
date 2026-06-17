#!/usr/bin/env python3
"""S24AC — Summer LoRA v5 validation image generator (RunPod, diffusers SDXL).

Mirrors the proven S24AA/S24T validation harness verbatim, swapped to the v5 artifact:

  base   : RealVisXL_V4.0.safetensors   (R2 cache)
  lora   : summer_lora_v5.safetensors    (R2, lora_training/s24ac_v5_…/out/…)
  trigger: smmr_v5                        (S24AC retokened trigger)
  weight : lora_scale 0.85
  engine : diffusers StableDiffusionXLPipeline.from_single_file + load_lora_weights

Generates EXACTLY the same 6 S24AA validation prompts, retokened smmr_v4 -> smmr_v5.
NOT wired into the app and NOT scored — a throwaway validation harness. Reuses the
kohya launch/wrapper/GPU-fallback + spend-cap safety. Writes status to R2 and progress
to runpod_s24ac_val_state.json. Poll with:
  python runpod_s24t_poll.py --state runpod_s24ac_val_state.json --watch
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from runpod_kohya_train import (  # noqa: E402
    GPU_CANDIDATES, MAX_SUPPLY_CYCLES, _key, launch,
)

STATE = HERE / "runpod_s24ac_val_state.json"

BASE_MODEL_R2_KEY = "lora_training/base_models/RealVisXL_V4.0.safetensors"
# v5 artifact produced by s24ac_train_driver.py (S24AC training run).
LORA_R2_KEY = "lora_training/s24ac_v5_1781720367/out/summer_lora_v5.safetensors"

SETTINGS = {
    "base_model": "RealVisXL_V4.0",
    "lora": "summer_lora_v5.safetensors",
    "trigger": "smmr_v5",
    "scheduler": "DPMSolverMultistepScheduler (Karras, sde-dpmsolver++)",
    "steps": 30,
    "guidance_scale": 5.0,
    "lora_scale": 0.85,
    "width": 1024,
    "height": 1024,
    "base_seed": 1234,
    "dtype": "float16",
}

NEGATIVE = ("deformed, disfigured, extra limbs, extra fingers, missing fingers, "
            "bad anatomy, bad hands, blurry, lowres, watermark, text, signature, "
            "multiple people, cropped, jpeg artifacts")

# (label, prompt) — the 6 S24AA validation prompts, trigger smmr_v5 (retokened).
PROMPTS = [
    ("01_studio_white_tank",
     "smmr_v5 woman standing naturally in a softly lit studio, white tank top and denim shorts"),
    ("02_black_sleeveless_tattoos",
     "smmr_v5 woman in a black sleeveless top, tattoos visible"),
    ("03_close_portrait",
     "close portrait of smmr_v5 woman, soft smile, warm lighting"),
    ("04_beach_sunset_bikini",
     "smmr_v5 woman standing on a beach at sunset in a white bikini"),
    ("05_black_evening_dress",
     "smmr_v5 woman wearing an elegant black evening dress in a luxury ballroom"),
    ("06_bed_oversized_shirt",
     "smmr_v5 woman lying in bed wearing an oversized shirt, morning light"),
]

CAPS = {"watchdog_s": 2400, "wallclock_cap_s": 2400, "spend_cap": 0.50}


_GEN_BODY = r'''
import json, os, time, glob, subprocess, traceback

R2_PUB = os.environ["R2_PUBLIC_URL"].rstrip("/")
RUN_ID = os.environ["RUN_ID"]
B = os.environ["R2_BUCKET_NAME"]
BASE_R2_KEY = os.environ["BASE_MODEL_R2_KEY"]
LORA_R2_KEY = os.environ["LORA_R2_KEY"]
BASE_PATH = "/workspace/base/realvisxl.safetensors"
LORA_PATH = "/workspace/lora/summer_lora_v5.safetensors"
OUT_DIR = "/workspace/out"

def _boto():
    import boto3
    return boto3.client("s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")

STATUS = {"run_id": RUN_ID, "stage": "boot", "done": False, "errors": [],
          "settings": SETTINGS, "images": []}
def put_status(stage=None, **kw):
    if stage: STATUS["stage"] = stage
    STATUS.update(kw); STATUS["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        _boto().put_object(Bucket=B, Key=f"lora_training/{RUN_ID}/status.json",
            Body=json.dumps(STATUS, indent=2).encode(), ContentType="application/json")
    except Exception as e:
        print("status upload failed:", e, flush=True)
    print(f"[stage] {STATUS['stage']} { {k:v for k,v in kw.items() if k!='images'} }", flush=True)

try:
    put_status("install")
    subprocess.run(
        "pip install -q --no-cache-dir diffusers==0.27.2 transformers==4.39.3 "
        "accelerate==0.29.3 huggingface_hub==0.22.2 peft==0.10.0 safetensors omegaconf boto3",
        shell=True, check=True)
    put_status("install_complete")

    put_status("verify_imports")
    import torch
    import diffusers, transformers, huggingface_hub, peft
    from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler
    put_status("verify_imports", torch=torch.__version__, diffusers=diffusers.__version__,
               transformers=transformers.__version__, huggingface_hub=huggingface_hub.__version__,
               peft=peft.__version__)

    cli = _boto()
    os.makedirs(os.path.dirname(BASE_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(LORA_PATH), exist_ok=True)
    put_status("fetch_base", note=f"R2 {BASE_R2_KEY}")
    t0 = time.time(); cli.download_file(B, BASE_R2_KEY, BASE_PATH)
    put_status("fetch_base", base_bytes=os.path.getsize(BASE_PATH), base_secs=round(time.time()-t0,1))
    put_status("fetch_lora", note=f"R2 {LORA_R2_KEY}")
    cli.download_file(B, LORA_R2_KEY, LORA_PATH)
    put_status("fetch_lora", lora_bytes=os.path.getsize(LORA_PATH))

    put_status("load_pipeline")
    pipe = StableDiffusionXLPipeline.from_single_file(
        BASE_PATH, torch_dtype=torch.float16, use_safetensors=True)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True, algorithm_type="sde-dpmsolver++")
    pipe.to("cuda")
    pipe.enable_vae_tiling()
    pipe.load_lora_weights(LORA_PATH)
    put_status("generate", n=len(PROMPTS))

    os.makedirs(OUT_DIR, exist_ok=True)
    results = []
    for i, item in enumerate(PROMPTS):
        label, prompt = item[0], item[1]
        gen = torch.Generator("cuda").manual_seed(SETTINGS["base_seed"] + i)
        img = pipe(prompt=prompt, negative_prompt=NEGATIVE,
                   num_inference_steps=SETTINGS["steps"],
                   guidance_scale=SETTINGS["guidance_scale"],
                   width=SETTINGS["width"], height=SETTINGS["height"],
                   generator=gen,
                   cross_attention_kwargs={"scale": SETTINGS["lora_scale"]}).images[0]
        fn = f"{label}.png"
        local = os.path.join(OUT_DIR, fn); img.save(local)
        key = f"lora_training/{RUN_ID}/val/{fn}"
        with open(local, "rb") as fh:
            cli.put_object(Bucket=B, Key=key, Body=fh.read(), ContentType="image/png")
        rec = {"index": i+1, "label": label, "prompt": prompt,
               "seed": SETTINGS["base_seed"]+i, "key": key, "url": f"{R2_PUB}/{key}",
               "bytes": os.path.getsize(local)}
        results.append(rec)
        STATUS["images"] = results
        put_status("generate", done_count=i+1, last=rec["url"])

    put_status("done", done=True, images=results, generated=len(results))
except Exception as e:
    traceback.print_exc()
    put_status("error", done=True, errors=[str(e)[:600]])

try:
    import urllib.request as u
    pid = os.environ.get("RUNPOD_POD_ID", "")
    body = json.dumps({"query": "mutation { podTerminate(input:{podId:\"%s\"}) }" % pid}).encode()
    req = u.Request(f"https://api.runpod.io/graphql?api_key={os.environ['RUNPOD_API_KEY']}",
                    data=body, headers={"Content-Type": "application/json"})
    u.urlopen(req, timeout=30).read()
except Exception as e:
    print("self-terminate failed:", e, flush=True)
'''


def _wrapper(watchdog_s: int, gen_py_b64: str) -> str:
    return (
        "#!/bin/bash\n"
        "selfkill(){ curl -s \"https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY\" "
        "-H 'Content-Type: application/json' "
        "-d \"{\\\"query\\\":\\\"mutation { podTerminate(input:{podId:\\\\\\\"$RUNPOD_POD_ID\\\\\\\"}) }\\\"}\" >/dev/null 2>&1; }\n"
        f"( sleep {watchdog_s}; echo WATCHDOG_FIRED; selfkill ) &\n"
        "mkdir -p /workspace\n"
        f"echo {gen_py_b64} | base64 -d > /workspace/gen.py\n"
        "echo '[wrapper] starting gen.py' $(date)\n"
        "python /workspace/gen.py\n"
        "echo MAIN_DONE rc=$?\n"
        "selfkill\n"
    )


def _build_gen_py() -> str:
    header = (
        f"SETTINGS = {json.dumps(SETTINGS)}\n"
        f"NEGATIVE = {json.dumps(NEGATIVE)}\n"
        f"PROMPTS = {json.dumps(PROMPTS)}\n"
    )
    return header + _GEN_BODY


def write_state(**kw):
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    st.update(kw)
    st["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE.write_text(json.dumps(st, indent=2))
    return st


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=f"s24ac_summer_lora_v5_validation_{int(time.time())}")
    ap.add_argument("--no-launch", action="store_true")
    args = ap.parse_args()

    gen_py_b64 = base64.b64encode(_build_gen_py().encode()).decode()
    wrapper_b64 = base64.b64encode(_wrapper(CAPS["watchdog_s"], gen_py_b64).encode()).decode()
    env = {
        "RUNPOD_API_KEY": _key(),
        "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
        "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
        "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
        "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
        "R2_PUBLIC_URL": os.environ["R2_PUBLIC_URL"],
        "RUN_ID": args.run_id,
        "BASE_MODEL_R2_KEY": BASE_MODEL_R2_KEY,
        "LORA_R2_KEY": LORA_R2_KEY,
    }

    write_state(run_id=args.run_id, caps=CAPS, state="composed", phase="prepare",
                settings=SETTINGS, lora_r2_key=LORA_R2_KEY,
                r2_status_url=f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}"
                              f"/lora_training/{args.run_id}/status.json")
    print(f"[config] base=RealVisXL_V4.0 lora=summer_lora_v5 trigger=smmr_v5 "
          f"prompts={len(PROMPTS)} steps={SETTINGS['steps']} cfg={SETTINGS['guidance_scale']} "
          f"lora_scale={SETTINGS['lora_scale']}")

    if args.no_launch:
        print("[compose] composed; --no-launch set, no pod created.")
        return 0

    print(f"[launch] creating pod (watchdog={CAPS['watchdog_s']}s, "
          f"spend_cap=${CAPS['spend_cap']}) across {len(GPU_CANDIDATES)} GPU type(s) …")
    pod, gpu_attempts, used_cycles = launch(env, wrapper_b64, cloud_type="COMMUNITY",
                                            gpu_list=GPU_CANDIDATES, max_cycles=MAX_SUPPLY_CYCLES)
    secured_gpu = next((a["gpu"] for a in reversed(gpu_attempts)
                        if a.get("result") == "secured"), None)
    write_state(state="launched", phase="boot", pod_id=pod["id"], cloud_type="COMMUNITY",
                cost_per_hr=pod.get("costPerHr"), gpu_type=secured_gpu,
                gpu_attempts=gpu_attempts, supply_cycles=used_cycles)
    print(f"[launch] pod={pod['id']} gpu={secured_gpu} costPerHr=${pod.get('costPerHr')}")
    print(f"[launch] poll with:  python {HERE/'runpod_s24t_poll.py'} "
          f"--state {STATE.name} --watch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
