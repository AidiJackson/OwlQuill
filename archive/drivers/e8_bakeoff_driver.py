#!/usr/bin/env python3
"""Sprint E8 — IMG2IMG PROVIDER BAKE-OFF driver (throwaway, founder-only).

Ships e8_bakeoff_pod.py: FULL img2img regeneration (no masks) of Summer's
black-dress canonical image (CharacterImage 1778) on RealVisXL V4.0 and
Juggernaut XL v9, 2 prompts each, Summer LoRA loaded on both.

Safety (E3 harness, cap raised to the E8 sprint's $0.10 budget):
  SPEND_CAP=0.10, TERMINATE_AT=0.09, 1350s in-pod watchdog (max $0.0825 @
  $0.22/hr), 1350s driver wallclock, launch-time RATE GUARD, finally-
  terminate, orphan verify. Reports to scripts/e8_reports/.

No UI, no production routes, no Canon/Adult Studio writes, no training.
"""
import base64
import json
import os
import sys
import time
import traceback

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

GQL = "https://api.runpod.io/graphql"
REST = "https://rest.runpod.io/v1/pods"
SUMMER = 60
SOURCE_IMAGE_ID = int(os.environ.get("E8_SOURCE_IMAGE_ID", "1778"))

GPU_CANDIDATES = ["NVIDIA RTX A5000", "NVIDIA RTX A4500", "NVIDIA GeForce RTX 3090"]
SPEND_CAP = 0.10           # E8 sprint hard cap
TERMINATE_AT = 0.09        # external kill threshold (margin below the cap)
WATCHDOG_S = 1350          # 2 SDXL downloads + 4 generations; $0.0825 @ $0.22/hr
DRIVER_WALLCLOCK_S = 1350
POLL_S = 15
MAX_SAFE_RATE = round(SPEND_CAP / (WATCHDOG_S / 3600.0) * 0.95, 4)

