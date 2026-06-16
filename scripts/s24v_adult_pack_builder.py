#!/usr/bin/env python3
"""S24V — Adult LoRA v4 training-pack *candidate* builder for Summer Fielding.

Reads Summer's LOCKED Canon Identity Pack (character_id=60, read-only) and uses
Gemini (Google AI native image gen, multi-reference / identity-anchored) to
GENERATE a fresh set of 18-24 candidate LoRA training images covering a fixed
set of pack roles. Each candidate is written to disk with a factual caption and
recorded in manifest.json as `pending_review`.

HARD BOUNDARIES (S24V):
  - NO LoRA training. This only generates + stages candidate images.
  - NO app wiring. Standalone script; canon is read-only.
  - NO NSFW / explicit generation. Adult-safe only:
    swimwear / underwear / oversized-shirt / reference-body framing.
  - Final pack export (dropping rejected images) is a SEPARATE, USER-APPROVED
    step. This script stops after staging candidates and never exports the pack.

Outputs (scripts/summer_lora_v4_pack_candidates/):
  images/<role>.png         generated candidate image
  captions/<role>.txt       kohya-style sidecar caption (mirrors manifest)
  manifest.json             per-image role/caption/status (pending_review)

Run from repo root:  python scripts/s24v_adult_pack_builder.py
Optional:            --only role1,role2   (regenerate a subset)
                     --dry-run            (print plan, generate nothing)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BACKEND = REPO / "backend"
OUT_DIR = HERE / "summer_lora_v4_pack_candidates"
IMG_DIR = OUT_DIR / "images"
CAP_DIR = OUT_DIR / "captions"
MANIFEST_PATH = OUT_DIR / "manifest.json"

# S24X — approved-only export target (built from the reviewed candidate manifest).
APPROVED_DIR = HERE / "summer_lora_v4_approved_pack"
APPROVED_IMG_DIR = APPROVED_DIR / "images"
APPROVED_CAP_DIR = APPROVED_DIR / "captions"
APPROVED_ZIP = APPROVED_DIR / "summer_lora_v4_approved_pack.zip"

CHARACTER_ID = 60
CHARACTER_NAME = "Summer Fielding"
TRIGGER = "smmr_v4"
IDENTITY_TRAITS = "blonde hair, blue eyes"  # canon stores no hair/eye text; user-stated
RETRIES = 2  # per-image generation attempts on transient provider errors

# ── Pack roles ─────────────────────────────────────────────────────────────
# Each role: scene phrase fed to the adult prompt builder, the factual caption
# tail (trigger prefix added automatically), and which canon anchor roles to
# send to Gemini as identity references. 19 roles total (in the 18-24 band).
#
# group "face"  → portrait framing, face anchors
# group "body"  → full/torso reference-body framing, body anchors (+ face seed)
# group "scene" → clothed adult-safe scenes, body+face anchors
# group "tat"   → tattoo detail crops, the specific mark crop + supporting views
FACE_ANCHORS = ["face_front", "face_left_3q", "face_right_3q", "expression", "final_card"]
BODY_ANCHORS = ["body_front", "body_left", "body_right", "body_back", "final_card", "face_front"]

ROLES: list[dict] = [
    # ── faces ──
    {"role": "face_front", "group": "face",
     "scene": "front-facing head-and-shoulders portrait, neutral expression, looking straight at camera, soft even studio lighting, plain neutral background",
     "caption": "front face portrait, neutral expression"},
    {"role": "face_left_3q", "group": "face",
     # Narrower anchor set: stacking multiple tight face crops here triggers
     # Gemini IMAGE_RECITATION refusals; face_front + expression + body_front
     # locks identity without provoking it.
     "anchors": ["face_front", "expression", "body_front"],
     "scene": "head and shoulders portrait, face at a left three-quarter angle, subtle natural expression, soft daylight, clean studio background",
     "caption": "left three-quarter face view"},
    {"role": "face_right_3q", "group": "face",
     "scene": "head-and-shoulders portrait turned to a right three-quarter angle, soft studio lighting, plain neutral background",
     "caption": "right three-quarter face view"},
    {"role": "face_soft_smile", "group": "face",
     "scene": "head-and-shoulders portrait, gentle natural soft smile, looking at camera, warm soft studio lighting, plain background",
     "caption": "soft smiling face portrait"},
    {"role": "face_profile", "group": "face",
     "scene": "head-and-shoulders pure side-profile portrait facing left, soft studio lighting, plain neutral background",
     "caption": "side profile face view"},
    # ── reference body ──
    {"role": "body_front", "group": "body",
     "scene": "full body front view, standing straight, arms relaxed at sides so both arms are fully visible, fitted swimwear, plain neutral studio background",
     "caption": "full body front view, slim body, fitted swimwear, butterfly floral sleeve tattoo on right upper arm, black-and-white ballerina tattoo on left forearm"},
    {"role": "body_left", "group": "body",
     "scene": "full body left side view, standing straight, arms relaxed at sides, fitted swimwear, plain neutral studio background",
     "caption": "full body left side view, slim body, fitted swimwear"},
    {"role": "body_right", "group": "body",
     "scene": "full body right side view, standing straight, arms relaxed at sides, fitted swimwear, plain neutral studio background",
     "caption": "full body right side view, slim body, fitted swimwear"},
    {"role": "body_back", "group": "body",
     "scene": "full body back view, standing straight, arms relaxed at sides, fitted swimwear, plain neutral studio background",
     "caption": "full body back view, slim body, fitted swimwear"},
    {"role": "torso_front", "group": "body",
     "scene": "torso framing from hips to head, front view, fitted swimwear, arms relaxed, plain neutral studio background",
     "caption": "torso front view, slim body, fitted swimwear"},
    {"role": "torso_side", "group": "body",
     "scene": "torso framing from hips to head, left side view, fitted swimwear, arms relaxed, plain neutral studio background",
     "caption": "torso side view, slim body, fitted swimwear"},
    # ── adult-safe scenes ──
    {"role": "standing_casual", "group": "scene",
     "scene": "full body standing in a relaxed natural pose, casual everyday outfit (jeans and a fitted t-shirt), soft natural daylight, simple indoor background",
     "caption": "standing, casual outfit"},
    {"role": "seated_casual", "group": "scene",
     "scene": "seated on a plain stool in a relaxed pose, casual everyday outfit, soft natural daylight, simple background",
     "caption": "seated, casual outfit"},
    {"role": "beach_full_body", "group": "scene",
     "scene": "full body standing on a sunny sandy beach, fitted swimwear, bright natural daylight, soft-focus ocean and sky background",
     "caption": "full body on beach, swimwear"},
    {"role": "bedroom_oversized_shirt", "group": "scene",
     "scene": "full body standing in a softly-lit bedroom wearing an oversized buttoned shirt, tasteful relaxed pose, warm ambient light",
     "caption": "bedroom, oversized shirt"},
    {"role": "formal_full_body", "group": "scene",
     "scene": "full length full body in an elegant formal floor-length evening dress, poised stance, soft studio lighting",
     "caption": "formal full body, evening dress"},
    {"role": "cinematic_rain", "group": "scene",
     "scene": "full body cinematic portrait standing on a wet city street at night in light rain, wearing a stylish jacket, moody neon reflections, shallow depth of field",
     "caption": "cinematic rain, full body, jacket"},
    # ── tattoo detail crops ──
    {"role": "tattoo_right_upper_arm_detail", "group": "tat",
     "scene": "extreme close-up detail crop of the RIGHT UPPER ARM showing the butterfly floral sleeve tattoo, natural skin texture, sharp focus, even lighting",
     "caption": "butterfly floral sleeve tattoo right upper arm closeup",
     "anchors": ["mark:Right upper arm", "body_front", "body_right", "face_front"]},
    {"role": "tattoo_left_forearm_detail", "group": "tat",
     "scene": "extreme close-up detail crop of the LEFT FOREARM showing the black-and-white ballerina tattoo, natural skin texture, sharp focus, even lighting",
     "caption": "black-and-white ballerina tattoo left forearm closeup",
     "anchors": ["mark:Left forearm", "body_front", "body_left", "face_front"]},
]


def _anchor_roles(role_def: dict) -> list[str]:
    if role_def.get("anchors"):
        return role_def["anchors"]
    return FACE_ANCHORS if role_def["group"] == "face" else BODY_ANCHORS


# ── S24X: approved-only pack export ─────────────────────────────────────────
#
# Reads the reviewed candidate manifest and packages ONLY approved candidates
# into a clean, self-contained training pack. NO generation, NO training, NO DB.
# Rejected/failed candidates are excluded. Trigger token is preserved (smmr_v4).


def export_approved_pack() -> int:
    if not MANIFEST_PATH.exists():
        print(f"FATAL: candidate manifest not found at {MANIFEST_PATH}")
        print("Run the candidate builder first (no --export-approved).")
        return 1

    candidate_manifest = json.loads(MANIFEST_PATH.read_text())
    images = candidate_manifest.get("images", [])
    approved = [e for e in images if e.get("status") == "approved"]
    rejected = [e for e in images if e.get("status") == "rejected"]
    pending = [e for e in images if e.get("status") == "pending_review"]
    failed = [e for e in images if e.get("status") == "failed"]

    if pending:
        print(f"FATAL: {len(pending)} candidate(s) are still pending_review — "
              f"finish the review before exporting: {[e['role'] for e in pending]}")
        return 1
    if not approved:
        print("FATAL: no approved candidates to export.")
        return 1

    trigger = candidate_manifest.get("trigger_token", TRIGGER)
    identity_traits = candidate_manifest.get("identity_traits", IDENTITY_TRAITS)
    build = candidate_manifest.get("build")
    marks_truth = candidate_manifest.get("marks_truth", [])
    exported_at = datetime.now(timezone.utc).isoformat()

    # ── Fresh approved-pack tree ────────────────────────────────────────────
    if APPROVED_DIR.exists():
        shutil.rmtree(APPROVED_DIR)
    APPROVED_IMG_DIR.mkdir(parents=True, exist_ok=True)
    APPROVED_CAP_DIR.mkdir(parents=True, exist_ok=True)

    # ── Copy approved images + write captions ───────────────────────────────
    pack_images: list[dict] = []
    captions_map: dict[str, str] = {}
    missing_sources: list[str] = []
    for e in sorted(approved, key=lambda x: x["role"]):
        role = e["role"]
        src_img = OUT_DIR / e["image"]  # e.g. images/<role>.png
        if not src_img.is_file():
            missing_sources.append(role)
            continue
        img_name = f"{role}.png"
        cap_name = f"{role}.txt"
        caption = e.get("caption", f"{trigger} adult woman, {identity_traits}, {role}")

        shutil.copy2(src_img, APPROVED_IMG_DIR / img_name)
        (APPROVED_CAP_DIR / cap_name).write_text(caption)
        captions_map[img_name] = caption
        pack_images.append({
            "role": role,
            "group": e.get("group"),
            "image": f"images/{img_name}",
            "caption_file": f"captions/{cap_name}",
            "caption": caption,
        })

    if missing_sources:
        print(f"FATAL: approved candidate image(s) missing on disk: {missing_sources}")
        shutil.rmtree(APPROVED_DIR)
        return 1

    # ── Pack artifacts ──────────────────────────────────────────────────────
    pack_manifest = {
        "sprint": "S24X",
        "kind": "adult_lora_v4_approved_pack",
        "source": "summer_lora_v4_pack_candidates (reviewed)",
        "character_id": CHARACTER_ID,
        "character_name": CHARACTER_NAME,
        "trigger_token": trigger,
        "identity_traits": identity_traits,
        "build": build,
        "exported_at": exported_at,
        "safety": "adult-safe only — swimwear/underwear/reference-body; no explicit NSFW",
        "training_state": "NOT trained — packaged for offline LoRA v4 training only",
        "counts": {
            "approved": len(approved),
            "rejected": len(rejected),
            "failed": len(failed),
            "exported": len(pack_images),
        },
        "excluded_rejected_roles": sorted(e["role"] for e in rejected),
        "excluded_failed_roles": sorted(e["role"] for e in failed),
        "marks_truth": marks_truth,
        "images": pack_images,
    }
    (APPROVED_DIR / "manifest.json").write_text(
        json.dumps(pack_manifest, indent=2, ensure_ascii=False))
    (APPROVED_DIR / "captions.json").write_text(
        json.dumps(captions_map, indent=2, ensure_ascii=False))

    training_notes = {
        "trigger_token": trigger,
        "identity_traits": identity_traits,
        "build": build,
        "image_count": len(pack_images),
        "marks_truth": marks_truth,
        "recommended": {
            "base_model": "SDXL (RealVisXL) — matches prior Summer v2/v3 runs",
            "caption_style": "kohya sidecar .txt per image; trigger token leads each caption",
            "notes": [
                "Train OUTSIDE Ficshon (offline). This pack does NOT train anything.",
                "Captions are factual; preserve tattoo placement language verbatim.",
                "Rejected/failed candidates are intentionally excluded.",
            ],
        },
        "source_pack": "summer_lora_v4_pack_candidates",
        "exported_at": exported_at,
    }
    (APPROVED_DIR / "training_notes.json").write_text(
        json.dumps(training_notes, indent=2, ensure_ascii=False))

    readme = (
        "Summer Fielding — Adult LoRA v4 APPROVED training pack (S24X)\n"
        "=============================================================\n\n"
        f"trigger token : {trigger}\n"
        f"identity      : {identity_traits}; build: {build}\n"
        f"approved      : {len(approved)}   rejected: {len(rejected)}   "
        f"failed: {len(failed)}\n"
        f"exported      : {len(pack_images)} images\n"
        f"exported_at   : {exported_at}\n\n"
        "Contents\n"
        "--------\n"
        "  images/        approved candidate images (<role>.png)\n"
        "  captions/      one kohya-style .txt caption per image (basename matches)\n"
        "  captions.json  filename -> caption map\n"
        "  manifest.json  full approved-pack manifest (roles, captions, counts)\n"
        "  training_notes.json  trigger/base-model/caption guidance for training\n\n"
        "Excluded (rejected): "
        f"{', '.join(sorted(e['role'] for e in rejected)) or 'none'}\n\n"
        "Boundaries\n"
        "----------\n"
        "  - Adult-safe only (swimwear/underwear/reference-body). No explicit NSFW.\n"
        "  - This pack is NOT trained. It is offline LoRA v4 training material only.\n"
        "  - Built from reviewed manifest statuses; rejected candidates are excluded.\n"
    )
    (APPROVED_DIR / "README.txt").write_text(readme)

    # ── Zip everything (except the zip itself) ──────────────────────────────
    with zipfile.ZipFile(APPROVED_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(APPROVED_DIR.rglob("*")):
            if path == APPROVED_ZIP or not path.is_file():
                continue
            zf.write(path, path.relative_to(APPROVED_DIR).as_posix())

    # ── Verify ──────────────────────────────────────────────────────────────
    rejected_roles = {e["role"] for e in rejected}
    checks: list[tuple[str, bool, str]] = []
    checks.append(("exported count == approved count",
                   len(pack_images) == len(approved),
                   f"exported={len(pack_images)} approved={len(approved)}"))
    checks.append(("rejected count == 1 (reviewed)",
                   len(rejected) == 1, f"rejected={len(rejected)}"))
    # every exported image has a matching caption file + captions.json entry
    cap_ok = all(
        (APPROVED_CAP_DIR / f"{i['role']}.png".replace('.png', '.txt')).is_file()
        and f"{i['role']}.png" in captions_map
        for i in pack_images
    )
    checks.append(("every image has matching caption", cap_ok, ""))
    # no rejected role present in the exported images dir
    exported_pngs = {p.stem for p in APPROVED_IMG_DIR.glob("*.png")}
    no_rejected = rejected_roles.isdisjoint(exported_pngs)
    checks.append(("no rejected role included", no_rejected,
                   f"rejected={sorted(rejected_roles)}"))
    checks.append(("trigger is smmr_v4", trigger == "smmr_v4", f"trigger={trigger}"))
    checks.append(("pack zip exists", APPROVED_ZIP.is_file(),
                   f"{APPROVED_ZIP.stat().st_size if APPROVED_ZIP.is_file() else 0} bytes"))

    all_ok = all(ok for _, ok, _ in checks)

    # ── Report ──────────────────────────────────────────────────────────────
    print("=" * 70)
    print("S24X — SUMMER ADULT LoRA v4 — APPROVED PACK EXPORT")
    print("=" * 70)
    print(f"trigger token : {trigger}")
    print(f"identity      : {identity_traits}; build: {build}")
    print(f"approved      : {len(approved)}")
    print(f"rejected      : {len(rejected)}  -> {sorted(rejected_roles) or 'none'}")
    print(f"failed        : {len(failed)}")
    print(f"output dir    : {APPROVED_DIR.relative_to(REPO)}")
    print(f"zip           : {APPROVED_ZIP.relative_to(REPO)}")
    print("-" * 70)
    print("verification:")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    print("-" * 70)
    print(f"approved role list ({len(pack_images)}):")
    for i in pack_images:
        print(f"  {i['role']:32s} {i['image']}")
    print("=" * 70)
    if not all_ok:
        print("EXPORT FAILED VERIFICATION — see FAIL lines above.")
        return 1
    print("STOP: approved pack exported. No training was performed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated role names to (re)generate")
    ap.add_argument("--dry-run", action="store_true", help="print plan, generate nothing")
    ap.add_argument("--force", action="store_true",
                    help="regenerate even if the image already exists (default: skip existing)")
    ap.add_argument("--export-approved", action="store_true",
                    help="S24X: export ONLY approved candidates to the approved pack (no generation)")
    args = ap.parse_args()

    # S24X export path is DB-free and provider-free: it reads review statuses
    # from the candidate manifest only. Branch BEFORE any canon/Gemini setup.
    if args.export_approved:
        return export_approved_pack()

    sys.path.insert(0, str(BACKEND))
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")

    from app.core.database import SessionLocal
    from app.core.storage import load_image_bytes
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.services import adult_studio as svc

    # ── Read locked canon (read-only) ──────────────────────────────────────
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
    finally:
        db.close()

    # url-by-canon-role lookup for anchor selection
    url_by_role = {r["role"]: r["url"] for r in manifest.get("refs", [])}

    selected = ROLES
    if args.only:
        wanted = {r.strip() for r in args.only.split(",") if r.strip()}
        selected = [r for r in ROLES if r["role"] in wanted]
        if not selected:
            print(f"FATAL: --only matched no known roles. Known: {[r['role'] for r in ROLES]}")
            return 1

    print("=" * 70)
    print("S24V — SUMMER ADULT LoRA v4 — CANDIDATE PACK BUILDER")
    print("=" * 70)
    print(f"character           : {CHARACTER_NAME} (id={CHARACTER_ID})")
    print(f"trigger token       : {TRIGGER}")
    print(f"canon refs available: {list(url_by_role)}")
    print(f"roles to generate   : {len(selected)}  (band 18-24)")
    print(f"output dir          : {OUT_DIR.relative_to(REPO)}")
    print(f"mode                : {'DRY-RUN (no generation)' if args.dry_run else 'GENERATE'}")
    print("-" * 70)

    if args.dry_run:
        for rd in selected:
            anchors = [a for a in _anchor_roles(rd) if a in url_by_role]
            print(f"  {rd['role']:32s} group={rd['group']:5s} anchors={anchors}")
        print("\nDRY-RUN complete. No images generated.")
        return 0

    # ── Generator (Gemini) ─────────────────────────────────────────────────
    from app.services.image_providers.google_provider import GoogleImageProvider
    provider = GoogleImageProvider()

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    CAP_DIR.mkdir(parents=True, exist_ok=True)

    # Cache canon anchor bytes so we load each at most once.
    _anchor_cache: dict[str, bytes] = {}

    def anchor_bytes(canon_role: str) -> bytes | None:
        if canon_role in _anchor_cache:
            return _anchor_cache[canon_role]
        url = url_by_role.get(canon_role)
        if not url:
            return None
        try:
            data = load_image_bytes(url)
            _anchor_cache[canon_role] = data
            return data
        except Exception as exc:  # noqa: BLE001
            print(f"    WARN anchor load failed role={canon_role} err={exc!r}")
            return None

    entries: list[dict] = []
    for rd in selected:
        role = rd["role"]
        prompt = svc.build_adult_prompt(rd["scene"], manifest, CHARACTER_NAME)
        caption = f"{TRIGGER} adult woman, {IDENTITY_TRAITS}, {rd['caption']}"
        # Exclude a role's own same-view canon image from its anchors: asking
        # Gemini to reproduce the exact reference it is shown triggers
        # IMAGE_RECITATION refusals. Other angles still lock identity.
        anchor_role_names = [a for a in _anchor_roles(rd) if a in url_by_role and a != role]
        refs = [b for b in (anchor_bytes(a) for a in anchor_role_names) if b]

        img_rel = f"images/{role}.png"
        cap_rel = f"captions/{role}.txt"
        entry = {
            "role": role,
            "group": rd["group"],
            "image": img_rel,
            "caption_file": cap_rel,
            "caption": caption,
            "anchor_roles": anchor_role_names,
            "status": "pending_review",
        }

        # Idempotent: keep an already-generated candidate unless --force, so a
        # plain full run rebuilds the manifest from disk without re-calling Gemini.
        existing = IMG_DIR / f"{role}.png"
        if existing.exists() and not args.force:
            (CAP_DIR / f"{role}.txt").write_text(caption)
            entry["bytes"] = existing.stat().st_size
            print(f"    EXISTS -> {img_rel} ({entry['bytes']} bytes) — kept")
            entries.append(entry)
            continue

        print(f"  {role:32s} anchors={anchor_role_names}")
        if not refs:
            entry["status"] = "failed"
            entry["error"] = "no canon anchor images could be loaded"
            print(f"    SKIP — {entry['error']}")
            entries.append(entry)
            continue

        last_err = None
        for attempt in range(1, RETRIES + 1):
            try:
                img_bytes = provider.generate_with_multi_reference(
                    prompt=prompt, reference_images=refs
                )
                (IMG_DIR / f"{role}.png").write_bytes(img_bytes)
                (CAP_DIR / f"{role}.txt").write_text(caption)
                entry["bytes"] = len(img_bytes)
                print(f"    OK   -> {img_rel} ({len(img_bytes)} bytes)")
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                print(f"    attempt {attempt}/{RETRIES} failed: {exc!r}")
                if attempt < RETRIES:
                    time.sleep(3)
        else:
            entry["status"] = "failed"
            entry["error"] = repr(last_err)
        entries.append(entry)

    # ── Manifest ───────────────────────────────────────────────────────────
    # On a subset run (--only) merge into the existing manifest so prior entries
    # for untouched roles are preserved instead of clobbered.
    if args.only and MANIFEST_PATH.exists():
        prior = json.loads(MANIFEST_PATH.read_text()).get("images", [])
        touched = {e["role"] for e in entries}
        entries = [p for p in prior if p["role"] not in touched] + entries
        # Keep canonical role order.
        order = {rd["role"]: i for i, rd in enumerate(ROLES)}
        entries.sort(key=lambda e: order.get(e["role"], 999))

    ok = [e for e in entries if e["status"] == "pending_review"]
    failed = [e for e in entries if e["status"] == "failed"]
    out_manifest = {
        "sprint": "S24V",
        "kind": "adult_lora_v4_candidate_pack",
        "character_id": CHARACTER_ID,
        "character_name": CHARACTER_NAME,
        "trigger_token": TRIGGER,
        "identity_traits": IDENTITY_TRAITS,
        "build": manifest.get("build"),
        "generator": "google_gemini_multi_reference",
        "source": "locked canon identity pack (read-only)",
        "safety": "adult-safe only — swimwear/underwear/reference-body; no explicit NSFW",
        "review_state": "candidates_pending_review",
        "export_note": (
            "FINAL pack export is a separate, user-approved step. Only images with "
            "status=='approved' (set during review) should be exported; rejected/failed "
            "images MUST be excluded. This builder never exports the final pack."
        ),
        "counts": {
            "total_roles": len(entries),
            "pending_review": len(ok),
            "failed": len(failed),
        },
        "marks_truth": [
            {"label": m["label"], "region": m["body_region"], "side": m["side"]}
            for m in manifest.get("marks", [])
        ],
        "images": entries,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(out_manifest, indent=2, ensure_ascii=False))

    # ── Report ─────────────────────────────────────────────────────────────
    print("-" * 70)
    print(f"pending_review : {len(ok)}")
    print(f"failed         : {len(failed)}")
    print(f"manifest       : {MANIFEST_PATH.relative_to(REPO)}")
    print("\ncandidate images (pending_review):")
    for e in ok:
        print(f"  {OUT_DIR.relative_to(REPO)}/{e['image']}")
    if failed:
        print("\nfailed roles (regenerate with --only):")
        for e in failed:
            print(f"  {e['role']:32s} {e.get('error','')}")
    print("=" * 70)
    print("STOP: candidate pack staged. Review images, then approve before any")
    print("final pack export or LoRA v4 training. No training was performed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
