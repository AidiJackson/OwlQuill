#!/usr/bin/env python3
"""S24T import — attach the 8 Summer LoRA v3 validation images to Summer's image
library as normal character images (kind=SCENE_ONLY), via the EXISTING ingestion path.

Behaviour parity: each local PNG is persisted with app.core.storage.save_image() (the
same function the live image generator uses — uploads to R2 under generated/<uuid>.png
in object-storage mode) and recorded as a CharacterImage row identical in shape to a
normally-generated scene image, so it appears in the library UI and is selectable like
any other image. Source provenance is stamped (metadata.source = "validation") and the
original filename is preserved (metadata.original_filename).

- Does NOT regenerate or alter the source files (they are read-only here).
- All-or-nothing: all 8 rows are staged, then a single commit. Any failure → rollback,
  no partial import.
- Duplicate guard: refuses to run if these filenames were already imported for Summer.

Run from backend/ (so the app env + DATABASE_URL are loaded):
    cd backend && python3 ../scripts/import_s24t_validation_to_library.py [--commit]
Without --commit it performs a dry run (uploads NOTHING, creates NO rows).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CHARACTER_ID = 60                  # Summer Fielding
VAL_DIR = Path(__file__).resolve().parent / "s24t_validation"
MANIFEST = VAL_DIR / "manifest_status.json"
PROVIDER = "runpod_realvisxl_summer_lora_v3"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="actually upload + write rows; otherwise dry-run")
    args = ap.parse_args()

    from app.core.database import SessionLocal
    from app.core.storage import save_image, file_path_to_url
    from app.models.character import Character
    from app.models.character_image import (
        CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum)

    manifest = json.loads(MANIFEST.read_text())
    records = sorted(manifest.get("images") or [], key=lambda r: r["index"])
    if len(records) != 8:
        print(f"FATAL: expected 8 images in manifest, found {len(records)}")
        return 1

    db = SessionLocal()
    try:
        char = db.get(Character, CHARACTER_ID)
        if char is None:
            print(f"FATAL: character {CHARACTER_ID} not found")
            return 1
        owner_id = char.owner_id
        print(f"[target] character={char.name!r} id={CHARACTER_ID} owner_id={owner_id} "
              f"commit={args.commit}")

        # Duplicate guard — refuse if any of these filenames already imported for Summer.
        existing = (db.query(CharacterImage)
                    .filter(CharacterImage.character_id == CHARACTER_ID)
                    .all())
        already = {((e.metadata_json or {}).get("original_filename"))
                   for e in existing
                   if (e.metadata_json or {}).get("source") == "validation"}
        want = {f"{r['label']}.png" for r in records}
        clash = want & already
        if clash:
            print(f"FATAL: these validation images already imported for Summer: "
                  f"{sorted(clash)}. Aborting to avoid duplicates.")
            return 1

        staged = []
        for r in records:
            fn = f"{r['label']}.png"
            local = VAL_DIR / fn
            png = local.read_bytes()              # read-only; originals untouched
            if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                print(f"FATAL: {fn} is not a valid PNG")
                db.rollback()
                return 1

            if args.commit:
                file_path = save_image(png)        # EXISTING ingestion path → R2
            else:
                file_path = f"(dry-run, not uploaded) {fn}"

            metadata = {
                "source": "validation",            # required provenance stamp
                "original_filename": fn,            # required: preserve original name
                "scene_only": True,
                "include_character": True,
                "character_id": CHARACTER_ID,
                "prompt": r["prompt"],
                "is_cover": False,
                "base_model": "RealVisXL_V4.0",
                "lora": "summer_lora_v3.safetensors",
                "trigger": "smmr_v3",
                "validation_run": manifest.get("run_id"),
                "import_sprint": "S24T",
                "r2_validation_url": r.get("url"),
            }
            img = CharacterImage(
                character_id=CHARACTER_ID,
                user_id=owner_id,
                kind=ImageKindEnum.SCENE_ONLY,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                provider=PROVIDER,
                prompt_summary=r["prompt"][:200],
                seed=str(r.get("seed")),
                metadata_json=metadata,
                file_path=file_path,
            )
            staged.append(img)
            print(f"  [{r['index']}] {fn:32s} seed={r.get('seed')} -> {file_path[:72]}")

        if not args.commit:
            print(f"[dry-run] staged {len(staged)} rows; nothing written. "
                  f"Re-run with --commit to import.")
            db.rollback()
            return 0

        db.add_all(staged)
        db.commit()
        ids = [img.id for img in staged]
        print(f"[committed] {len(ids)} CharacterImage rows: ids={ids}")
        for img in staged:
            print(f"    id={img.id} url={file_path_to_url(img.file_path)}")
        return 0
    except Exception as e:  # noqa: BLE001
        db.rollback()
        import traceback
        traceback.print_exc()
        print(f"FATAL: import failed, rolled back: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
