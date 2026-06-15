#!/usr/bin/env python3
"""S24E — poll the kohya training pod and enforce the spend/uptime caps.

Reads runpod_kohya_state.json, queries the live pod (uptime + costPerHr + balance) and
the R2 status.json the in-pod script writes, prints the current stage, and TERMINATES the
pod when: the job is done/errored, uptime >= wallclock cap, or estimated spend >= cap.

  python runpod_kohya_poll.py            # single check
  python runpod_kohya_poll.py --watch    # loop until the pod is gone/terminated
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STATE = HERE / "runpod_kohya_state.json"
API = "https://api.runpod.io/graphql"


def gql(query, variables=None):
    r = requests.post(f"{API}?api_key={os.environ['RUNPOD_API_KEY']}",
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(json.dumps(j["errors"])[:300])
    return j["data"]


def find_pod(pod_id):
    data = gql("query { myself { pods { id desiredStatus costPerHr runtime { uptimeInSeconds } } clientBalance } }")
    me = data["myself"]
    pod = next((p for p in (me["pods"] or []) if p["id"] == pod_id), None)
    return pod, me["clientBalance"]


def terminate(pod_id):
    return gql("mutation($id:String!){ podTerminate(input:{podId:$id}) }", {"id": pod_id})


def r2_status(url):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def check_once(st) -> bool:
    """Return True when the pod is gone/terminated (loop should stop)."""
    pod_id = st.get("pod_id")
    caps = st.get("caps", {})
    if not pod_id:
        print("no pod_id in state; nothing to poll.")
        return True
    pod, balance = find_pod(pod_id)
    status = r2_status(st.get("r2_status_url", ""))
    stage = status.get("stage", "(no status yet)")
    done = bool(status.get("done"))
    errs = status.get("errors") or []

    if pod is None:
        print(f"POD GONE (self-terminated). final_stage={stage} done={done} errs={errs} bal=${balance:.2f}")
        return True

    uptime = (pod.get("runtime") or {}).get("uptimeInSeconds") or 0
    cphr = pod.get("costPerHr") or 0.0
    spend = round(cphr * uptime / 3600.0, 4)
    print(f"pod={pod_id} stage={stage} uptime={uptime}s spend=${spend} cphr=${cphr} "
          f"done={done} bal=${balance:.2f}")

    reason = None
    if done:
        reason = "job done" + (f" errors={errs}" if errs else "")
    elif uptime >= caps.get("wallclock_cap_s", 1800):
        reason = f"uptime cap {caps.get('wallclock_cap_s')}s reached"
    elif spend >= caps.get("spend_cap", 0.5):
        reason = f"spend cap ${caps.get('spend_cap')} reached"
    if reason:
        print(f"TERMINATING pod {pod_id}: {reason}")
        terminate(pod_id)
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=20)
    args = ap.parse_args()
    if not STATE.exists():
        print("no state file; launch a run first.")
        return 1
    st = json.loads(STATE.read_text())
    if not args.watch:
        check_once(st)
        return 0
    while True:
        try:
            if check_once(st):
                break
        except Exception as e:  # noqa: BLE001 - keep polling on transient API errors
            print("poll error:", str(e)[:200])
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
