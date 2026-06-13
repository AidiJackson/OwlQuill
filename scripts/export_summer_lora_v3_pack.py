#!/usr/bin/env python3
"""S24C — export a clean kohya-compatible Summer Adult LoRA v3 training pack.

Reads Summer's LOCKED Canon Identity Pack (character_id=60, read-only), builds the
upgraded manifest (now incl. face expression + body map + final identity card), and
packages images + per-image factual captions (trigger token 'smmr_v3') + manifest.json
into a ZIP. NO training, NO generation — packaging only.

Run from backend/:  python ../scripts/export_summer_lora_v3_pack.py
Writes:  scripts/summer_lora_v3_pack.zip  and  scripts/summer_lora_v3_pack_report.json
"""
import io
import json
import sys
import zipfile
from pathlib import Path

CHARACTER_ID = 60
TRIGGER = "smmr_v3"
IDENTITY_TRAITS = "blonde hair, blue eyes"  # user-stated (canon stores no hair/eye text)

# v3 required roles (internal role names as emitted by build_manifest).
REQUIRED_ROLES = [
    "face_front", "face_left_3q", "face_right_3q", "expression",
    "body_front", "body_left", "body_right", "body_back",
    "body_map", "final_card",
]
HERE = Path(__file__).resolve().parent
ZIP_PATH = HERE / "summer_lora_v3_pack.zip"
REPORT_PATH = HERE / "summer_lora_v3_pack_report.json"


def main() -> int:
    sys.path.insert(0, str(HERE.parent / "backend"))
    from app.core.database import SessionLocal
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.services import adult_studio as svc

    db = SessionLocal()
    try:
        canon = (
            db.query(CharacterIdentityCanon)
            .filter(CharacterIdentityCanon.character_id == CHARACTER_ID)
            .first()
        )
        if not canon or not (canon.face_locked and canon.body_locked):
            print("FATAL: Summer canon (character 60) is missing or not locked.")
            return 1

        manifest = svc.build_manifest(canon)
        zip_bytes, summary = svc.build_training_pack(
            manifest,
            character_id=CHARACTER_ID,
            character_name="Summer Fielding",
            trigger=TRIGGER,
            identity_traits=IDENTITY_TRAITS,
        )
    finally:
        db.close()

    ZIP_PATH.write_bytes(zip_bytes)

    # Roles actually packed (derive from manifest refs minus any skipped on load).
    skipped_roles = {s["role"] for s in summary["skipped"]}
    manifest_roles = [r["role"] for r in manifest["refs"]]
    packed_roles = [r for r in manifest_roles if r not in skipped_roles]
    mark_roles = [r for r in packed_roles if r.startswith("mark:")]
    missing_required = [r for r in REQUIRED_ROLES if r not in packed_roles]

    # Read back the captions from the ZIP for the report (one source of truth).
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    captions = json.loads(zf.read("captions.json"))

    report = {
        "sprint": "S24C",
        "character_id": CHARACTER_ID,
        "trigger_token": TRIGGER,
        "identity_traits": IDENTITY_TRAITS,
        "zip_path": str(ZIP_PATH.relative_to(HERE.parent)),
        "total_image_count": summary["image_count"],
        "packed_roles": packed_roles,
        "mark_roles": mark_roles,
        "missing_required_roles": missing_required,
        "skipped_refs": summary["skipped"],
        "filenames": summary["filenames"],
        "captions": captions,
        "marks_truth": [
            {"label": m["label"], "region": m["body_region"], "side": m["side"]}
            for m in manifest.get("marks", [])
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # ── Print export report ────────────────────────────────────────────────
    print("=" * 64)
    print("S24C SUMMER LoRA v3 — TRAINING PACK EXPORT REPORT")
    print("=" * 64)
    print(f"trigger token        : {TRIGGER}")
    print(f"identity traits      : {IDENTITY_TRAITS}")
    print(f"total image count    : {summary['image_count']}")
    print(f"zip                  : {ZIP_PATH.relative_to(HERE.parent)} ({len(zip_bytes)} bytes)")
    print(f"\npacked roles ({len(packed_roles)}):")
    for r in packed_roles:
        print(f"  - {r}")
    print(f"\nmissing required roles: {missing_required or 'NONE'}")
    if summary["skipped"]:
        print(f"\nskipped refs (load failed): {summary['skipped']}")
    print("\nmark truth (canon sides):")
    for m in manifest.get("marks", []):
        print(f"  - {m['label']} -> region={m['body_region']} side={m['side']}")
    print("\ncaptions:")
    for fname, cap in captions.items():
        print(f"  {fname:28s} {cap}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
