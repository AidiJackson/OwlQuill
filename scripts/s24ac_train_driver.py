#!/usr/bin/env python3
"""S24AC — FINAL Summer Adult LoRA v5 training run (RunPod kohya SDXL).

Final controlled retrain using the APPROVED v4 pack but lower-capacity v3-style
settings (rank 16 / alpha 16 / 1800 steps / warmup 100). One training run only.

Reuses the proven S24E/S24Y kohya launch primitives (REST community-cloud launch,
triple spend-cap safety: in-pod watchdog self-kill + completion self-kill + sandbox
poller). The in-pod body is a v5 variant of runpod_kohya_train._TRAIN_BODY:

  base    : RealVisXL_V4.0  (R2 cache, lora_training/base_models/…)         [unchanged]
  pack    : summer_lora_v4_approved_pack.zip  (uploaded as-is, NOT modified) [unchanged]
  RETOKEN : in-pod ONLY — rewrite smmr_v4 -> smmr_v5 in the *copied* caption
            .txt files and set class_tokens=smmr_v5. The source pack on disk and
            in R2 is never modified (S24AC option 1).
  trigger : smmr_v5
  output  : summer_lora_v5.safetensors  -> lora_training/<RUN_ID>/out/

Config (S24AC spec): rank 16, alpha 16, steps 1800, resolution 1024, buckets on,
optimizer AdamW, cosine scheduler, warmup 100, unet_only, bf16, NO bitsandbytes.

Spend cap: hard $1.00 (poller + watchdog). v4 (2600 steps) cost ~$0.20 on an A4500,
so v5 (1800 steps) is expected ~$0.13. Writes progress to runpod_s24ac_state.json:
  poll with:  python runpod_s24t_poll.py --state runpod_s24ac_state.json --watch
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
import runpod_kohya_config as cfgmod  # noqa: E402
from runpod_kohya_train import (  # noqa: E402
    BASE_MODEL_R2_KEY, BASE_MODEL_URL, GPU_CANDIDATES, MAX_SUPPLY_CYCLES,
    _key, launch,
)
from runpod_kohya_upload import upload_pack  # noqa: E402

STATE = HERE / "runpod_s24ac_state.json"

# ── S24AC v5 config: lower-capacity v3-style overrides on the proven builder ──
TRIGGER_V5 = "smmr_v5"
TRIGGER_V4 = "smmr_v4"
OUTPUT_NAME_V5 = "summer_lora_v5"
V5_PARAMS = {
    "network_dim": 16,        # rank 16 (v3-style; v4 was 32)
    "network_alpha": 16,      # alpha 16
    "max_train_steps": 1800,  # v3-style (v4 was 2600)
    "lr_warmup_steps": 100,   # v3-style (v4 was 150)
    # inherited from DEFAULTS: resolution 1024,1024; enable_bucket True; AdamW;
    # cosine; bf16; gradient_checkpointing; sdpa; cache_latents; lr 1e-4;
    # num_repeats 10; train_batch_size 2; --network_train_unet_only (always added).
}

# Hard caps (S24AC): $1.00 spend cap; watchdog/wallclock 9000s. Poller is the real guard.
CAPS = {"watchdog_s": 9000, "wallclock_cap_s": 9000, "spend_cap": 1.00}

IMAGE = "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04"


def build_v5_config() -> dict:
    """v5 train_args + dataset.toml. class_tokens forced to smmr_v5 by temporarily
    pointing cfgmod.TRIGGER_TOKEN at smmr_v5 (one-shot script; safe)."""
    cfgmod.TRIGGER_TOKEN = TRIGGER_V5
    dataset_toml = cfgmod.build_dataset_toml(params=V5_PARAMS)
    train_args = cfgmod.build_train_args(params=V5_PARAMS, output_name=OUTPUT_NAME_V5)
    p = {**cfgmod.DEFAULTS, **V5_PARAMS}
    return {"dataset_toml": dataset_toml, "train_args": train_args, "params": p}


# ── In-pod training body (runs ON the GPU pod) ───────────────────────────────
# v5 variant of runpod_kohya_train._TRAIN_BODY: adds the smmr_v4->smmr_v5 caption
# retoken step, uploads summer_lora_v5.safetensors. NO dry-run path (train only).
_TRAIN_BODY = r'''
import json, os, subprocess, time, zipfile, glob, shutil, traceback

R2_PUB = os.environ["R2_PUBLIC_URL"].rstrip("/")
RUN_ID = os.environ["RUN_ID"]
B = os.environ["R2_BUCKET_NAME"]
BASE_R2_KEY = os.environ["BASE_MODEL_R2_KEY"]
BASE_URL = os.environ["BASE_MODEL_URL"]            # HF fallback / manual diagnostic only
SD = "/workspace/sd-scripts"
DATASET_DIR = "/workspace/dataset/img"
BASE_PATH = "/workspace/base/realvisxl.safetensors"
OUT_KEY = f"lora_training/{RUN_ID}/out/summer_lora_v5.safetensors"

def _boto():
    import boto3
    return boto3.client("s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")

STATUS = {"run_id": RUN_ID, "sprint": "S24AC", "stage": "boot", "done": False, "errors": []}
def put_status(stage=None, **kw):
    if stage: STATUS["stage"] = stage
    STATUS.update(kw); STATUS["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        _boto().put_object(Bucket=B, Key=f"lora_training/{RUN_ID}/status.json",
            Body=json.dumps(STATUS, indent=2).encode(), ContentType="application/json")
    except Exception as e:
        print("status upload failed:", e, flush=True)
    print(f"[stage] {STATUS['stage']} {kw}", flush=True)

def _existing_status():
    try:
        obj = _boto().get_object(Bucket=B, Key=f"lora_training/{RUN_ID}/status.json")
        return json.loads(obj["Body"].read())
    except Exception:
        return {}

def sh(cmd, **kw):
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=True, **kw)

def fetch_base():
    os.makedirs(os.path.dirname(BASE_PATH), exist_ok=True)
    t0 = time.time()
    try:
        _boto().download_file(B, BASE_R2_KEY, BASE_PATH)
        return "r2", os.path.getsize(BASE_PATH), round(time.time() - t0, 1)
    except Exception as e:
        print("[base] R2 fetch failed; HF fallback:", str(e)[:300], flush=True)
        sh(f"curl -L --fail --retry 3 -o {BASE_PATH} '{BASE_URL}'")
        return "hf_fallback", os.path.getsize(BASE_PATH), round(time.time() - t0, 1)

try:
    # boot-guard: a community container can restart after self-terminate; never clobber
    # a terminal (done) status with a fresh boot write.
    if _existing_status().get("done") is True:
        print("[boot-guard] prior status done=true; skipping boot write", flush=True)
    else:
        put_status("boot", note="pod booted")

    # 1) deps — boto3 first, then kohya's OWN self-consistent set with bitsandbytes stripped
    #    (AdamW needs none; torch stays from the base image).
    sh("pip install -q --no-cache-dir boto3 >/dev/null 2>&1 || pip install -q boto3")
    put_status("install_clone", note="cloning sd-scripts")
    if not os.path.isdir(SD):
        sh(f"git clone --depth 1 https://github.com/kohya-ss/sd-scripts {SD}")
    put_status("install_python", note="installing sd-scripts requirements (bitsandbytes stripped)")
    sh(f"cd {SD} && grep -vi bitsandbytes requirements.txt > /workspace/reqs.txt && "
       f"pip install -q --no-cache-dir -r /workspace/reqs.txt 2>&1 | tail -3")
    put_status("install_complete", note="deps installed (no bitsandbytes)")

    # 2) dataset — fetch the APPROVED v4 pack zip (unmodified) and flatten png+txt.
    os.makedirs(DATASET_DIR, exist_ok=True)
    put_status("fetch_dataset", note="fetching approved v4 pack zip")
    _boto().download_file(B, f"lora_training/{RUN_ID}/summer_lora_v4_approved_pack.zip",
                          "/workspace/pack.zip")
    with zipfile.ZipFile("/workspace/pack.zip") as z:
        z.extractall("/workspace/pack")
    n_png = 0
    for f in glob.glob("/workspace/pack/images/*"):
        shutil.copy(f, DATASET_DIR)
        if f.endswith(".png"): n_png += 1
    for f in glob.glob("/workspace/pack/captions/*.txt"):
        shutil.copy(f, DATASET_DIR)
    # back-compat: a v3-style pack with .txt inside images/ also works
    n_txt = len(glob.glob(f"{DATASET_DIR}/*.txt"))
    put_status("fetch_dataset", images=n_png, captions=n_txt, extracted=True)

    # 2b) RETOKEN (S24AC option 1): rewrite smmr_v4 -> smmr_v5 in the COPIED captions
    #     only. The source pack zip in R2 is never modified.
    retoken_hits = 0
    for txt in glob.glob(f"{DATASET_DIR}/*.txt"):
        s = open(txt, "r", encoding="utf-8").read()
        if "smmr_v4" in s:
            open(txt, "w", encoding="utf-8").write(s.replace("smmr_v4", "smmr_v5"))
            retoken_hits += 1
    sample = ""
    _txts = sorted(glob.glob(f"{DATASET_DIR}/*.txt"))
    if _txts:
        sample = open(_txts[0], encoding="utf-8").read()[:160]
    leftover_v4 = sum(1 for t in _txts if "smmr_v4" in open(t, encoding="utf-8").read())
    put_status("retoken", retokened_files=retoken_hits, leftover_smmr_v4=leftover_v4,
               trigger="smmr_v5", sample_caption=sample)
    if leftover_v4:
        raise RuntimeError(f"retoken incomplete: {leftover_v4} captions still contain smmr_v4")

    # 3) config (class_tokens=smmr_v5 baked into DATASET_TOML by the driver)
    open("/workspace/dataset.toml", "w").write(DATASET_TOML)
    put_status("build_config", config_built=True, train_args=TRAIN_ARGS,
               dataset_toml=DATASET_TOML)

    # 4) base checkpoint from the R2 cache (HF fallback inside fetch_base)
    os.makedirs("/workspace/base", exist_ok=True)
    put_status("download_base", base_source="r2",
               note=f"downloading RealVisXL V4.0 (~6.94GB) from R2 ({BASE_R2_KEY})")
    base_source, base_bytes, base_secs = fetch_base()
    put_status("download_base", base_source=base_source, base_bytes=base_bytes, base_secs=base_secs)

    # 5) train
    os.makedirs("/workspace/output", exist_ok=True)
    put_status("train", note="accelerate launch sdxl_train_network.py")
    cmd = ("cd %s && accelerate launch --num_processes=1 --mixed_precision=bf16 "
           "sdxl_train_network.py %s 2>&1 | tee /workspace/train.log") % (SD, " ".join(TRAIN_ARGS))
    rc = subprocess.run(cmd, shell=True).returncode
    outs = glob.glob("/workspace/output/*.safetensors")

    # 5b) parse final/avg loss from the kohya log (best-effort)
    loss = {}
    try:
        import re
        log = open("/workspace/train.log", encoding="utf-8", errors="ignore").read()
        avgs = re.findall(r"average loss[^\d]*([0-9.]+)", log)
        steps = re.findall(r"loss=([0-9.]+)", log)
        if avgs: loss["average_loss"] = float(avgs[-1])
        if steps: loss["last_step_loss"] = float(steps[-1])
        loss["loss_samples"] = len(steps)
    except Exception as e:
        loss["parse_error"] = str(e)[:200]

    if rc == 0 and outs:
        cli = _boto()
        with open(outs[0], "rb") as fh:
            cli.put_object(Bucket=B, Key=OUT_KEY, Body=fh.read(),
                           ContentType="application/octet-stream")
        with open("/workspace/train.log", "rb") as fh:
            cli.put_object(Bucket=B, Key=f"lora_training/{RUN_ID}/out/train.log", Body=fh.read())
        put_status("done", done=True,
                   artifact=f"{R2_PUB}/{OUT_KEY}", artifact_key=OUT_KEY,
                   artifact_bytes=os.path.getsize(outs[0]),
                   log=f"{R2_PUB}/lora_training/{RUN_ID}/out/train.log",
                   loss=loss, train_rc=rc)
    else:
        put_status("done", done=True, errors=[f"train rc={rc} outputs={outs}"], loss=loss)
except Exception as e:
    traceback.print_exc()
    put_status("error", done=True, errors=[str(e)[:500]])

# self-terminate (completion backstop; wrapper watchdog is the hard backstop)
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


def _build_train_py() -> str:
    cfg = build_v5_config()
    header = (
        f"DATASET_TOML = {json.dumps(cfg['dataset_toml'])}\n"
        f"TRAIN_ARGS = {json.dumps(cfg['train_args'])}\n"
    )
    return header + _TRAIN_BODY


def _wrapper(watchdog_s: int, train_py_b64: str) -> str:
    return (
        "#!/bin/bash\n"
        "selfkill(){ curl -s \"https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY\" "
        "-H 'Content-Type: application/json' "
        "-d \"{\\\"query\\\":\\\"mutation { podTerminate(input:{podId:\\\\\\\"$RUNPOD_POD_ID\\\\\\\"}) }\\\"}\" >/dev/null 2>&1; }\n"
        f"( sleep {watchdog_s}; echo WATCHDOG_FIRED; selfkill ) &\n"
        "mkdir -p /workspace\n"
        f"echo {train_py_b64} | base64 -d > /workspace/train.py\n"
        "echo '[wrapper] starting train.py' $(date)\n"
        "python /workspace/train.py\n"
        "echo MAIN_DONE rc=$?\n"
        "selfkill\n"
    )


def write_state(**kw):
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    st.update(kw)
    st["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE.write_text(json.dumps(st, indent=2))
    return st


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=f"s24ac_v5_{int(time.time())}")
    ap.add_argument("--no-launch", action="store_true", help="compose only; no pod")
    args = ap.parse_args()

    cfg = build_v5_config()
    p = cfg["params"]
    print(f"[config] base=RealVisXL_V4.0 trigger={TRIGGER_V5} output={OUTPUT_NAME_V5} "
          f"rank={p['network_dim']} alpha={p['network_alpha']} steps={p['max_train_steps']} "
          f"warmup={p['lr_warmup_steps']} res={p['resolution']} buckets={p['enable_bucket']} "
          f"opt={p['optimizer_type']} sched={p['lr_scheduler']} unet_only=True bf16")
    print("[config] dataset.toml:\n" + cfg["dataset_toml"])
    assert "class_tokens = \"smmr_v5\"" in cfg["dataset_toml"], "class_tokens not smmr_v5"
    assert "--network_train_unet_only" in cfg["train_args"], "unet_only missing"
    assert "--network_dim=16" in cfg["train_args"] and "--network_alpha=16" in cfg["train_args"]
    assert "--max_train_steps=1800" in cfg["train_args"]
    assert "--optimizer_type=AdamW" in cfg["train_args"]
    assert "--output_name=summer_lora_v5" in cfg["train_args"]

    # upload the approved pack zip AS-IS (same key the in-pod body fetches)
    print(f"[upload] pushing approved v4 pack to R2 for run {args.run_id} …")
    dataset_url = upload_pack(run_id=args.run_id)
    print(f"[upload] dataset_url = {dataset_url}")

    train_py_b64 = base64.b64encode(_build_train_py().encode()).decode()
    wrapper_b64 = base64.b64encode(_wrapper(CAPS["watchdog_s"], train_py_b64).encode()).decode()
    env = {
        "RUNPOD_API_KEY": _key(),
        "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
        "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
        "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
        "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
        "R2_PUBLIC_URL": os.environ["R2_PUBLIC_URL"],
        "RUN_ID": args.run_id,
        "BASE_MODEL_URL": BASE_MODEL_URL,
        "BASE_MODEL_R2_KEY": BASE_MODEL_R2_KEY,
    }

    write_state(run_id=args.run_id, sprint="S24AC", mode="train", caps=CAPS,
                state="composed", phase="prepare", dataset_url=dataset_url,
                config={"trigger": TRIGGER_V5, "output_name": OUTPUT_NAME_V5,
                        "rank": p["network_dim"], "alpha": p["network_alpha"],
                        "steps": p["max_train_steps"], "warmup": p["lr_warmup_steps"]},
                artifact_key=f"lora_training/{args.run_id}/out/summer_lora_v5.safetensors",
                r2_status_url=f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}"
                              f"/lora_training/{args.run_id}/status.json")

    if args.no_launch:
        print("[compose] composed; --no-launch set, no pod created.")
        return 0

    print(f"[launch] creating pod (watchdog={CAPS['watchdog_s']}s, spend_cap=${CAPS['spend_cap']}) "
          f"across {len(GPU_CANDIDATES)} GPU type(s) …")
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
