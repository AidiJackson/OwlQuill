#!/usr/bin/env python3
"""Sprint 23C — TATTOO-SAFE HIRES driver (throwaway, founder-only).

Ships s23c_tattoo_safe_pod.py: the 23B stack + tattoo-safe hires restore —
23A-A canon-grounded base -> unchanged tattoo enforcement -> 1.5x hires re-detail ->
IP-Adapter-FaceID face refine (identity as a 512-d embedding from FACE_EMBED_KEY).
EXPERIMENT-ONLY licensing: FaceID + InsightFace artifacts are non-commercial.

Safety: SPEND_CAP=0.15, 1800s in-pod watchdog, 1800s driver wallclock, launch-time
RATE GUARD (max safe ~$0.285/hr), finally-terminate, orphan verify.

Inputs are CONSUMED FROM THE DB enforcement plan (active LoRA + the two mark crops keyed
by route) + the locked identity canon. Summer only. No UI, no public path, no Canon
Studio writes, no training, no normal generator.
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

GPU_CANDIDATES = ["NVIDIA RTX A5000", "NVIDIA RTX A4500", "NVIDIA GeForce RTX 3090"]
SPEND_CAP = 0.15            # S23B: 4 candidates x 5 stages in one pod
TERMINATE_AT = 0.14       # external kill threshold (margin below the cap)
WATCHDOG_S = 1800          # in-pod self-kill backstop; 1800s @ $0.22/hr = $0.11 < cap
DRIVER_WALLCLOCK_S = 1800  # driver-side max observed uptime before force-kill
POLL_S = 20
# Max GPU rate that still keeps the 700s watchdog worst-case under the cap (5% margin).
MAX_SAFE_RATE = round(SPEND_CAP / (WATCHDOG_S / 3600.0) * 0.95, 4)

REPORTS_DIR = os.path.join(HERE, "founder_reports")

# Populated in main() before any report is written; embedded in every report.
CANON_GROUNDING = {}


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


def write_report(report, run_id):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    path = os.path.join(REPORTS_DIR, f"{run_id}.json")
    # Atomic-ish: write temp then replace so the backend never reads a half file.
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp, path)
    return path


def r2_status(pub_url, run_id):
    try:
        rr = requests.get(f"{pub_url.rstrip('/')}/proof/{run_id}/status.json", timeout=15)
        if rr.status_code == 200:
            return rr.json()
    except Exception:
        pass
    return {}


def load_plan_inputs():
    from app.core.database import SessionLocal
    from app.services.adult_identity_enforcement_plan import build_enforcement_plan
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


def load_canon_refs():
    """Read-only: Summer's LOCKED canon face_front + body_front card URLs."""
    from app.core.database import SessionLocal
    from app.models.character_identity_canon import CharacterIdentityCanon
    db = SessionLocal()
    try:
        row = (db.query(CharacterIdentityCanon)
               .filter_by(character_id=SUMMER).first())
        if not row or row.status != "locked":
            raise SystemExit("identity canon missing or not locked for Summer")
        face = json.loads(row.face_canon_json or "{}").get("face_front_image_url")
        body = json.loads(row.body_canon_json or "{}").get("body_front_image_url")
        if not face or not body:
            raise SystemExit(f"canon card URLs missing: face={face} body={body}")
        return face, body
    finally:
        db.close()


def build_report(plan, by_route, pod_id, gpu, st, spend, runtime_s, no_orphans,
                 run_id, base_prompt, extra_error=None):
    variants = (st or {}).get("candidates", {})
    done = bool((st or {}).get("done"))
    errors = list((st or {}).get("errors", []))
    if extra_error:
        errors.append(extra_error)
    finals = {vk: v.get("images", {}).get("99_final") for vk, v in variants.items()}
    fatal = any("fatal" in str(e).lower() for e in errors)
    # Completed = all four matrix cells produced a tattoo-enforced 99_final.
    diffusion_pass = "completed" if (
        done and not fatal and len(finals) == 4 and all(finals.values())) else "failed"

    variant_summary = {
        vk: {
            "seed": v.get("seed"),
            "errors": v.get("errors", []),
            "images": v.get("images", {}),
            "final": finals.get(vk),
        } for vk, v in variants.items()
    }

    report = {
        "executor": "s23c_tattoo_safe_driver",
        "version": "v1",
        "experiment": "s23c_tattoo_safe_hires",
        "canon_grounding": CANON_GROUNDING,
        "run_id": run_id,
        "character_id": SUMMER,
        "identity_id": plan["identity_id"],
        "active_version_id": plan["active_version_id"],
        "model_artifact_uri": plan["model_artifact_uri"],
        "base_prompt": base_prompt,
        "enforcement_mode": "masked_diffusion",
        "diffusion_pass": diffusion_pass,
        "gpu": gpu,
        "pod_id": pod_id,
        "spend_cap_usd": SPEND_CAP,
        "spend_usd": round(spend, 4),
        "runtime_s": round(runtime_s, 1),
        "candidates": variant_summary,
        "faceid_loaded": (st or {}).get("faceid_loaded"),
        "final_image_urls": finals,
        "pod_status_final": (st or {}).get("stage"),
        "pod_errors": errors,
        "lora_loaded": (st or {}).get("lora_loaded"),
        "no_orphaned_pods": no_orphans,
        "manual_review_required": True,
        "success": diffusion_pass == "completed" and spend < SPEND_CAP and no_orphans,
    }
    write_report(report, run_id)
    return report


