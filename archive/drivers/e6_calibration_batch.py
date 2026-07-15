"""Sprint E6 — self-hosted editor quality calibration batch.

Runs N prompts sequentially through the PRODUCTION async job path
(start_editor_job → detached driver → RunPod E5 pod → quality gate),
same Summer source image each time, and collects per-run metrics into
scripts/e6_reports/e6_batch_results.json. Downloads each final image to
scripts/e6_reports/<n>_final.png for visual inspection.

Sequential by construction: the per-character singleton blocks parallel jobs.

Usage: cd backend && python ../scripts/e6_calibration_batch.py [indices...]
       (no args = all prompts; e.g. `1 4` reruns prompts 1 and 4 only)
"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

logging.basicConfig(level=logging.WARNING)

SOURCE_IMAGE_ID = 1778
CHARACTER_ID = 60
REPORT_DIR = Path(__file__).parent / "e6_reports"

PROMPTS = [
    "Summer on the beach in a black bikini instead of the black dress.",
    "Summer on the beach in a blue bikini instead of the black dress.",
    "Summer beside a luxury hotel pool in a red bikini instead of the black dress.",
    "Summer sitting on a bed in black lace lingerie instead of the black dress.",
    "Summer walking along a sunny beach boardwalk wearing a white summer dress "
    "instead of the black dress.",
]


def run_one(db, source_file_path: str, user_id: int, idx: int, prompt: str,
            tag: str) -> dict:
    import urllib.request

    from app.services.editor_job_service import get_latest_job, start_editor_job

    job = start_editor_job(
        db, character_id=CHARACTER_ID, user_id=user_id, prompt=prompt,
        source_file_path=source_file_path, source_image_ids=[SOURCE_IMAGE_ID],
        strength=0.25)
    print(f"[{idx}] job={job.id} run={job.run_id} started: {prompt[:60]}", flush=True)

    t0 = time.time()
    while True:
        time.sleep(15)
        db.expire_all()
        job = get_latest_job(db, CHARACTER_ID)
        elapsed = int(time.time() - t0)
        print(f"[{idx}] {elapsed}s state={job.state} q={job.quality_status}", flush=True)
        if job.state not in ("queued", "running"):
            break
        if elapsed > 1500:
            break

    result = job.result_json or {}
    metrics = (result or {}).get("quality_reasons")
    row = {
        "idx": idx, "prompt": prompt, "job_id": job.id, "run_id": job.run_id,
        "state": job.state, "quality_status": job.quality_status,
        "quality_reasons": result.get("quality_reasons"),
        "spend_usd": result.get("spend_usd"),
        "runtime_s": result.get("runtime_s"),
        "image_id": job.image_id, "error": job.error,
        "stage_images": result.get("stage_images"),
        "r2_final_url": result.get("r2_final_url"),
        "wallclock_s": round(time.time() - t0, 1),
    }
    # Pull pod quality metrics from the driver report for exact numbers.
    rep_path = Path(__file__).parent / "editor_job_reports" / f"{job.run_id}.json"
    if rep_path.exists():
        rep = json.loads(rep_path.read_text())
        row["quality_metrics"] = rep.get("quality_metrics")
        row["no_orphaned_pods"] = rep.get("no_orphaned_pods")

    url = result.get("r2_final_url")
    if url:
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                (REPORT_DIR / f"{tag}{idx}_final.png").write_bytes(r.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx}] final download failed: {exc}", flush=True)
    return row


def main() -> int:
    from app.core.database import SessionLocal
    from app.core.storage import load_image_bytes, save_image
    from app.models.character_image import CharacterImage

    indices = [int(a) for a in sys.argv[1:]] or list(range(1, len(PROMPTS) + 1))
    tag = "" if len(indices) == len(PROMPTS) else "retry_"
    REPORT_DIR.mkdir(exist_ok=True)

    db = SessionLocal()
    try:
        src = db.query(CharacterImage).filter(CharacterImage.id == SOURCE_IMAGE_ID).first()
        source_png = load_image_bytes(src.file_path)
        source_file_path = save_image(source_png)
        user_id = src.user_id

        rows = []
        for idx in indices:
            row = run_one(db, source_file_path, user_id, idx, PROMPTS[idx - 1], tag)
            rows.append(row)
            out = REPORT_DIR / f"e6_batch_results{'_retry' if tag else ''}.json"
            out.write_text(json.dumps(rows, indent=2))
            print(f"[{idx}] -> {row['state']}/{row['quality_status']} "
                  f"metrics={row.get('quality_metrics')}", flush=True)
        print("BATCH_DONE", flush=True)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
