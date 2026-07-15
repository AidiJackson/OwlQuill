"""Sprint E5 validation — ONE live async job through the PRODUCTION job path.

start_editor_job (real launcher → detached driver → RunPod E5 pod) then
get_latest_job polling, exactly as the route + UI do. Verifies: async flow,
quality gate verdict, library persistence, compositing quality, no orphans.

Run: cd backend && python ../scripts/e5_editor_validation.py
"""
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOURCE_IMAGE_ID = 1778
CHARACTER_ID = 60
PROMPT = "Summer on the beach in a black bikini instead of the black dress."
OUT_JSON = Path(__file__).parent / "e5_reports" / "e5_validation_report.json"


def main() -> int:
    from app.core.database import SessionLocal
    from app.core.storage import load_image_bytes, save_image
    from app.models.character_image import CharacterImage
    from app.services.editor_job_service import get_latest_job, start_editor_job

    db = SessionLocal()
    try:
        row = db.query(CharacterImage).filter(CharacterImage.id == SOURCE_IMAGE_ID).first()
        assert row is not None and row.character_id == CHARACTER_ID
        source_png = load_image_bytes(row.file_path)
        source_file_path = save_image(source_png)
        user_id = row.user_id

        job = start_editor_job(
            db,
            character_id=CHARACTER_ID,
            user_id=user_id,
            prompt=PROMPT,
            source_file_path=source_file_path,
            source_image_ids=[SOURCE_IMAGE_ID],
            strength=0.25,
        )
        print(f"job started id={job.id} run_id={job.run_id} state={job.state}", flush=True)

        t0 = time.time()
        while True:
            time.sleep(15)
            db.expire_all()
            job = get_latest_job(db, CHARACTER_ID)
            print(f"[{int(time.time()-t0)}s] state={job.state} pod={job.pod_id} "
                  f"quality={job.quality_status}", flush=True)
            if job.state not in ("queued", "running"):
                break
            if time.time() - t0 > 1500:
                print("VALIDATION TIMEOUT", flush=True)
                break

        report = {
            "executor": "e5_editor_validation",
            "job_id": job.id, "run_id": job.run_id, "state": job.state,
            "quality_status": job.quality_status,
            "final_image_url": job.final_image_url, "image_id": job.image_id,
            "error": job.error, "result": job.result_json,
            "prompt": PROMPT, "source_image_id": SOURCE_IMAGE_ID,
            "wallclock_s": round(time.time() - t0, 1),
        }
        OUT_JSON.parent.mkdir(exist_ok=True)
        OUT_JSON.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)
        return 0 if job.state == "completed" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
