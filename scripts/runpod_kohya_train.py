#!/usr/bin/env python3
"""S24E/S24H — RunPod kohya SDXL LoRA training driver (Summer Adult LoRA v3).

Builds the in-pod bootstrap (install sd-scripts -> download RealVisXL -> fetch+extract
the kohya dataset -> write config -> train), launches an on-demand community GPU pod,
and reports progress through R2 (the same status channel the existing proof harness uses).

Triple safety (mirrors runpod_proof_lib): in-pod watchdog self-kill, in-pod completion
self-kill, and the sandbox poller (runpod_kohya_poll.py) spend/uptime cap.

S24H: launch uses the RunPod REST API (POST /v1/pods) with COMMUNITY cloud. The GraphQL
podFindAndDeployOnDemand mutation with SECURE cloud was broken at the platform level
(INTERNAL_SERVER_ERROR on all GPU types). All other harnesses in this repo use REST.

Modes:
  --mode preflight   no pod; local checks + compose only (free)
  --mode dry-run     launch a pod that installs/downloads/extracts/builds-config and runs
                     `sdxl_train_network.py --help`, then SELF-TERMINATES *before training*
  --mode train       full training run (1800 steps), uploads the .safetensors to R2

Run from backend/ (so the R2 + RUNPOD env is loaded) or anywhere the env is exported.
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
from runpod_kohya_upload import upload_pack  # noqa: E402

API = "https://api.runpod.io/graphql"
REST_API = "https://rest.runpod.io/v1/pods"  # S24H: REST replaces broken SECURE GraphQL
STATE = HERE / "runpod_kohya_state.json"

# RealVisXL V4.0 — SDXL photoreal base (~6.94 GB).
# S24R: the pod now pulls this from the authenticated R2 cache (BASE_MODEL_R2_KEY) via
# boto3 instead of the slow HF resolve that exhausted S24Q's wallclock inside download_base.
# The HF URL is kept ONLY as a fallback / manual diagnostic (see fetch_base in the body).
BASE_MODEL_URL = "https://huggingface.co/SG161222/RealVisXL_V4.0/resolve/main/RealVisXL_V4.0.safetensors"
BASE_MODEL_R2_KEY = "lora_training/base_models/RealVisXL_V4.0.safetensors"

IMAGE = "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04"
# Broadened 20GB+ COMMUNITY fallback pool (S24E.1). Tried sequentially until one has
# supply; the whole list is retried up to MAX_SUPPLY_CYCLES with backoff. Ordered by the
# S24E.1 spec (A5000 -> A4500 -> 4090 -> 3090 -> 6000 Ada -> 4000 Ada -> A40 -> A5000 PCIe).
GPU_CANDIDATES = [
    "NVIDIA RTX A5000",          # $0.16/hr (24GB)
    "NVIDIA RTX A4500",          # $0.19/hr (20GB — fine for SDXL LoRA)
    "NVIDIA GeForce RTX 4090",   # $0.34/hr (24GB)
    "NVIDIA GeForce RTX 3090",   # $0.22/hr (24GB)
    "NVIDIA RTX 6000 Ada Generation",  # (48GB)
    "NVIDIA RTX 4000 Ada Generation",  # (20GB)
    "NVIDIA A40",                # (48GB)
    "NVIDIA A5000",              # A5000 PCIe alias (24GB)
]
GPU = GPU_CANDIDATES[0]
RATE = 0.16                       # $/hr estimate (poller uses live costPerHr)
CONTAINER_DISK_GB = 40            # 6.94GB base + deps + dataset + output (proven size)

# Supply-aware backoff (S24E.1 TASK 4): retry the whole GPU list up to N cycles.
MAX_SUPPLY_CYCLES = 3
CYCLE_BACKOFF_S = [0, 20, 45]     # cycle 1 immediate, cycle 2 +20s, cycle 3 +45s

# Caps (dry-run is short; full train longer). Poller + watchdog both enforce.
# Dry-run absolute hard spend cap = $0.10.
CAPS = {
    "dry-run": {"watchdog_s": 3600, "wallclock_cap_s": 3600, "spend_cap": 0.10},
    "train":   {"watchdog_s": 9000, "wallclock_cap_s": 9000, "spend_cap": 1.00},  # S24P/S24Q: $1.00 hard cap; watchdog 9000s (poller is the real spend guard)
}


def _key():
    return os.environ["RUNPOD_API_KEY"]


def gql(query, variables=None):
    import requests

    r = requests.post(f"{API}?api_key={_key()}", json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(json.dumps(j["errors"])[:500])
    return j["data"]


# ── In-pod bootstrap (runs ON the GPU pod) ───────────────────────────────────
# Header injects the config + flags; the body does the work. Kept dependency-light
# for the dry-run: it proves sd-scripts imports via `--help` without training.
_TRAIN_BODY = r'''
import json, os, subprocess, sys, time, urllib.request, zipfile, glob, shutil

R2_PUB = os.environ["R2_PUBLIC_URL"].rstrip("/")
RUN_ID = os.environ["RUN_ID"]
BASE_URL = os.environ["BASE_MODEL_URL"]            # S24R: HF fallback / manual diagnostic only
BASE_R2_KEY = os.environ["BASE_MODEL_R2_KEY"]      # S24R: authenticated R2 cache (primary)
DATASET_URL = os.environ["DATASET_URL"]
SD = "/workspace/sd-scripts"
DATASET_DIR = "/workspace/dataset/img"
BASE_PATH = "/workspace/base/realvisxl.safetensors"

def _boto():
    import boto3
    return boto3.client("s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")

STATUS = {"run_id": RUN_ID, "dry_run": DRY_RUN, "stage": "boot", "done": False, "errors": []}
def put_status(stage=None, **kw):
    if stage: STATUS["stage"] = stage
    STATUS.update(kw); STATUS["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        _boto().put_object(Bucket=os.environ["R2_BUCKET_NAME"],
            Key=f"lora_training/{RUN_ID}/status.json",
            Body=json.dumps(STATUS, indent=2).encode(), ContentType="application/json")
    except Exception as e:
        print("status upload failed:", e, flush=True)
    print(f"[stage] {STATUS['stage']} {kw}", flush=True)

def _existing_status():
    """S24N: read the current status.json from R2 ({} if absent/unreadable). Used by the
    boot overwrite guard so a container restart cannot clobber a terminal (done) status."""
    try:
        obj = _boto().get_object(Bucket=os.environ["R2_BUCKET_NAME"],
                                 Key=f"lora_training/{RUN_ID}/status.json")
        return json.loads(obj["Body"].read())
    except Exception:
        return {}

def write_result(help_ok, help_tail=""):
    """S24N: durable, WRITE-ONCE dry-run verdict at lora_training/<RUN_ID>/result.json.
    The boot stage never writes this key, so the verdict survives a container restart that
    clobbers status.json (the S24M failure mode). First write wins; never overwritten."""
    B = os.environ["R2_BUCKET_NAME"]
    key = f"lora_training/{RUN_ID}/result.json"
    try:
        _boto().head_object(Bucket=B, Key=key)
        print("[result] result.json already exists; preserving write-once verdict", flush=True)
        return
    except Exception:
        pass
    rec = {"run_id": RUN_ID, "help_ok": bool(help_ok), "stage": "dry_run_verify",
           "done": True, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if help_tail:
        rec["help_tail"] = help_tail
    try:
        _boto().put_object(Bucket=B, Key=key,
                           Body=json.dumps(rec, indent=2).encode(), ContentType="application/json")
        print("[result] durable result.json written:", json.dumps(rec)[:200], flush=True)
    except Exception as e:
        print("[result] result.json write failed:", e, flush=True)

def sh(cmd, **kw):
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=True, **kw)

def fetch_base():
    """S24R: download the RealVisXL base checkpoint into BASE_PATH from the authenticated
    R2 cache (BASE_R2_KEY) via boto3. Falls back to the HF URL only if the R2 object is
    missing/unreadable. Returns (source, bytes, secs)."""
    os.makedirs(os.path.dirname(BASE_PATH), exist_ok=True)
    t0 = time.time()
    try:
        _boto().download_file(os.environ["R2_BUCKET_NAME"], BASE_R2_KEY, BASE_PATH)
        return "r2", os.path.getsize(BASE_PATH), round(time.time() - t0, 1)
    except Exception as e:
        print("[base] R2 fetch failed; falling back to HF resolve:", str(e)[:300], flush=True)
        sh(f"curl -L --fail --retry 3 -o {BASE_PATH} '{BASE_URL}'")
        return "hf_fallback", os.path.getsize(BASE_PATH), round(time.time() - t0, 1)

try:
    # S24N boot-guard: community-cloud containers can restart after self-terminate and
    # re-run this bootstrap. If a prior pass already finished (done=true), do NOT overwrite
    # the terminal status.json with a fresh "boot" (the S24M last-write-wins clobber).
    if _existing_status().get("done") is True:
        print("[boot-guard] prior status done=true; skipping boot write (no clobber)", flush=True)
    else:
        put_status("boot", note="pod booted")
    # 1) deps — install boto3 first (status channel), then sd-scripts deps. Do NOT
    #    reinstall torch (image already has torch 2.2 + cu121).
    sh("pip install -q --no-cache-dir boto3 >/dev/null 2>&1 || pip install -q boto3")
    put_status("install_clone", note="cloning sd-scripts")
    if not os.path.isdir(SD):
        sh(f"git clone --depth 1 https://github.com/kohya-ss/sd-scripts {SD}")
    put_status("install_python", note="installing sd-scripts requirements.txt (self-consistent set)")
    # S24O: stop manual version whack-a-mole — install kohya sd-scripts' OWN pinned,
    # self-consistent dependency set (diffusers/huggingface_hub/accelerate/transformers all
    # mutually compatible). torch stays from the base image (requirements.txt does not pin
    # torch). The trailing "." line installs the sd-scripts library, so run pip from {SD}.
    # S24Q: strip bitsandbytes in BOTH dry-run and train. In S24P's first real train the full
    # kohya requirements (incl. bitsandbytes' heavy CUDA wheel) consumed the entire watchdog
    # inside install_python. This first training run uses the standard AdamW optimizer, which
    # needs no bitsandbytes, so the proven fast dry-run dependency set is used for train too.
    sh(f"cd {SD} && grep -vi bitsandbytes requirements.txt > /workspace/reqs.txt && "
       f"pip install -q --no-cache-dir -r /workspace/reqs.txt 2>&1 | tail -3")
    if DRY_RUN:
        put_status("install_bitsandbytes_skipped", note="dry-run skips bitsandbytes")
    else:
        put_status("install_bitsandbytes_skipped",
                   note="first train skips bitsandbytes; using standard optimizer")
    put_status("install_complete", note="deps installed (bitsandbytes skipped)")

    # 2) dataset (always — small/fast; done before the heavy base download so the
    #    dry-run reaches "dataset extracted" + "config built" well under the cost cap)
    os.makedirs(DATASET_DIR, exist_ok=True)
    put_status("fetch_dataset", note="fetching dataset zip")
    _boto().download_file(os.environ["R2_BUCKET_NAME"],
                          f"lora_training/{RUN_ID}/summer_lora_v3_pack.zip",
                          "/workspace/pack.zip")
    with zipfile.ZipFile("/workspace/pack.zip") as z:
        z.extractall("/workspace/pack")
    # pack layout: images/<name>.png + images/<name>.txt -> flatten into DATASET_DIR
    n_png = 0
    for f in glob.glob("/workspace/pack/images/*"):
        shutil.copy(f, DATASET_DIR)
        if f.endswith(".png"): n_png += 1
    n_txt = len(glob.glob(f"{DATASET_DIR}/*.txt"))
    put_status("fetch_dataset", images=n_png, captions=n_txt, extracted=True)

    # 3) config (always)
    open("/workspace/dataset.toml", "w").write(DATASET_TOML)
    put_status("build_config", config_built=True, train_args=TRAIN_ARGS,
               dataset_toml_bytes=len(DATASET_TOML))

    os.makedirs("/workspace/base", exist_ok=True)
    if DRY_RUN:
        # 4) DRY-RUN (S24R): prove the base checkpoint is fetchable from the authenticated R2
        #    cache (BASE_R2_KEY) FROM THE POD — a TINY ranged GET (first 64 MiB via boto3
        #    get_object Range), not the full 6.94GB. This proves R2 auth + correct key +
        #    pod->R2 connectivity within the tight dry-run spend cap (the full pull belongs to
        #    the real train path). NO HF fallback here: if R2 fails the verdict must be
        #    unambiguous, not silently slow.
        PROBE = 64 << 20  # 64 MiB
        put_status("download_base", base_source="r2",
                   note=f"DRY-RUN: ranged R2 fetch (first {PROBE} bytes of {BASE_R2_KEY}) via boto3")
        t0 = time.time(); base_started = False; base_partial = 0; r2_err = None
        try:
            obj = _boto().get_object(Bucket=os.environ["R2_BUCKET_NAME"], Key=BASE_R2_KEY,
                                     Range=f"bytes=0-{PROBE - 1}")
            data = obj["Body"].read()
            base_partial = len(data)
            base_started = base_partial > 0
            with open(f"{BASE_PATH}.partial", "wb") as fh:
                fh.write(data)
        except Exception as e:
            r2_err = str(e)[:400]
        put_status("download_base", base_source="r2", base_download_started=base_started,
                   base_partial_bytes=base_partial, base_secs=round(time.time() - t0, 1),
                   base_r2_error=r2_err)
        # 5) prove sd-scripts + deps import without training
        r = subprocess.run(f"cd {SD} && python sdxl_train_network.py --help",
                           shell=True, capture_output=True, text=True)
        help_ok = (r.returncode == 0) and ("--network_dim" in (r.stdout + r.stderr))
        # S24N: persist the verdict to the durable write-once result.json BEFORE the
        # status.json writes, so it survives any post-completion container restart.
        write_result(help_ok, help_tail=(r.stderr or r.stdout)[-400:])
        put_status("dry_run_verify", help_ok=help_ok,
                   help_tail=(r.stderr or r.stdout)[-400:])
        put_status("done", done=True, dry_run=True,
                   summary={"base_source": "r2", "base_download_started": base_started,
                            "base_partial_bytes": base_partial, "base_r2_error": r2_err,
                            "config_built": True,
                            "images": n_png, "captions": n_txt, "dataset_extracted": True,
                            "sd_scripts_help_ok": help_ok})
    else:
        # TRAIN (S24R): pull the base checkpoint from the R2 cache via boto3 (HF fallback
        # inside fetch_base only if the R2 object is missing), then train.
        put_status("download_base", base_source="r2",
                   note=f"downloading RealVisXL V4.0 (~6.94GB) from R2 ({BASE_R2_KEY})")
        base_source, base_bytes, base_secs = fetch_base()
        put_status("download_base", base_source=base_source, base_bytes=base_bytes,
                   base_secs=base_secs)
        os.makedirs("/workspace/output", exist_ok=True)
        put_status("train", note="accelerate launch sdxl_train_network.py")
        cmd = ("cd %s && accelerate launch --num_processes=1 --mixed_precision=bf16 "
               "sdxl_train_network.py %s 2>&1 | tee /workspace/train.log") % (SD, " ".join(TRAIN_ARGS))
        rc = subprocess.run(cmd, shell=True).returncode
        outs = glob.glob("/workspace/output/*.safetensors")
        if rc == 0 and outs:
            cli = _boto(); B = os.environ["R2_BUCKET_NAME"]
            with open(outs[0], "rb") as fh:
                cli.put_object(Bucket=B, Key=f"lora_training/{RUN_ID}/out/summer_lora_v3.safetensors",
                               Body=fh.read(), ContentType="application/octet-stream")
            with open("/workspace/train.log", "rb") as fh:
                cli.put_object(Bucket=B, Key=f"lora_training/{RUN_ID}/out/train.log", Body=fh.read())
            put_status("done", done=True,
                       artifact=f"{R2_PUB}/lora_training/{RUN_ID}/out/summer_lora_v3.safetensors",
                       log=f"{R2_PUB}/lora_training/{RUN_ID}/out/train.log")
        else:
            put_status("done", done=True, errors=[f"train rc={rc} outputs={outs}"])
except Exception as e:
    import traceback; traceback.print_exc()
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


def _build_train_py(dry_run: bool) -> str:
    cfg = cfgmod.build_config()
    header = (
        f"DRY_RUN = {bool(dry_run)}\n"
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


def compose(mode: str, run_id: str, dataset_url: str):
    dry = mode == "dry-run"
    caps = CAPS["dry-run" if dry else "train"]
    train_py_b64 = base64.b64encode(_build_train_py(dry).encode()).decode()
    wrapper_b64 = base64.b64encode(_wrapper(caps["watchdog_s"], train_py_b64).encode()).decode()
    env = {
        "RUNPOD_API_KEY": _key(),
        "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
        "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
        "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
        "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
        "R2_PUBLIC_URL": os.environ["R2_PUBLIC_URL"],
        "RUN_ID": run_id,
        "BASE_MODEL_URL": BASE_MODEL_URL,
        "BASE_MODEL_R2_KEY": BASE_MODEL_R2_KEY,
        "DATASET_URL": dataset_url,
    }
    # Return wrapper_b64 directly; launch() constructs dockerStartCmd for the REST API.
    return env, wrapper_b64, caps


def launch(env: dict, wrapper_b64: str, *, cloud_type: str = "COMMUNITY",
           gpu_list: list | None = None, max_cycles: int = MAX_SUPPLY_CYCLES):
    """Find+deploy a pod via the RunPod REST API across the GPU fallback pool.

    S24H: uses POST https://rest.runpod.io/v1/pods (proven working in every other
    harness in this repo). Replaces the broken GraphQL podFindAndDeployOnDemand
    mutation which returned INTERNAL_SERVER_ERROR on all SECURE-cloud GPU types.

    Tries each GPU in order per cycle; on non-200/201 response logs and tries the next.
    On auth/hard errors (4xx) stops immediately. All attempts persisted to state.json."""
    import requests as req

    gpu_list = gpu_list if gpu_list is not None else GPU_CANDIDATES
    gpu_attempts: list[dict] = []
    last_status: int = 0
    last_body: str = ""

    for cycle in range(1, max_cycles + 1):
        backoff = CYCLE_BACKOFF_S[min(cycle - 1, len(CYCLE_BACKOFF_S) - 1)] if max_cycles > 1 else 0
        if backoff:
            print(f"[launch] supply backoff: sleeping {backoff}s before cycle {cycle}…")
            time.sleep(backoff)
        for gpu in gpu_list:
            attempt = {"gpu": gpu, "cycle": cycle,
                       "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            body = {
                "name": "kohya-lora",
                "imageName": IMAGE,
                "gpuCount": 1,
                "cloudType": cloud_type,
                "gpuTypeIds": [gpu],
                "containerDiskInGb": CONTAINER_DISK_GB,
                "volumeInGb": 0,
                "dockerStartCmd": ["bash", "-c", f"echo {wrapper_b64} | base64 -d | bash"],
                "env": env,
            }
            try:
                r = req.post(REST_API,
                             headers={"Authorization": f"Bearer {_key()}",
                                      "Content-Type": "application/json"},
                             json=body, timeout=90)
                last_status, last_body = r.status_code, r.text[:400]
                if r.status_code in (200, 201):
                    pod = r.json()
                    attempt["result"] = "secured"
                    gpu_attempts.append(attempt)
                    print(f"[launch] secured GPU: {gpu} (cycle {cycle}) "
                          f"pod={pod.get('id')} rate=${pod.get('costPerHr')}")
                    return pod, gpu_attempts, cycle
                # 4xx → hard error (auth/bad request); no point trying other GPUs.
                if 400 <= r.status_code < 500:
                    msg = f"REST {r.status_code}: {last_body}"
                    attempt.update(result="error", error_type="HTTPError", reason=msg)
                    gpu_attempts.append(attempt)
                    _persist_launch_failure(error_type="HTTPError", error_message=msg,
                                            gpu_attempts=gpu_attempts, supply_cycles=cycle)
                    raise RuntimeError(msg)
                # 5xx → capacity/supply/transient; try next GPU.
                attempt.update(result="supply_fail", error_type="HTTP5xx", reason=last_body)
                gpu_attempts.append(attempt)
                print(f"[launch] {gpu}: unavailable (HTTP {r.status_code}: "
                      f"{last_body[:80]}…), trying next…")
            except RuntimeError:
                raise
            except Exception as e:  # noqa: BLE001 — network error; treat as transient
                last_body = str(e)[:200]
                attempt.update(result="error", error_type=type(e).__name__, reason=last_body)
                gpu_attempts.append(attempt)
                _persist_launch_failure(error_type=type(e).__name__, error_message=last_body,
                                        gpu_attempts=gpu_attempts, supply_cycles=cycle)
                raise
        print(f"[launch] cycle {cycle}/{max_cycles} exhausted (all supply-constrained).")

    # All cycles exhausted.
    _persist_launch_failure(
        error_type="SupplyExhausted",
        error_message=(f"no GPU supply across {gpu_list} ({cloud_type}) "
                       f"after {max_cycles} cycle(s): HTTP {last_status} {last_body}"),
        gpu_attempts=gpu_attempts, supply_cycles=max_cycles)
    raise RuntimeError(
        f"no GPU supply across {gpu_list} ({cloud_type}) after {max_cycles} cycle(s): "
        f"HTTP {last_status} {last_body}")


def write_state(**kw):
    st = {}
    if STATE.exists():
        st = json.loads(STATE.read_text())
    st.update(kw)
    st["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE.write_text(json.dumps(st, indent=2))
    return st


def _persist_launch_failure(*, error_type, error_message, gpu_attempts, supply_cycles, phase="launch"):
    """Persist a complete failure record to runpod_kohya_state.json. Called BEFORE any
    raise so no launch failure is ever silent (S24E.1 TASK 2). Never raises itself."""
    try:
        write_state(state="failed", phase=phase, error_type=error_type,
                    error_message=error_message, gpu_attempts=gpu_attempts,
                    supply_cycles=supply_cycles,
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        print(f"[fail] persisted failure to {STATE.name}: {error_type} "
              f"(cycles={supply_cycles}, attempts={len(gpu_attempts)})")
    except Exception as e:  # noqa: BLE001 — last-resort, must not mask the original error
        print(f"[fail] could not persist failure state: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["preflight", "dry-run", "train"], default="dry-run")
    ap.add_argument("--run-id", default=f"s24e_{int(time.time())}")
    ap.add_argument("--no-launch", action="store_true", help="compose only; do not create a pod")
    args = ap.parse_args()

    cfg = cfgmod.build_config()
    print(f"[config] base={cfg['base_model']} rank={cfg['params']['network_dim']} "
          f"alpha={cfg['params']['network_alpha']} steps={cfg['params']['max_train_steps']} "
          f"res={cfg['params']['resolution']} buckets={cfg['params']['enable_bucket']}")

    if args.mode == "preflight":
        bal = gql("query { myself { clientBalance } }")["myself"]["clientBalance"]
        print(f"[preflight] RunPod balance ${bal:.2f}, GPU {GPU} @ ${RATE}/hr, base {BASE_MODEL_URL}")
        print("[preflight] config builds OK; pack upload + pod launch NOT performed.")
        return 0

    # Upload dataset (real, cheap) then compose + (optionally) launch. The whole pre-launch
    # path is wrapped so upload/compose/HTTP errors persist a failure record too (TASK 2).
    try:
        print(f"[upload] pushing pack to R2 for run {args.run_id} …")
        dataset_url = upload_pack(run_id=args.run_id)
        print(f"[upload] dataset_url = {dataset_url}")
        env, wrapper_b64, caps = compose(args.mode, args.run_id, dataset_url)
    except Exception as e:  # noqa: BLE001
        _persist_launch_failure(phase="prepare", error_type=type(e).__name__,
                                error_message=str(e)[:500], gpu_attempts=[], supply_cycles=0)
        raise

    write_state(run_id=args.run_id, mode=args.mode, dataset_url=dataset_url, caps=caps,
                state="composed", phase="prepare",
                r2_status_url=f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/lora_training/{args.run_id}/status.json")

    if args.no_launch:
        print("[compose] payload + env composed; --no-launch set, no pod created.")
        return 0

    # S24H: all modes use COMMUNITY cloud via REST API.
    cloud_type, max_cycles, gpu_list = "COMMUNITY", MAX_SUPPLY_CYCLES, GPU_CANDIDATES
    write_state(cloud_type=cloud_type)

    print(f"[launch] creating pod (mode={args.mode}, cloud={cloud_type}, watchdog={caps['watchdog_s']}s, "
          f"spend_cap=${caps['spend_cap']}) across {len(gpu_list)} GPU type(s) …")
    pod, gpu_attempts, used_cycles = launch(env, wrapper_b64, cloud_type=cloud_type,
                                            gpu_list=gpu_list, max_cycles=max_cycles)
    secured_gpu = next((a["gpu"] for a in reversed(gpu_attempts)
                        if a.get("result") == "secured"), None)
    write_state(state="launched", phase="boot", pod_id=pod["id"], cloud_type=cloud_type,
                cost_per_hr=pod.get("costPerHr"), gpu_type=secured_gpu,
                gpu_attempts=gpu_attempts, supply_cycles=used_cycles)
    print(f"[launch] pod={pod['id']} gpu={secured_gpu} costPerHr=${pod.get('costPerHr')} "
          f"machine={pod.get('machineId')}")
    print(f"[launch] poll with:  python {HERE/'runpod_kohya_poll.py'} --watch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
