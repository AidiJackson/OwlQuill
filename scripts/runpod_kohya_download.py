#!/usr/bin/env python3
"""S24E — download the trained Summer LoRA v3 artifacts from R2.

Pulls the .safetensors, training log, status.json, and the local config snapshot into
scripts/artifacts/<run_id>/. Run after a `--mode train` job reports done.

  python runpod_kohya_download.py [--run-id RID]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STATE = HERE / "runpod_kohya_state.json"


def _pub_base() -> str:
    import os

    return os.environ["R2_PUBLIC_URL"].rstrip("/")


def _get(url: str, dest: Path) -> bool:
    r = requests.get(url, timeout=120)
    if r.status_code != 200:
        print(f"  miss ({r.status_code}): {url}")
        return False
    dest.write_bytes(r.content)
    print(f"  saved {dest.name} ({len(r.content)} bytes)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    run_id = args.run_id
    if not run_id and STATE.exists():
        run_id = json.loads(STATE.read_text()).get("run_id")
    if not run_id:
        print("no run_id (pass --run-id or run after a launch).")
        return 1

    base = f"{_pub_base()}/lora_training/{run_id}"
    out = HERE / "artifacts" / run_id
    out.mkdir(parents=True, exist_ok=True)
    print(f"downloading run {run_id} -> {out}")

    got_model = _get(f"{base}/out/summer_lora_v3.safetensors", out / "summer_lora_v3.safetensors")
    _get(f"{base}/out/train.log", out / "train.log")
    _get(f"{base}/status.json", out / "status.json")

    # local config snapshot alongside the artifact
    cfg_local = HERE / "summer_lora_v3_kohya_config.json"
    if cfg_local.exists():
        (out / "summer_lora_v3_kohya_config.json").write_bytes(cfg_local.read_bytes())

    print("done." if got_model else "done (no .safetensors yet — was this a dry-run or unfinished?).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
