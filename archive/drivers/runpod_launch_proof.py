"""Launch the headless Summer tattoo-inpaint proof pod. One-shot.

Bakes the pod-side inpaint script + a self-terminating startup wrapper into the
container command (base64 via env), launches an RTX 4090 on-demand, and records
pod_id + started_at into runpod_phase0_state.json.
"""
import base64
import os
import time

import runpod_proof_lib as L

HERE = os.path.dirname(__file__)
RUN_ID = "summer_tattoo_" + time.strftime("%Y%m%d_%H%M%S", time.gmtime())

# Founder one-shot scene. Composed to retain the 'TOK' LoRA trigger + arms-at-sides /
# forearms-visible framing (required for the LoRA to fire and for SegFormer to build
# both arm masks), while folding in the founder's requested beach-resort scene.
BASE_PROMPT = (
    "a photo of TOK, Summer Fielding, an adult woman with long blonde hair and blue eyes, "
    "at a luxury beach resort, standing near the shoreline, wearing a blue bikini, "
    "both arms straight and relaxed at her sides, forearms fully visible, "
    "golden hour sunlight, confident relaxed expression, full body shot, "
    "realistic photography, photorealistic"
)

with open(os.path.join(HERE, "comfyui_proof_pod_inpaint.py"), "rb") as f:
    proof_b64 = base64.b64encode(f.read()).decode()

WRAPPER = r'''#!/bin/bash
KEY="$RUNPOD_API_KEY"; PODID="$RUNPOD_POD_ID"
command -v curl >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq curl)
selfkill(){ curl -s -X POST "https://api.runpod.io/graphql?api_key=$KEY" -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation { podTerminate(input:{podId:\\\"$PODID\\\"}) }\"}"; }
# (1) hard watchdog (founder one-shot: 700s backstop keeps worst-case spend < $0.05)
( sleep 700; echo WATCHDOG_FIRED; selfkill ) &
mkdir -p /workspace
echo "$PROOF_PY_B64" | base64 -d > /workspace/proof.py
echo "[start] installing deps $(date)"
pip install -q --no-cache-dir "diffusers==0.31.0" "transformers==4.46.3" accelerate \
  safetensors peft boto3 opencv-python-headless 2>&1 | tail -3
# Image torch 2.2 needs numpy<2; deps above can pull numpy 2.x -> force-pin last.
pip install -q --no-cache-dir "numpy==1.26.4" 2>&1 | tail -2
echo "[start] running proof $(date)"
python /workspace/proof.py
echo "MAIN_DONE rc=$?"
# (2) main self-kill
selfkill
'''
wrapper_b64 = base64.b64encode(WRAPPER.encode()).decode()

env = {
    "RUNPOD_API_KEY": L.KEY,
    "R2_ACCOUNT_ID": os.environ["R2_ACCOUNT_ID"],
    "R2_ACCESS_KEY_ID": os.environ["R2_ACCESS_KEY_ID"],
    "R2_SECRET_ACCESS_KEY": os.environ["R2_SECRET_ACCESS_KEY"],
    "R2_BUCKET_NAME": os.environ["R2_BUCKET_NAME"],
    "R2_PUBLIC_URL": os.environ["R2_PUBLIC_URL"],
    "LORA_URL": "https://replicate.delivery/xezq/g0qan15PFK4gF5Kyh5gCOf5DPe9qtoKr4I1h2xQhPykN9gsWA/trained_model.tar",
    "BUTTERFLY_URL": f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/generated/49a155d1a8834e71885105519cfaab3e.png",
    "BALLERINA_URL": f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/generated/efd8bd5522af4be2a8f155647b43b64c.png",
    "PROOF_RUN_ID": RUN_ID,
    "PROOF_PY_B64": proof_b64,
    "BASE_PROMPT": BASE_PROMPT,
}
env_list = [{"key": k, "value": v} for k, v in env.items()]

# Embed the wrapper as a literal base64 blob (safe charset: no quotes/spaces) so
# container-arg parsing can't mangle it. The wrapper reads PROOF_PY_B64 from env.
docker_args = f'bash -c "echo {wrapper_b64} | base64 -d | bash"'

