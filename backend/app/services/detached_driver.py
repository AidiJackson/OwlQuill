"""Shared spawner for detached job-driver processes.

The editor, adult-founder and identity-pack job services all launch a
scripts/ driver the same way: ensure a log directory, merge job identifiers
into the environment, open an append-mode log, and Popen the driver detached
(``start_new_session=True``) with the repo root as cwd so it survives a
uvicorn dev reload. The Popen invariants live here once; each service keeps
its own driver path, env variables and log naming.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def spawn_detached_driver(
    *,
    driver_path: Path,
    log_dir: Path,
    log_name: str,
    extra_env: dict[str, str],
    cwd: Path,
) -> None:
    """Spawn one detached driver process; returns once it has started."""
    log_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **extra_env}
    logf = open(log_dir / f"{log_name}.log", "ab")  # noqa: SIM115 — handed to the child
    subprocess.Popen(
        [sys.executable, str(driver_path)],
        env=env, stdout=logf, stderr=logf,
        start_new_session=True, cwd=str(cwd),
    )
