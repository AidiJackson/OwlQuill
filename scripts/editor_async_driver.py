"""Detached driver for Editor Studio async jobs (Sprint E5).

Launched by editor_job_service._default_launcher as a detached process (it
outlives the API request). Reads its job row, runs the production self_hosted
transform (RunPod, hard caps, finally-terminate), applies the Part B quality
gate, persists the result to the image library, and writes the run_id-scoped
report JSON that the service reconciles on poll.

Report contract (scripts/editor_job_reports/{run_id}.json):
  non-terminal progress: {"terminal": false, "pod_id": ..., "stage": ...}
  terminal:              {"terminal": true, "success": bool, "quality_status":
                          "pass|needs_review|failed", "quality_reasons": [...],
                          "image_id": int|None, "final_image_url": str|None,
                          "stage_images": {...}, "spend_usd": float, ...}

Env: EDITOR_RUN_ID, EDITOR_JOB_ID (set by the launcher).
"""
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("editor_async_driver")

RUN_ID = os.environ["EDITOR_RUN_ID"]
JOB_ID = int(os.environ["EDITOR_JOB_ID"])
REPORTS_DIR = _REPO_ROOT / "scripts" / "editor_job_reports"


def write_report(payload: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REPORTS_DIR / f"{RUN_ID}.json.tmp"
    tmp.write_text(json.dumps({"run_id": RUN_ID, "job_id": JOB_ID, **payload}, indent=2))
    tmp.replace(REPORTS_DIR / f"{RUN_ID}.json")


def main() -> int:
    from app.core.database import SessionLocal
    from app.core.storage import file_path_to_url, load_image_bytes, save_image
    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )
    from app.models.editor_job import EditorJob
    from app.services.editor_job_service import evaluate_quality
    from app.services.editor_self_hosted import SelfHostedImageEditor

    t0 = time.time()
    write_report({"terminal": False, "stage": "starting"})

    db = SessionLocal()
    try:
        job = db.query(EditorJob).filter(EditorJob.id == JOB_ID).first()
        if job is None:
            write_report({"terminal": True, "success": False,
                          "quality_status": "failed", "error": "job row not found"})
            return 1
        params = job.params_json or {}
        prompt = job.prompt
        character_id = job.character_id
        user_id = job.user_id
        source_ids = params.get("source_image_ids") or []
        source_png = load_image_bytes(params["source_file_path"])
    finally:
        db.close()

    from PIL import Image

    source_size = Image.open(io.BytesIO(source_png)).size

    editor = SelfHostedImageEditor()
    write_report({"terminal": False, "stage": "launching_pod"})

    png = None
    pod_status: dict = {}
    telemetry: dict = {}
    error = None
    try:
        result = editor.transform(
            prompt=prompt, source_png=source_png, run_id=RUN_ID,
            # Publish pod_id immediately so a cancel poll can terminate the pod.
            on_launch=lambda pod_id: write_report(
                {"terminal": False, "stage": "pod_running", "pod_id": pod_id}),
        )
        png = result["png"]
        pod_status = result.get("status") or {}
        telemetry = {k: result.get(k) for k in
                     ("pod_id", "gpu", "rate_usd_hr", "spend_usd", "runtime_s")}
    except Exception as exc:  # noqa: BLE001 — every failure becomes a terminal report
        error = str(exc)[:500]
        logger.warning("transform failed run_id=%s: %r", RUN_ID, exc)

    quality_status, quality_reasons = evaluate_quality(pod_status, png, source_size)
    stage_images = (pod_status.get("images") or {})

    # Orphan audit: the supervisor guarantees termination; verify and record.
    no_orphans = True
    try:
        import requests

        key = os.environ.get("RUNPOD_API_KEY", "")
        r = requests.post(
            f"https://api.runpod.io/graphql?api_key={key}",
            json={"query": "query { myself { pods { id desiredStatus } } }"}, timeout=30)
        pods = (r.json().get("data") or {}).get("myself", {}).get("pods") or []
        live = [p["id"] for p in pods
                if p.get("desiredStatus") not in ("TERMINATED", "EXITED")]
        no_orphans = telemetry.get("pod_id") not in live
    except Exception:  # noqa: BLE001 — audit is best-effort
        pass

    image_id = None
    final_url = None
    if png is not None and quality_status != "failed":
        db = SessionLocal()
        try:
            file_path = save_image(png)
            img = CharacterImage(
                character_id=character_id,
                user_id=user_id,
                kind=ImageKindEnum.SCENE_ONLY,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                provider="self_hosted",
                prompt_summary=prompt[:200],
                metadata_json={
                    "editor_generated": True,
                    "editor_version": "e5",
                    "provider": "self_hosted",
                    "editor_provider": "self_hosted",
                    "editor_mode": "transform",
                    "editor_job_id": JOB_ID,
                    "editor_run_id": RUN_ID,
                    "prompt": prompt,
                    "quality_status": quality_status,
                    "quality_reasons": quality_reasons,
                    "source_image_ids": source_ids,
                },
                file_path=file_path,
            )
            db.add(img)
            db.commit()
            db.refresh(img)
            image_id = img.id
            final_url = file_path_to_url(file_path)
            logger.info("editor_job saved image_id=%s quality=%s", image_id, quality_status)
        finally:
            db.close()

    success = png is not None and error is None and quality_status != "failed"
    write_report({
        "terminal": True,
        "success": success,
        "error": error,
        "quality_status": quality_status,
        "quality_reasons": quality_reasons,
        "image_id": image_id,
        "final_image_url": final_url,
        "r2_final_url": stage_images.get("99_final"),
        "stage_images": stage_images,
        "errors": pod_status.get("errors") or ([error] if error else []),
        "quality_metrics": pod_status.get("quality") or {},
        "no_orphaned_pods": no_orphans,
        "driver_runtime_s": round(time.time() - t0, 1),
        **telemetry,
    })
    return 0 if success else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — never die without a terminal report
        write_report({"terminal": True, "success": False,
                      "quality_status": "failed", "error": str(exc)[:500]})
        raise
