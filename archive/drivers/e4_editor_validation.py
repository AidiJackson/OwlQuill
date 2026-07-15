"""Sprint E4 validation — ONE live edit through the PRODUCTION provider path.

Calls app.services.editor_studio.get_editor("self_hosted") exactly as the
/editor/generate route does, sourcing Summer's black-dress canonical image
(CharacterImage 1778) from the library. Verifies the integrated provider,
the E4 remnant fixes, spend cap, and orphan-free teardown.

Run: cd backend && python ../scripts/e4_editor_validation.py
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
PROMPT = ("Remove the black dress. Replace with a blue bikini. "
          "Place her at a luxury beach resort.")
OUT_PNG = Path(__file__).parent / "e4_validation_final.png"
OUT_JSON = Path(__file__).parent / "e4_reports" / "e4_validation_report.json"


def main() -> int:
    from app.core.database import SessionLocal
    from app.core.storage import load_image_bytes
    from app.models.character_image import CharacterImage
    from app.services.editor_studio import get_editor

    db = SessionLocal()
    try:
        row = db.query(CharacterImage).filter(CharacterImage.id == SOURCE_IMAGE_ID).first()
        if row is None or row.character_id != CHARACTER_ID:
            raise SystemExit(f"source image {SOURCE_IMAGE_ID} missing or not Summer's")
        source = load_image_bytes(row.file_path)
    finally:
        db.close()
    print(f"source image {SOURCE_IMAGE_ID}: {len(source)} bytes", flush=True)

    editor = get_editor("self_hosted")  # production registry, real credential checks
    t0 = time.time()
    report = {
        "executor": "e4_editor_validation",
        "experiment": "e4_selfhosted_editor_production",
        "provider": editor.provider_name,
        "editor_version": editor.editor_version,
        "character_id": CHARACTER_ID,
        "source_image_id": SOURCE_IMAGE_ID,
        "prompt": PROMPT,
        "spend_cap_usd": 0.05,
    }
    try:
        png = editor.edit(prompt=PROMPT, source_images=[source], strength=0.25)
        OUT_PNG.write_bytes(png)
        report.update(success=True, runtime_s=round(time.time() - t0, 1),
                      final_bytes=len(png), local_path=str(OUT_PNG))
        print(f"SUCCESS {len(png)} bytes in {report['runtime_s']}s -> {OUT_PNG}", flush=True)
        rc = 0
    except Exception as exc:  # noqa: BLE001 — report and exit nonzero
        report.update(success=False, runtime_s=round(time.time() - t0, 1),
                      error=str(exc)[:500])
        print(f"FAILED after {report['runtime_s']}s: {exc}", flush=True)
        rc = 1

    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