def launch(key, env, wrapper_b64):
    body = {
        "name": "s23c-tattoo-safe",
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
    run_id = os.environ.get("FOUNDER_RUN_ID") or ("s23c_safehires_" + time.strftime(
        "%Y%m%d_%H%M%S", time.gmtime()))
    base_prompt = os.environ.get("BASE_PROMPT") or ""
    base_model_id = os.environ.get("BASE_MODEL_ID", "SG161222/RealVisXL_V4.0")

    plan, by_route = load_plan_inputs()
    lora = plan["model_artifact_uri"]
    butterfly = by_route["ip_adapter"]["reference_uri"]
    ballerina = by_route["controlnet_canny"]["reference_uri"]
    face_ref, body_ref = load_canon_refs()
    CANON_GROUNDING.update({"base_model_id": base_model_id,
                            "stack": "23B + tattoo-safe hires (arm-mask paste-back through "
                                     "the 1.5x re-detail), best-of-4 seeds",
                            "face_ref_url": face_ref, "body_ref_url": body_ref})
    log(f"run_id={run_id} plan consumed: lora={lora[:40]}... "
        f"butterfly={butterfly[-20:]} ballerina={ballerina[-20:]}")
    log(f"canon cards: face={face_ref[-24:]} body={body_ref[-24:]} "
        f"base_model={base_model_id}")
    log(f"max_safe_rate=${MAX_SAFE_RATE}/hr cap=${SPEND_CAP}")

    with open(os.path.join(HERE, "s23c_tattoo_safe_pod.py"), "rb") as f:
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
        "RUNPOD_API_KEY": key,
        "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
        "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
        "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
        "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
        "R2_PUBLIC_URL": pub,
        "LORA_URL": lora,
        "BUTTERFLY_URL": butterfly,
        "BALLERINA_URL": ballerina,
        "PROOF_RUN_ID": run_id,
        "PROOF_PY_B64": proof_b64,
        "BASE_PROMPT": base_prompt,  # founder prompt → pod base gen
        "FACE_REF_URL": face_ref,    # canon face card → base-pass grounding
        "BODY_REF_URL": body_ref,    # canon body card → base-pass grounding
        "FACE_EMBED_KEY": os.environ.get("FACE_EMBED_KEY",
                                         "proof/s23b_inputs/face_embed.json"),
        "BASE_MODEL_ID": base_model_id,
    }

    # Seed an initial running report so the backend can reconcile even before the pod
    # streams anything (final_image_url stays null until 99_final exists).
    build_report(plan, by_route, None, None, {"stage": "launching"}, 0.0, 0.0, True,
                 run_id, base_prompt)

    pod, gpu = launch(key, env, wrapper_b64)
    if pod is None:
        log("ABORT: no community GPU available; NO pod launched, NO spend.")
        build_report(plan, by_route, None, None, {"stage": "aborted_no_gpu", "done": True},
                     0.0, 0.0, True, run_id, base_prompt,
                     extra_error="fatal: no community GPU available")
        sys.exit(2)

    pod_id = pod["id"]

    # ── Launch-time RATE GUARD: if the GPU rate could breach the cap, kill now ──
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
        build_report(plan, by_route, pod_id, gpu, {"stage": "rate_guard", "done": True},
                     0.0, 0.0, no_orphans, run_id, base_prompt,
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
            # Persist progress so the backend can show intermediate state.
            up = (pods.get(pod_id, {}).get("runtime") or {}).get("uptimeInSeconds") or 0
            rate = pods.get(pod_id, {}).get("costPerHr") or rate or 0.16
            spend = round(up / 3600.0 * rate, 4)
            build_report(plan, by_route, pod_id, gpu, st, spend, time.time() - t0,
                         True, run_id, base_prompt)
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
    report = build_report(plan, by_route, pod_id, gpu, st, spend, time.time() - t0,
                          no_orphans, run_id, base_prompt)
    log(f"DONE diffusion_pass={report['diffusion_pass']} spend=${spend} "
        f"finals={list(report['final_image_urls'].values())} no_orphans={no_orphans}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"FATAL driver: {e}")
        traceback.print_exc()
        sys.exit(1)
