"""Sprint E2 validation — Grok editor provider.

Runs the exact route logic (same service + storage + persistence calls as
POST /editor/generate with provider=grok) against the live DB:

  Primary:   source 1778 (Summer black dress) ->
             "Summer in a different scene on the beach wearing a blue bikini."
  Secondary: source 1778 ->
             "Summer in black lace lingerie sitting on a bed."

Both at strength 0.25 (recorded; grok has no API-level strength control).
Saves outputs through save_image, records CharacterImage rows with E2
metadata, and writes local copies for visual review.
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

SOURCE_IMAGE_ID = 1778  # "Summer in a stunning sleek strapless black dress"
CHARACTER_ID = 60       # Summer Fielding
STRENGTH = 0.25
SCENARIOS = [
    ("bikini_beach", "Summer in a different scene on the beach wearing a blue bikini."),
    ("lingerie_bed", "Summer in black lace lingerie sitting on a bed."),
]
OUT_DIR = Path(__file__).resolve().parent / "editor_e2_validation"


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    from app.core.database import SessionLocal
    from app.core.storage import file_path_to_url, load_image_bytes, save_image
    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )
    from app.services.editor_studio import clamp_strength, get_editor

    db = SessionLocal()
    results = []
    try:
        src = db.query(CharacterImage).filter(CharacterImage.id == SOURCE_IMAGE_ID).first()
        assert src is not None and src.character_id == CHARACTER_ID, "source image not found"
        src_bytes = load_image_bytes(src.file_path)
        (OUT_DIR / "source_1778.png").write_bytes(src_bytes)
        print(f"source: id={src.id} bytes={len(src_bytes)}")

        editor = get_editor("grok")
        strength = clamp_strength(STRENGTH)

        for key, prompt in SCENARIOS:
            print(f"\n=== {key}: {prompt!r}")
            try:
                png = editor.edit(prompt=prompt, source_images=[src_bytes], strength=strength)
            except (ValueError, RuntimeError) as exc:
                print(f"{key} FAILED: {str(exc)[:300]}")
                results.append({"scenario": key, "success": False, "error": str(exc)[:300]})
                continue

            (OUT_DIR / f"output_{key}.png").write_bytes(png)
            file_path = save_image(png)
            img = CharacterImage(
                character_id=CHARACTER_ID,
                user_id=src.user_id or 2,
                kind=ImageKindEnum.SCENE_ONLY,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                provider="grok",
                prompt_summary=prompt[:200],
                metadata_json={
                    "editor_generated": True,
                    "editor_version": editor.editor_version,
                    "provider": "grok",
                    "prompt": prompt,
                    "strength": strength,
                    "input_fidelity": None,
                    "source_image_ids": [src.id],
                    "uploaded_source_count": 0,
                    "validation_run": "sprint_e2",
                },
                file_path=file_path,
            )
            db.add(img)
            db.commit()
            db.refresh(img)
            print(f"{key} OK: saved image id={img.id} bytes={len(png)}")
            results.append({
                "scenario": key,
                "success": True,
                "saved_image_id": img.id,
                "image_url": file_path_to_url(file_path),
                "prompt": prompt,
                "strength": strength,
            })
    finally:
        db.close()

    print("\n" + json.dumps(results, indent=2))
    (OUT_DIR / "validation_result.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
