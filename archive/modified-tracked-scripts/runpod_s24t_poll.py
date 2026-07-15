#!/usr/bin/env python3
"""S24T validation poller — spend/uptime cap guard for the validation pod.

Thin sibling of runpod_kohya_poll.py, reading runpod_s24t_state.json. Watches the pod
via the RunPod GraphQL API + the R2 status.json, terminates the pod on completion /
uptime cap / spend cap, and stops the loop when the pod is gone.

  python runpod_s24t_poll.py          # one-shot
  python runpod_s24t_poll.py --watch  # loop until the pod is gone/terminated
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STATE = HERE / "runpod_s24t_state.json"
API = "https://api.runpod.io/graphql"


def _key():
    return os.environ["RUNPOD_API_KEY"]


def gql(query, variables=None):
    r = requests.post(f"{API}?api_key={_key()}",
                      json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(json.dumps(j["errors"])[:500])
    return j["data"]


def find_pod(pod_id):
    data = gql("query { myself { clientBalance pods { id costPerHr runtime { uptimeInSeconds } } } }")
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
    gen = status.get("generated") or status.get("done_count")

    if pod is None:
        print(f"POD GONE (self-terminated). final_stage={stage} done={done} "
              f"generated={gen} errs={errs} bal=${balance:.2f}")
        return True

    uptime = (pod.get("runtime") or {}).get("uptimeInSeconds") or 0
    cphr = pod.get("costPerHr") or 0.0
    spend = round(cphr * uptime / 3600.0, 4)
    print(f"pod={pod_id} stage={stage} gen={gen} uptime={uptime}s spend=${spend} "
          f"cphr=${cphr} done={done} bal=${balance:.2f}")

    reason = None
    if done:
        reason = "job done" + (f" errors={errs}" if errs else "")
    elif uptime >= caps.get("wallclock_cap_s", 2400):
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
    ap.add_argument("--state", default=None,
                    help="state file to poll (default runpod_s24t_state.json); "
                         "e.g. runpod_s24aa_state.json for the v4 validation run")
    args = ap.parse_args()
    state_path = (HERE / args.state) if args.state else STATE
    if not state_path.exists():
        print("no state file; launch a run first.")
        return 1
    st = json.loads(state_path.read_text())
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
    raise SystemExit(main())