MUT = """
mutation($input: PodFindAndDeployOnDemandInput!) {
  podFindAndDeployOnDemand(input: $input) { id imageName machineId costPerHr }
}
"""
variables = {"input": {
    "cloudType": "COMMUNITY",
    "gpuCount": 1,
    "gpuTypeId": L.GPU,
    "name": "summer-tattoo-proof",
    "imageName": "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04",
    "containerDiskInGb": 40,
    "volumeInGb": 0,
    "dockerArgs": docker_args,
    "ports": "8888/http",
    "env": env_list,
}}

print(f"RUN_ID={RUN_ID}")

# Primary path: RunPod REST API (better placement than legacy GraphQL deploy).
import requests

rest_body = {
    "name": "summer-tattoo-proof",
    "imageName": "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04",
    # Founder one-shot: cheapest stable community cards only (~$0.16-0.22/hr) so the
    # 700s watchdog keeps worst-case spend < $0.05. No secure/expensive cards.
    "gpuTypeIds": [
        "NVIDIA RTX A5000",
        "NVIDIA RTX A4500",
    ],
    "gpuCount": 1,
    "cloudType": "COMMUNITY",
    "containerDiskInGb": 40,
    "volumeInGb": 0,
    "ports": ["8888/http"],
    "env": env,
    "dockerStartCmd": ["bash", "-c", f"echo {wrapper_b64} | base64 -d | bash"],
}
rr = requests.post(
    "https://rest.runpod.io/v1/pods",
    headers={"Authorization": f"Bearer {L.KEY}", "Content-Type": "application/json"},
    json=rest_body, timeout=90,
)
print("REST status:", rr.status_code)
if rr.status_code not in (200, 201):
    print("REST body:", rr.text[:800])
    # Fallback: legacy GraphQL deploy (single 4090).
    print("falling back to GraphQL deploy…")
    data = L.gql(MUT, variables)
    pod = data["podFindAndDeployOnDemand"]
else:
    pod = rr.json()
print("LAUNCHED pod:", {k: pod.get(k) for k in ("id", "name", "machineId", "costPerHr", "desiredStatus") if isinstance(pod, dict)})

# ── Post-launch rate guard ────────────────────────────────────────────────
# If the actual GPU rate would let the 700s watchdog breach the $0.05 cap, kill
# the pod immediately (spend so far ~seconds = negligible) and stop. With a 700s
# backstop, the max safe rate is 0.05/(700/3600) = $0.257/hr; use a 5% margin.
rate = float(pod.get("costPerHr") or 0.0)
MAX_SAFE_RATE = round(L.SPEND_CAP / (L.WATCHDOG_S / 3600.0) * 0.95, 4)
print(f"RATE GUARD: costPerHr=${rate}/hr max_safe=${MAX_SAFE_RATE}/hr")
if rate <= 0 or rate > MAX_SAFE_RATE:
    print(f"==> RATE GUARD TRIPPED (rate=${rate} > ${MAX_SAFE_RATE}). Terminating immediately.")
    try:
        L.terminate(pod["id"])
        print("terminate() sent — no orphaned pod.")
    except Exception as e:  # noqa: BLE001
        print("terminate FAILED:", e)
    L.write_state(run_id=RUN_ID, pod_id=pod["id"], pod_status="TERMINATED",
                  current_stage="rate guard tripped at launch (cap could not be guaranteed)",
                  terminated_reason=f"rate_guard ${rate}/hr > ${MAX_SAFE_RATE}/hr")
    raise SystemExit(3)

L.write_state(
    run_id=RUN_ID, pod_id=pod["id"], pod_status="LAUNCHED",
    current_stage="launched; container starting",
    started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    r2_status_url=f"{os.environ['R2_PUBLIC_URL'].rstrip('/')}/proof/{RUN_ID}/status.json",
    spend={"spend_cap_usd": L.SPEND_CAP, "cost_per_hr_usd": rate or L.RATE,
           "gpu_type": "A5000/A4500 community", "estimated_spend_usd": 0.0},
)
print("STATE WRITTEN. pod_id=", pod["id"])
