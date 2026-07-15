#!/usr/bin/env python3
"""Sprint 8 — hardened RunPod driver: REAL masked-diffusion Summer tattoo enforcement.

ADMIN/INTERNAL operational validation. Launches ONE community GPU pod that runs the
proven Phase-0 pod-side inpaint pipeline (base SDXL + Summer LoRA -> SegFormer arm masks
-> IP-Adapter butterfly pass on right upper arm -> ControlNet-Canny ballerina pass on
left forearm -> 99_final), streaming every stage to R2. This is the diffusion denoise
pass Sprint 7 deferred.

Inputs are CONSUMED FROM THE DB enforcement plan (active LoRA artifact + the two mark
reference crops keyed by route), not hardcoded.

HARD SAFETY (tuned to the $0.20 cap — far tighter than Phase 0's $5):
  - Cheapest community GPU only (A5000 ~$0.16/hr; fallbacks A4500/3090). No secure cloud.
  - In-pod watchdog self-kills at WATCHDOG_S (backstop if this driver dies).
  - External tight loop (every POLL_S) terminates on: status done / estimated spend
    >= TERMINATE_AT / driver wallclock / fatal pod error / pod already gone.
  - finally: terminate the pod no matter how the driver exits (idempotent).
  - pod_id persisted to state immediately on launch for manual cleanup.
At A5000 $0.16/hr, WATCHDOG_S=2100 => worst-case ~$0.093, comfortably under $0.20.

Summer only. No UI, no public path, no Canon Studio writes, no training, no normal
generator. Writes summer_adult_studio_masked_diffusion_report.json. Run in BACKGROUND.
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

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.adult_identity_enforcement_plan import build_enforcement_plan  # noqa: E402

KEY = os.environ["RUNPOD_API_KEY"]
GQL = "https://api.runpod.io/graphql"
REST = "https://rest.runpod.io/v1/pods"
SUMMER = 60

# Cheapest community GPUs first; all keep WATCHDOG_S spend well under the cap.
GPU_CANDIDATES = ["NVIDIA RTX A5000", "NVIDIA RTX A4500", "NVIDIA GeForce RTX 3090"]
SPEND_CAP = 0.20
TERMINATE_AT = 0.17        # external kill threshold (margin below the hard cap)
WATCHDOG_S = 2100          # in-pod self-kill backstop (~$0.093 @ $0.16/hr)
DRIVER_WALLCLOCK_S = 2100  # driver-side max observed uptime before force-kill
POLL_S = 25

STATE = os.path.join(HERE, "runpod_sprint8_state.json")
REPORT = os.path.join(HERE, "summer_adult_studio_masked_diffusion_report.json")
RUN_ID = "summer_s8_" + time.strftime("%Y%m%d_%H%M%S", time.gmtime())


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def gql(query, variables=None):
    r = requests.post(f"{GQL}?api_key={KEY}",
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(json.dumps(j["errors"])[:400])
    return j["data"]


def list_pods():
    return gql("query { myself { pods { id desiredStatus costPerHr "
               "runtime { uptimeInSeconds } } clientBalance } }")["myself"]


def terminate(pod_id):
    if not pod_id:
        return
    try:
        gql("mutation($id:String!){ podTerminate(input:{podId:$id}) }", {"id": pod_id})
        log(f"terminate() sent for {pod_id}")
    except Exception as e:  # noqa: BLE001
        log(f"terminate() error (will retry via watchdog): {e}")


def save_state(**kw):
    try:
        st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    except Exception:
        st = {}
    st.update(kw)
    st["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(st, open(STATE, "w"), indent=2)
    return st


def r2_status(pub_url):
    try:
        rr = requests.get(f"{pub_url.rstrip('/')}/proof/{RUN_ID}/status.json", timeout=15)
        if rr.status_code == 200:
            return rr.json()
    except Exception:
        pass
    return {}


def load_plan_inputs():
    db = SessionLocal()
    try:
        plan = build_enforcement_plan(
            SUMMER, db, route_expectations={"sleeve": "ip_adapter",
                                            "ballerina": "controlnet_canny"})
        if not plan["ready_for_executor"]:
            raise SystemExit(f"plan not ready_for_executor: {plan['blocking_reasons']}")
        by_route = {m["route"]: m for m in plan["marks"]}
        return plan, by_route
    finally:
        db.close()


def launch(env, wrapper_b64):
    body = {
        "name": "summer-s8-enforce",
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
        rr = requests.post(REST, headers={"Authorization": f"Bearer {KEY}",
                                          "Content-Type": "application/json"},
                           json=body, timeout=90)
        if rr.status_code in (200, 201):
            pod = rr.json()
            log(f"LAUNCHED gpu={gpu} pod={pod.get('id')} rate=${pod.get('costPerHr')}")
            return pod, gpu
        log(f"launch on {gpu} failed ({rr.status_code}): {rr.text[:200]}")
    return None, None


def build_report(plan, by_route, pod_id, gpu, st, spend, runtime_s, no_orphans):
    images = (st or {}).get("images", {})
    done = bool((st or {}).get("done"))
    errors = (st or {}).get("errors", [])
    final_url = images.get("99_final")
    fatal = any("fatal" in str(e).lower() for e in errors)
    diffusion_pass = "completed" if (done and final_url and not fatal) else "failed"

    routes_executed = []
    for route, art_key in (("ip_adapter", "03_after_butterfly"),
                           ("controlnet_canny", "04_after_ballerina")):
        m = by_route.get(route, {})
        routes_executed.append({
            "route": route,
            "region": m.get("region"),
            "side": m.get("side"),
            "canon_mark_id": m.get("canon_mark_id"),
            "reference_uri": m.get("reference_uri"),
            "result_artifact_url": images.get(art_key),
            "status": "executed" if images.get(art_key) else "attempted",
        })

    report = {
        "executor": "runpod_masked_diffusion_enforcer",
        "version": "v2",
        "run_id": RUN_ID,
        "character_id": SUMMER,
        "identity_id": plan["identity_id"],
        "active_version_id": plan["active_version_id"],
        "model_artifact_uri": plan["model_artifact_uri"],
        "enforcement_mode": "masked_diffusion",
        "diffusion_pass": diffusion_pass,
        "gpu": gpu,
        "pod_id": pod_id,
        "spend_cap_usd": SPEND_CAP,
        "spend_usd": round(spend, 4),
        "runtime_s": round(runtime_s, 1),
        "routes_executed": routes_executed,
        "base_image_url": images.get("01_base"),
        "intermediate_artifacts": {
            "mask_right_upper_arm": images.get("02_mask_right_upper_arm"),
            "mask_left_forearm": images.get("02_mask_left_forearm"),
            "after_butterfly": images.get("03_after_butterfly"),
            "ballerina_canny_control": images.get("03b_ballerina_canny_control"),
            "after_ballerina": images.get("04_after_ballerina"),
        },
        "final_image_url": final_url,
        "image_urls": {"base": images.get("01_base"), "final": final_url,
                       "artifacts": [u for u in images.values() if u]},
        "pod_status_final": (st or {}).get("stage"),
        "pod_errors": errors,
        "lora_loaded": (st or {}).get("lora_loaded"),
        "no_orphaned_pods": no_orphans,
        "flags": {
            "ADULT_STUDIO_TRAINING_ENABLED": settings.ADULT_STUDIO_TRAINING_ENABLED,
            "ADULT_STUDIO_PROVIDER": settings.ADULT_STUDIO_PROVIDER,
        },
        "manual_review_required": True,
        "success": diffusion_pass == "completed" and spend < SPEND_CAP and no_orphans,
    }
    json.dump(report, open(REPORT, "w"), indent=2)
    return report


def main():
    pub = os.environ["R2_PUBLIC_URL"]
    plan, by_route = load_plan_inputs()
    lora = plan["model_artifact_uri"]
    butterfly = by_route["ip_adapter"]["reference_uri"]
    ballerina = by_route["controlnet_canny"]["reference_uri"]
    log(f"plan consumed: lora={lora[:48]}... butterfly={butterfly[-24:]} "
        f"ballerina={ballerina[-24:]}")

    with open(os.path.join(HERE, "comfyui_proof_pod_inpaint.py"), "rb") as f:
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
        'safetensors peft boto3 opencv-python-headless 2>&1 | tail -3\n'
        'pip install -q --no-cache-dir "numpy==1.26.4" 2>&1 | tail -2\n'
        'echo "[start] running proof $(date)"\n'
        'python /workspace/proof.py\n'
        'echo "MAIN_DONE rc=$?"\n'
        'selfkill\n'
    )
    wrapper_b64 = base64.b64encode(wrapper.encode()).decode()

    env = {
        "RUNPOD_API_KEY": KEY,
        "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
        "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
        "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
        "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
        "R2_PUBLIC_URL": pub,
        "LORA_URL": lora,
        "BUTTERFLY_URL": butterfly,
        "BALLERINA_URL": ballerina,
        "PROOF_RUN_ID": RUN_ID,
        "PROOF_PY_B64": proof_b64,
    }

    save_state(run_id=RUN_ID, stage="launching", spend_cap_usd=SPEND_CAP)
    pod, gpu = launch(env, wrapper_b64)
    if pod is None:
        log("ABORT: no community GPU available; NO pod launched, NO spend.")
        save_state(stage="aborted_no_gpu")
        build_report(plan, by_route, None, None, {}, 0.0, 0.0, True)
        sys.exit(2)

    pod_id = pod["id"]
    save_state(pod_id=pod_id, gpu=gpu, stage="running",
               r2_status_url=f"{pub.rstrip('/')}/proof/{RUN_ID}/status.json")

    t0 = time.time()
    st = {}
    spend = 0.0
    no_orphans = False
    try:
        while True:
            time.sleep(POLL_S)
            me = list_pods()
            pods = {p["id"]: p for p in me["pods"]}
            st = r2_status(pub)
            if pod_id not in pods:
                log("pod self-terminated (gone).")
                break
            p = pods[pod_id]
            up = (p.get("runtime") or {}).get("uptimeInSeconds") or 0
            rate = p.get("costPerHr") or 0.16
            spend = round(up / 3600.0 * rate, 4)
            stage = st.get("stage", "(no status yet)")
            log(f"up={up}s spend=${spend} stage={stage} done={st.get('done')} "
                f"imgs={list((st.get('images') or {}).keys())} errs={len(st.get('errors') or [])}")
            save_state(uptime_s=up, spend_usd=spend, stage=stage,
                       images=st.get("images"), done=st.get("done"))
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
                terminate(pod_id)
                break
    except Exception as e:  # noqa: BLE001
        log(f"driver loop error: {e}")
        traceback.print_exc()
    finally:
        terminate(pod_id)  # idempotent — guarantee no orphan
        time.sleep(8)
        try:
            me = list_pods()
            still = {p["id"]: p for p in me["pods"]}
            gone = pod_id not in still or still[pod_id].get("desiredStatus") in (
                "TERMINATED", "EXITED")
            no_orphans = bool(gone)
            log(f"post-terminate: pod present={pod_id in still} no_orphans={no_orphans} "
                f"balance=${me.get('clientBalance')}")
        except Exception as e:  # noqa: BLE001
            log(f"orphan-check error: {e}")

    st = r2_status(pub) or st
    runtime_s = time.time() - t0
    report = build_report(plan, by_route, pod_id, gpu, st, spend, runtime_s, no_orphans)
    save_state(stage="finished", spend_usd=spend, final_image_url=report["final_image_url"],
               diffusion_pass=report["diffusion_pass"], no_orphaned_pods=no_orphans)
    log(f"DONE diffusion_pass={report['diffusion_pass']} spend=${spend} "
        f"final={report['final_image_url']} no_orphans={no_orphans}")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"FATAL driver: {e}")
        traceback.print_exc()
        # Best-effort: if a pod_id was recorded, kill it.
        try:
            st = json.load(open(STATE))
            terminate(st.get("pod_id"))
        except Exception:
            pass
        sys.exit(1)
