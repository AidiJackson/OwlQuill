#!/usr/bin/env python3
"""Sprint 10 — Summer Adult Studio FOUNDER VALIDATION PACK driver (hardened RunPod).

Launches ONE community GPU pod that loads the masked-diffusion pipeline once and runs
the full Adult Studio enforcement (both tattoos) across 5 outfits: casual, sleeveless
top, cocktail dress, swimwear, fitness/gymwear. Inputs CONSUMED FROM THE DB enforcement
plan (active LoRA + the two mark reference crops). Streams every stage to R2.

ADMIN/INTERNAL. Summer only. NOT the normal generator, NOT Canon Studio, NOT a UI, NOT
public. Hard cap $0.25; cheapest community GPU; in-pod watchdog + external $0.22 guard +
finally-terminate guarantee no orphan and no breach. Does NOT score quality — emits a
founder-review report (per-image URL, cost, runtime, route status, notes) for manual
review. Run in BACKGROUND.
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
GPU_CANDIDATES = ["NVIDIA RTX A5000", "NVIDIA RTX A4500", "NVIDIA GeForce RTX 3090"]
SPEND_CAP = 0.25
TERMINATE_AT = 0.22        # external kill threshold (margin below hard cap)
WATCHDOG_S = 2700          # in-pod backstop; worst-case ~$0.165 @ $0.22/hr
DRIVER_WALLCLOCK_S = 2700
POLL_S = 30
OUTFIT_KEYS = ["casual", "sleeveless_top", "cocktail_dress", "swimwear", "fitness"]

STATE = os.path.join(HERE, "runpod_sprint10_state.json")
REPORT = os.path.join(HERE, "summer_founder_validation_pack_report.json")
RUN_ID = "summer_s10_" + time.strftime("%Y%m%d_%H%M%S", time.gmtime())


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
        log(f"terminate() error (watchdog backstop remains): {e}")


def save_state(**kw):
    try:
        st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    except Exception:
        st = {}
    st.update(kw)
    st["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(st, open(STATE, "w"), indent=2)


def r2_status(pub):
    try:
        rr = requests.get(f"{pub.rstrip('/')}/proof/{RUN_ID}/status.json", timeout=15)
        if rr.status_code == 200:
            return rr.json()
    except Exception:
        pass
    return {}


def load_inputs():
    db = SessionLocal()
    try:
        plan = build_enforcement_plan(SUMMER, db, route_expectations={
            "sleeve": "ip_adapter", "ballerina": "controlnet_canny"})
        if not plan["ready_for_executor"]:
            raise SystemExit(f"plan not ready: {plan['blocking_reasons']}")
        by = {m["route"]: m for m in plan["marks"]}
        return plan, by
    finally:
        db.close()


def launch(env, wrapper_b64):
    body = {"name": "summer-s10-valpack",
            "imageName": "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04",
            "gpuCount": 1, "cloudType": "COMMUNITY", "containerDiskInGb": 40,
            "volumeInGb": 0, "ports": ["8888/http"], "env": env,
            "dockerStartCmd": ["bash", "-c", f"echo {wrapper_b64} | base64 -d | bash"]}
    for gpu in GPU_CANDIDATES:
        body["gpuTypeIds"] = [gpu]
        rr = requests.post(REST, headers={"Authorization": f"Bearer {KEY}",
                                          "Content-Type": "application/json"},
                           json=body, timeout=90)
        if rr.status_code in (200, 201):
            pod = rr.json()
            log(f"LAUNCHED gpu={gpu} pod={pod.get('id')} rate=${pod.get('costPerHr')}")
            return pod, gpu
        log(f"launch on {gpu} failed ({rr.status_code}): {rr.text[:150]}")
    return None, None


def build_report(plan, pod_id, gpu, st, spend, runtime_s, no_orphans):
    outfits = (st or {}).get("outfits", {})
    rt_sum = sum((outfits.get(k, {}).get("runtime_s") or 0) for k in OUTFIT_KEYS) or 1.0
    images = []
    for k in OUTFIT_KEYS:
        o = outfits.get(k, {})
        imgs = o.get("images", {})
        ort = o.get("runtime_s")
        # apportion total pod spend across outfits by their runtime share
        ocost = round(spend * ((ort or 0) / rt_sum), 5) if ort else None
        images.append({
            "outfit": k,
            "description": o.get("desc"),
            "final_image_url": imgs.get("99_final"),
            "base_image_url": imgs.get("01_base"),
            "intermediate_artifacts": {
                "mask_right_upper_arm": imgs.get("02_mask_right_upper_arm"),
                "mask_left_forearm": imgs.get("02_mask_left_forearm"),
                "after_butterfly": imgs.get("03_after_butterfly"),
                "ballerina_canny_control": imgs.get("03b_ballerina_canny_control"),
                "after_ballerina": imgs.get("04_after_ballerina"),
            },
            "route_execution": {
                "ip_adapter_butterfly_right_upper_arm": o.get("routes", {}).get("ip_adapter"),
                "controlnet_canny_ballerina_left_forearm": o.get("routes", {}).get("controlnet_canny"),
            },
            "arm_pixels": o.get("arm_pixels"),
            "runtime_s": ort,
            "cost_usd_apportioned": ocost,
            "errors": o.get("errors", []),
            "notes": "",  # for the founder to fill in
        })
    completed = [i for i in images if i["final_image_url"]]
    return {
        "executor": "runpod_validation_pack",
        "sprint": "phase3-sprint10",
        "purpose": "founder manual review of Adult Studio quality (NO auto-scoring)",
        "run_id": RUN_ID, "character_id": SUMMER, "character": "Summer Fielding",
        "identity_id": plan["identity_id"], "active_version_id": plan["active_version_id"],
        "model_artifact_uri": plan["model_artifact_uri"],
        "gpu": gpu, "pod_id": pod_id,
        "spend_cap_usd": SPEND_CAP, "spend_usd_total": round(spend, 4),
        "runtime_s_total": round(runtime_s, 1),
        "outfits_completed": f"{len(completed)}/{len(OUTFIT_KEYS)}",
        "lora_loaded": (st or {}).get("lora_loaded"),
        "ip_adapter_loaded": (st or {}).get("ip_adapter_loaded"),
        "images": images,
        "founder_review_checklist_per_image": [
            "tattoo placement accuracy", "tattoo fidelity", "face consistency",
            "body consistency", "clothing stability", "overall character recognition"],
        "no_orphaned_pods": no_orphans,
        "flags": {"ADULT_STUDIO_TRAINING_ENABLED": settings.ADULT_STUDIO_TRAINING_ENABLED,
                  "ADULT_STUDIO_PROVIDER": settings.ADULT_STUDIO_PROVIDER},
        "auto_quality_scoring": False,
        "manual_review_required": True,
        "pod_errors": (st or {}).get("errors", []),
        "success": len(completed) >= 1 and spend < SPEND_CAP and no_orphans,
    }


def main():
    pub = os.environ["R2_PUBLIC_URL"]
    plan, by = load_inputs()
    env = {
        "RUNPOD_API_KEY": KEY,
        "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
        "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
        "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
        "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
        "R2_PUBLIC_URL": pub,
        "LORA_URL": plan["model_artifact_uri"],
        "BUTTERFLY_URL": by["ip_adapter"]["reference_uri"],
        "BALLERINA_URL": by["controlnet_canny"]["reference_uri"],
        "PROOF_RUN_ID": RUN_ID,
    }
    with open(os.path.join(HERE, "comfyui_validation_pack_pod.py"), "rb") as f:
        env["PROOF_PY_B64"] = base64.b64encode(f.read()).decode()
    log(f"plan consumed: lora ok, butterfly+ballerina refs ok; outfits={OUTFIT_KEYS}")

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
        'echo "[start] running pack $(date)"\n'
        'python /workspace/proof.py\n'
        'echo "MAIN_DONE rc=$?"\n'
        'selfkill\n'
    )
    wrapper_b64 = base64.b64encode(wrapper.encode()).decode()

    save_state(run_id=RUN_ID, stage="launching", spend_cap_usd=SPEND_CAP)
    pod, gpu = launch(env, wrapper_b64)
    if pod is None:
        log("ABORT: no community GPU available; NO pod, NO spend.")
        save_state(stage="aborted_no_gpu")
        json.dump(build_report(plan, None, None, {}, 0.0, 0.0, True), open(REPORT, "w"), indent=2)
        sys.exit(2)
    pod_id = pod["id"]
    save_state(pod_id=pod_id, gpu=gpu, stage="running",
               r2_status_url=f"{pub.rstrip('/')}/proof/{RUN_ID}/status.json")

    t0 = time.time()
    st, spend, no_orphans = {}, 0.0, False
    try:
        while True:
            time.sleep(POLL_S)
            me = list_pods()
            pods = {p["id"]: p for p in me["pods"]}
            st = r2_status(pub)
            done_outfits = [k for k in OUTFIT_KEYS
                            if (st.get("outfits", {}).get(k, {}) or {}).get("final_done")]
            if pod_id not in pods:
                log("pod self-terminated (gone)."); break
            p = pods[pod_id]
            up = (p.get("runtime") or {}).get("uptimeInSeconds") or 0
            rate = p.get("costPerHr") or 0.19
            spend = round(up / 3600.0 * rate, 4)
            log(f"up={up}s spend=${spend} stage={st.get('stage')} "
                f"done_outfits={done_outfits} errs={len(st.get('errors') or [])}")
            save_state(uptime_s=up, spend_usd=spend, stage=st.get("stage"),
                       done_outfits=done_outfits)
            reason = None
            if st.get("done"):
                reason = "pack done"
            elif spend >= TERMINATE_AT:
                reason = f"SPEND GUARD ${spend} >= ${TERMINATE_AT}"
            elif up >= DRIVER_WALLCLOCK_S:
                reason = f"driver wallclock {up}s"
            elif any("fatal" in str(e).lower() for e in (st.get("errors") or [])):
                reason = "fatal pod error"
            if reason:
                log(f"==> TERMINATING ({reason})"); terminate(pod_id); break
    except Exception as e:  # noqa: BLE001
        log(f"driver loop error: {e}"); traceback.print_exc()
    finally:
        terminate(pod_id)
        time.sleep(8)
        try:
            me = list_pods()
            still = {p["id"]: p for p in me["pods"]}
            no_orphans = pod_id not in still or still[pod_id].get("desiredStatus") in (
                "TERMINATED", "EXITED")
            log(f"post-terminate no_orphans={no_orphans} balance=${me.get('clientBalance')}")
        except Exception as e:  # noqa: BLE001
            log(f"orphan-check error: {e}")

    st = r2_status(pub) or st
    report = build_report(plan, pod_id, gpu, st, spend, time.time() - t0, no_orphans)
    json.dump(report, open(REPORT, "w"), indent=2)
    save_state(stage="finished", spend_usd=spend, no_orphaned_pods=no_orphans,
               outfits_completed=report["outfits_completed"])
    log(f"DONE outfits={report['outfits_completed']} spend=${spend} no_orphans={no_orphans}")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"FATAL driver: {e}"); traceback.print_exc()
        try:
            terminate(json.load(open(STATE)).get("pod_id"))
        except Exception:
            pass
        sys.exit(1)