REPORTS_DIR = os.path.join(HERE, "e8_reports")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def gql(key, query, variables=None):
    r = requests.post(f"{GQL}?api_key={key}",
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(json.dumps(j["errors"])[:400])
    return j["data"]


def list_pods(key):
    return gql(key, "query { myself { pods { id desiredStatus costPerHr "
                    "runtime { uptimeInSeconds } } clientBalance } }")["myself"]


def terminate(key, pod_id):
    if not pod_id:
        return
    try:
        gql(key, "mutation($id:String!){ podTerminate(input:{podId:$id}) }", {"id": pod_id})
        log(f"terminate() sent for {pod_id}")
    except Exception as e:  # noqa: BLE001
        log(f"terminate() error (watchdog will back this up): {e}")


def r2_status(pub, run_id):
    try:
        r = requests.get(f"{pub}/proof/{run_id}/status.json",
                         timeout=20, headers={"Cache-Control": "no-cache"})
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa: BLE001
        pass
    return {}


def load_source_url():
    """Read-only DB lookup: the black-dress source image R2 URL."""
    from app.core.database import SessionLocal
    from app.models.character_image import CharacterImage
    db = SessionLocal()
    try:
        row = db.query(CharacterImage).filter(CharacterImage.id == SOURCE_IMAGE_ID).first()
        if not row or row.character_id != SUMMER:
            raise SystemExit(f"source image {SOURCE_IMAGE_ID} missing or not Summer's")
        return row.file_path
    finally:
        db.close()


def load_lora_url():
    """Read-only: active Summer LoRA artifact from the enforcement plan."""
    from app.core.database import SessionLocal
    from app.services.adult_identity_enforcement_plan import build_enforcement_plan
    db = SessionLocal()
    try:
        plan = build_enforcement_plan(
            SUMMER, db, route_expectations={"sleeve": "ip_adapter",
                                            "ballerina": "controlnet_canny"})
        if not plan["ready_for_executor"]:
            raise SystemExit(f"plan not ready_for_executor: {plan['blocking_reasons']}")
        return plan["model_artifact_uri"]
    finally:
        db.close()


def write_report(report, run_id):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"{run_id}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp, path)
    return path


def build_report(pod_id, gpu, st, spend, runtime_s, no_orphans, run_id,
                 source_url, lora_url, extra_error=None):
    images = (st or {}).get("images", {})
    errors = list((st or {}).get("errors", []))
    if extra_error:
        errors.append(extra_error)
    fatal = any("fatal" in str(e).lower() for e in errors)
    done = bool((st or {}).get("done"))
    final = images.get("99_final")
    report = {
        "executor": "e8_bakeoff_driver",
        "version": "v1",
        "experiment": "e8_img2img_bakeoff",
        "run_id": run_id,
        "character_id": SUMMER,
        "source_image_id": SOURCE_IMAGE_ID,
        "source_url": source_url,
        "lora_url": lora_url,
        "gpu": gpu,
        "pod_id": pod_id,
        "spend_cap_usd": SPEND_CAP,
        "spend_usd": round(spend, 4),
        "runtime_s": round(runtime_s, 1),
        "strength": (st or {}).get("strength"),
        "stage_images": images,
        "final_image_url": final,
        "lora_loaded": (st or {}).get("lora_loaded"),
        "pod_status_final": (st or {}).get("stage"),
        "pod_errors": errors,
        "no_orphaned_pods": no_orphans,
        "success": done and not fatal and bool(final)
                   and spend < SPEND_CAP and no_orphans,
    }
    write_report(report, run_id)
    return report


def launch(key, env, wrapper_b64):
    body = {
        "name": "e8-img2img-bakeoff",
        "imageName": "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04",
        "gpuCount": 1,
        "cloudType": "COMMUNITY",
        "containerDiskInGb": 40,
        "volumeInGb": 0,
        "ports": ["8888/http"],
        "env": env,
        "dockerStartCmd": ["bash", "-c", f"echo {wrapper_b64} | base64 -d | bash"],
    }
    for gpu in GPU_CANDIDATES:
        body["gpuTypeIds"] = [gpu]
        rr = requests.post(REST, headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"},
                           json=body, timeout=90)
        if rr.status_code in (200, 201):
            pod = rr.json()
            log(f"LAUNCHED gpu={gpu} pod={pod.get('id')} rate=${pod.get('costPerHr')}")
            return pod, gpu
        log(f"launch on {gpu} failed ({rr.status_code}): {rr.text[:200]}")
    return None, None


def main():
    key = os.environ["RUNPOD_API_KEY"]
    pub = os.environ["R2_PUBLIC_URL"]
    run_id = os.environ.get("E8_RUN_ID") or ("e8_bakeoff_" + time.strftime("%Y%m%d_%H%M%S"))

    source_url = load_source_url()
    lora_url = load_lora_url()
    log(f"run_id={run_id} source={source_url[-40:]} lora={lora_url[:40]}...")
    log(f"max_safe_rate=${MAX_SAFE_RATE}/hr cap=${SPEND_CAP} watchdog={WATCHDOG_S}s")

    with open(os.path.join(HERE, "e8_bakeoff_pod.py"), "rb") as f:
        proof_b64 = base64.b64encode(f.read()).decode()

    wrapper = (
        '#!/bin/bash\n'
        'KEY="$RUNPOD_API_KEY"; PODID="$RUNPOD_POD_ID"\n'
        'command -v curl >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq curl)\n'
        'selfkill(){ curl -s -X POST "https://api.runpod.io/graphql?api_key=$KEY" '
        '-H "Content-Type: application/json" '
        '-d "{\\"query\\":\\"mutation { podTerminate(input:{podId:\\\\\\"$PODID\\\\\\"}) }\\"}"; }\n'
        f'( sleep {WATCHDOG_S}; echo WATCHDOG_FIRED; selfkill ) &\n'
        'mkdir -p /workspace\n'
        'echo "$PROOF_PY_B64" | base64 -d > /workspace/proof.py\n'
        'echo "[start] installing deps $(date)"\n'
        'pip install -q --no-cache-dir "diffusers==0.31.0" "transformers==4.46.3" accelerate '
        'safetensors peft boto3 2>&1 | tail -3\n'
        'pip install -q --no-cache-dir "numpy==1.26.4" 2>&1 | tail -2\n'
        'echo "[start] running proof $(date)"\n'
        'python /workspace/proof.py\n'
        'echo "MAIN_DONE rc=$?"\n'
        'selfkill\n'
    )
    wrapper_b64 = base64.b64encode(wrapper.encode()).decode()

    env = {
        "RUNPOD_API_KEY": key,
        "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
        "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
        "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
        "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
        "R2_PUBLIC_URL": pub,
        "PROOF_RUN_ID": run_id,
        "PROOF_PY_B64": proof_b64,
        "SOURCE_URL": source_url,
        "LORA_URL": lora_url,
        "E8_STRENGTH": os.environ.get("E8_STRENGTH", "0.65"),
    }
    if os.environ.get("HF_TOKEN"):
        env["HF_TOKEN"] = os.environ["HF_TOKEN"]

    build_report(None, None, {"stage": "launching"}, 0.0, 0.0, True,
                 run_id, source_url, lora_url)

    pod, gpu = launch(key, env, wrapper_b64)
    if pod is None:
        log("ABORT: no community GPU available; NO pod launched, NO spend.")
        build_report(None, None, {"stage": "aborted_no_gpu", "done": True}, 0.0, 0.0,
                     True, run_id, source_url, lora_url,
                     extra_error="fatal: no community GPU available")
        sys.exit(2)

    pod_id = pod["id"]

    rate = float(pod.get("costPerHr") or 0.0)
    if rate <= 0 or rate > MAX_SAFE_RATE:
        log(f"RATE GUARD TRIPPED rate=${rate}/hr > max_safe=${MAX_SAFE_RATE}/hr — terminating.")
        terminate(key, pod_id)
        time.sleep(6)
        try:
            still = {p["id"]: p for p in list_pods(key)["pods"]}
            no_orphans = pod_id not in still or still[pod_id].get("desiredStatus") in (
                "TERMINATED", "EXITED")
        except Exception:  # noqa: BLE001
            no_orphans = False
        build_report(pod_id, gpu, {"stage": "rate_guard", "done": True}, 0.0, 0.0,
                     no_orphans, run_id, source_url, lora_url,
                     extra_error=f"fatal: rate_guard ${rate}/hr > ${MAX_SAFE_RATE}/hr")
        sys.exit(3)

    t0 = time.time()
    st, spend, no_orphans = {}, 0.0, False
    try:
        while True:
            time.sleep(POLL_S)
            me = list_pods(key)
            pods = {p["id"]: p for p in me["pods"]}
            st = r2_status(pub, run_id)
            up = (pods.get(pod_id, {}).get("runtime") or {}).get("uptimeInSeconds") or 0
            rate = pods.get(pod_id, {}).get("costPerHr") or rate or 0.16
            spend = round(up / 3600.0 * rate, 4)
            build_report(pod_id, gpu, st, spend, time.time() - t0, True,
                         run_id, source_url, lora_url)
            if pod_id not in pods:
                log("pod self-terminated (gone).")
                break
            stage = st.get("stage", "(no status yet)")
            log(f"up={up}s spend=${spend} stage={stage} done={st.get('done')}")
            reason = None
            if st.get("done"):
                reason = "pipeline done"
            elif spend >= TERMINATE_AT:
                reason = f"SPEND CAP guard ${spend} >= ${TERMINATE_AT}"
            elif up >= DRIVER_WALLCLOCK_S:
                reason = f"driver wallclock {up}s"
            elif any("fatal" in str(e).lower() for e in (st.get("errors") or [])):
                reason = "fatal pod error"
            if reason:
                log(f"==> TERMINATING ({reason})")
                terminate(key, pod_id)
                break
    except Exception as e:  # noqa: BLE001
        log(f"driver loop error: {e}")
        traceback.print_exc()
    finally:
        terminate(key, pod_id)  # idempotent — guarantee no orphan
        time.sleep(8)
        try:
            still = {p["id"]: p for p in list_pods(key)["pods"]}
            no_orphans = pod_id not in still or still[pod_id].get("desiredStatus") in (
                "TERMINATED", "EXITED")
            log(f"post-terminate: present={pod_id in still} no_orphans={no_orphans}")
        except Exception as e:  # noqa: BLE001
            log(f"orphan-check error: {e}")

    st = r2_status(pub, run_id) or st
    report = build_report(pod_id, gpu, st, spend, time.time() - t0, no_orphans,
                          run_id, source_url, lora_url)
    log(f"DONE success={report['success']} spend=${spend} "
        f"final={report['final_image_url']} no_orphans={no_orphans}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"FATAL driver: {e}")
        traceback.print_exc()
        sys.exit(1)
