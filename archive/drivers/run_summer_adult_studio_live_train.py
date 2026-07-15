#!/usr/bin/env python3
"""FIRST LIVE Adult Studio training run — Summer Fielding (character_id=60, identity id=1).

Drives the NEW admin training workflow (admin route handlers) against the REAL
Replicate provider. Training ONLY: no generation, no inference, no RunPod, no ComfyUI,
no Canon Studio writes, no normal image-generator changes.

Flags are enabled IN-PROCESS for this run only (the persisted .env / live server config
is never touched) and restored to disabled in a finally block. Writes a JSON report.

Safety: hard cost ceiling $1.00 (expected ~$0.41). Only character_id=60 is trained.
"""
import json
import os
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.adult_identity import (  # noqa: E402
    AdultIdentityModel,
    AdultIdentityModelVersion,
    AdultIdentityTrainingJob,
)

CHARACTER_ID = 60
IDENTITY_ID = 1
EXPECTED_DEST = "aidijackson/ficshon-adult-1"
COST_CEILING = 1.00
POLL_INTERVAL_S = 20
POLL_TIMEOUT_S = 2700
REPORT = Path(__file__).resolve().parent / "summer_adult_studio_live_train_report.json"

rep = {"character_id": CHARACTER_ID, "identity_id": IDENTITY_ID,
       "expected_destination": EXPECTED_DEST, "expected_cost_usd": 0.41}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def write_report():
    REPORT.write_text(json.dumps(rep, indent=2))


# ── PRE-CHECK (no flags, no spend): confirm manifest images load ────────────────
def precheck(db):
    from app.services.adult_studio import build_training_pack
    model = db.query(AdultIdentityModel).filter(
        AdultIdentityModel.character_id == CHARACTER_ID).first()
    if model is None or model.id != IDENTITY_ID:
        raise SystemExit(f"FATAL: expected identity id={IDENTITY_ID} for character {CHARACTER_ID}")
    if model.status != "prepared":
        raise SystemExit(f"FATAL: identity status is {model.status!r}, expected 'prepared'")
    manifest = model.prepared_manifest_json or {}
    rep["prepared_fingerprint"] = model.canon_fingerprint
    zip_bytes, summary = build_training_pack(
        manifest, character_id=CHARACTER_ID,
        character_name=manifest.get("character_name", "Summer Fielding"))
    rep["precheck"] = {"image_count": summary["image_count"],
                       "skipped": summary["skipped"],
                       "zip_bytes": len(zip_bytes)}
    log(f"precheck: {summary['image_count']} images load, zip={len(zip_bytes)} bytes, "
        f"skipped={len(summary['skipped'])}")
    if summary["image_count"] == 0:
        raise SystemExit("FATAL: 0 trainable images — aborting before any spend")
    return model


def main():
    db = SessionLocal()
    admin = types.SimpleNamespace(id=0, email="runbot@local", is_admin=True)
    try:
        # 0) pre-check (no flags changed yet, no spend)
        precheck(db)

        # 1) enable the three settings IN-PROCESS for this run only
        prev = (settings.ADULT_STUDIO_TRAINING_ENABLED,
                settings.ADULT_STUDIO_PROVIDER,
                settings.ADULT_STUDIO_REPLICATE_OWNER)
        settings.ADULT_STUDIO_TRAINING_ENABLED = True
        settings.ADULT_STUDIO_PROVIDER = "replicate"
        settings.ADULT_STUDIO_REPLICATE_OWNER = "aidijackson"
        if not settings.REPLICATE_API_TOKEN:
            settings.REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
        log(f"flags enabled in-process (was {prev})")

        from app.api.routes.adult_studio_admin import (
            train_adult_studio_identity, poll_adult_studio_training_job)

        try:
            # 2) submit through the admin workflow
            t0 = time.time()
            status = train_adult_studio_identity(CHARACTER_ID, admin=admin, db=db)
            # 3) record provider_job_id
            rep["submit"] = status.model_dump()
            rep["provider_job_id"] = status.external_job_id
            log(f"submitted: job_id={status.job_id} provider_job_id={status.external_job_id} "
                f"state={status.state} identity={status.identity_status}")
            if status.external_job_id is None:
                raise SystemExit("FATAL: no provider_job_id returned (submit did not reach provider)")

            # 4) poll until completed/failed
            job_id = status.job_id
            last = status
            while True:
                if time.time() - t0 > POLL_TIMEOUT_S:
                    rep["error"] = "poll timeout"
                    raise SystemExit("FATAL: poll timed out")
                time.sleep(POLL_INTERVAL_S)
                last = poll_adult_studio_training_job(job_id, admin=admin, db=db)
                cost = last.cost_usd
                log(f"poll: state={last.state} identity={last.identity_status} cost={cost}")
                if cost is not None and cost > COST_CEILING:
                    rep["error"] = f"cost ${cost} exceeded ceiling ${COST_CEILING}"
                    raise SystemExit(f"FATAL: cost ceiling exceeded ({cost})")
                if last.state in ("completed", "failed", "canceled"):
                    break
            rep["runtime_s"] = round(time.time() - t0, 1)
            rep["final"] = last.model_dump()

            # 5) verify on completion
            if last.state == "completed":
                db.expire_all()
                model = db.get(AdultIdentityModel, IDENTITY_ID)
                ver = db.get(AdultIdentityModelVersion, last.version_id) if last.version_id else None
                job = db.get(AdultIdentityTrainingJob, job_id)
                checks = {
                    "job_completed": job.state == "completed",
                    "identity_ready": model.status == "ready",
                    "version_created": ver is not None,
                    "active_version_id_set": model.active_version_id == last.version_id,
                    "artifact_uri_saved": bool(ver and ver.lora_weights_uri),
                    "cost_recorded": job.cost_usd is not None,
                    "fingerprint_matches": bool(ver and ver.canon_fingerprint == rep.get("prepared_fingerprint")),
                }
                rep["verification"] = checks
                rep["artifact_uri"] = ver.lora_weights_uri if ver else None
                rep["final_cost_usd"] = job.cost_usd
                log(f"verification: {checks}")
                log(f"artifact_uri={rep['artifact_uri']} cost=${job.cost_usd}")
                rep["result"] = "SUCCESS" if all(checks.values()) else "COMPLETED_WITH_GAPS"
            else:
                rep["result"] = f"TRAINING_{last.state.upper()}"
                rep["error"] = last.error
                log(f"training ended non-success: state={last.state} error={last.error}")

        finally:
            # 6) restore settings to disabled (in-process)
            settings.ADULT_STUDIO_TRAINING_ENABLED = False
            settings.ADULT_STUDIO_PROVIDER = "disabled"
            settings.ADULT_STUDIO_REPLICATE_OWNER = ""
            # 7) confirm disabled
            rep["flags_after"] = {
                "ADULT_STUDIO_TRAINING_ENABLED": settings.ADULT_STUDIO_TRAINING_ENABLED,
                "ADULT_STUDIO_PROVIDER": settings.ADULT_STUDIO_PROVIDER,
                "ADULT_STUDIO_REPLICATE_OWNER": settings.ADULT_STUDIO_REPLICATE_OWNER,
            }
            log(f"flags restored: {rep['flags_after']}")
    except SystemExit as e:
        rep.setdefault("result", "ABORTED")
        rep.setdefault("error", str(e))
        log(f"ABORT: {e}")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        rep["result"] = "EXCEPTION"
        rep["error"] = repr(e)
    finally:
        db.close()
        write_report()
        log("REPORT:\n" + json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
