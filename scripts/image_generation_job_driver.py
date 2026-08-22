"""Detached driver for one founder image-generation job.

Launched by image_generation_job_service._default_launcher with
IMAGE_GENERATION_JOB_ID in the environment. Runs in its own session/process
group so it survives a uvicorn dev reload; it does NOT survive a container
restart — the poll-time stale-job reconciler in the service covers that case.

All real work happens in run_image_generation_job (status/stage/result are
written directly to the job row). This wrapper only bootstraps imports and
guarantees the process exits cleanly.
"""
import os
import sys
from pathlib import Path

# Repo layout: <repo>/scripts/ → the app package lives in <repo>/backend.
_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))


def main() -> int:
    job_id_raw = os.environ.get("IMAGE_GENERATION_JOB_ID", "")
    try:
        job_id = int(job_id_raw)
    except ValueError:
        print(
            f"image_generation_job_driver: invalid IMAGE_GENERATION_JOB_ID={job_id_raw!r}",
            file=sys.stderr,
        )
        return 2

    from app.services.image_generation_job_service import run_image_generation_job

    run_image_generation_job(job_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
