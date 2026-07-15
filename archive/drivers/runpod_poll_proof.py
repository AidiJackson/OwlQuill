"""One-shot poll + cap-enforcer for the proof pod. Call repeatedly.

Prints a concise status line. Terminates the pod (and records it) when ANY of:
  - R2 status.json reports done
  - spend estimate >= SPEND_CAP
  - uptime >= WALLCLOCK_CAP_S
  - the pod has already vanished (self-terminated)
"""
import json
import os

import requests

import runpod_proof_lib as L

st_file = L.STATE
with open(st_file) as f:
    st = json.load(f)
pod_id = st.get("pod_id")
run_id = st.get("run_id")

me = L.list_pods()
pods = {p["id"]: p for p in me["pods"]}
balance = me["clientBalance"]

# Fetch R2 progress (best-effort).
r2 = {}
try:
    url = st.get("r2_status_url")
    if url:
        rr = requests.get(url, timeout=15)
        if rr.status_code == 200:
            r2 = rr.json()
except Exception:
    pass

if pod_id not in pods:
    L.write_state(pod_status="GONE", current_stage="pod not present (self-terminated)",
                  r2_stage=r2.get("stage"), r2_done=r2.get("done"))
    print(f"POD GONE (self-terminated). r2_stage={r2.get('stage')} done={r2.get('done')} "
          f"images={list((r2.get('images') or {}).keys())} balance=${balance:.2f}")
    raise SystemExit(0)

p = pods[pod_id]
up = (p.get("runtime") or {}).get("uptimeInSeconds") or 0
rate = p.get("costPerHr") or L.RATE
spend = round(up / 3600.0 * rate, 4)
reason = None
if r2.get("done"):
    reason = "proof done"
elif spend >= L.SPEND_CAP:
    reason = f"SPEND CAP hit ${spend}"
elif up >= L.WALLCLOCK_CAP_S:
    reason = f"wallclock cap {up}s"

L.write_state(pod_status=p.get("desiredStatus"), uptime_s=up,
              current_stage=r2.get("stage", "(no r2 status yet)"),
              r2_done=r2.get("done"), r2_errors=r2.get("errors"),
              spend={"spend_cap_usd": L.SPEND_CAP, "cost_per_hr_usd": L.RATE,
                     "gpu_type": "RTX 4090", "estimated_spend_usd": spend})

print(f"pod={pod_id[:12]} status={p.get('desiredStatus')} up={up}s spend=${spend} "
      f"r2_stage={r2.get('stage')} done={r2.get('done')} imgs={list((r2.get('images') or {}).keys())} "
      f"errs={r2.get('errors')} bal=${balance:.2f}")

if reason:
    print(f"==> TERMINATING ({reason})")
    L.terminate(pod_id)
    L.write_state(pod_status="TERMINATED", current_stage=f"terminated: {reason}",
                  terminated_reason=reason)
    print("terminate() sent.")
