"""Shared helpers for the Summer tattoo-inpaint RunPod proof (Option 1 headless).

Safety model (triple self-terminate, $5 absolute cap):
  1. in-pod watchdog hard-kills at WATCHDOG_S (45 min)
  2. in-pod main script self-kills on completion/failure
  3. sandbox poller terminates on spend>=cap / uptime>=cap / done / error
"""
import json
import os
import time

import requests

API = "https://api.runpod.io/graphql"
KEY = os.environ["RUNPOD_API_KEY"]
GPU = "NVIDIA RTX A5000"   # cheap community card (~$0.16-0.22/hr); GraphQL-fallback only
RATE = 0.22            # $/hr estimate for A5000-class community (poller uses live costPerHr)
SPEND_CAP = 0.05       # absolute $ ceiling (founder one-shot)
WALLCLOCK_CAP_S = 700   # poller uptime cap; 700s @ $0.22/hr = $0.0428 < cap
WATCHDOG_S = 700        # in-pod self-kill backstop; 700s @ $0.22/hr = $0.0428 < cap
STATE = os.path.join(os.path.dirname(__file__), "runpod_phase0_state.json")


def gql(query, variables=None):
    r = requests.post(f"{API}?api_key={KEY}", json={"query": query, "variables": variables or {}}, timeout=60)
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(json.dumps(j["errors"])[:500])
    return j["data"]


def list_pods():
    return gql("query { myself { pods { id name desiredStatus costPerHr runtime { uptimeInSeconds } } clientBalance } }")["myself"]


def terminate(pod_id):
    return gql("mutation($id:String!){ podTerminate(input:{podId:$id}) }", {"id": pod_id})


def write_state(**kw):
    try:
        with open(STATE) as f:
            st = json.load(f)
    except Exception:
        st = {}
    st.update(kw)
    st["last_checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(STATE, "w") as f:
        json.dump(st, f, indent=2)
    return st
