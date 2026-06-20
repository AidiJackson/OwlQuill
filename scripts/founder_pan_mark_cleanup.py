#!/usr/bin/env python3
"""S24AL one-off: remove the two duplicate, markless Pan permanent marks.

Context: the founder-run step (founder_v2_build.py) reused an existing Pan
(character_id=59) that already carried two older, image-less marks. The run then
added two new, detail-cropped marks, leaving four total (two redundant pairs).

This script removes ONLY the two stale markless duplicates and keeps the two new
detail-cropped marks. It is deliberately narrow and safe:

  * No provider calls, no generation, no rebuild, no canon-slot writes.
  * Removes ONLY the two ids in REMOVE_IDS, and ONLY if each is markless
    (no detail_crop_url AND no reference_image_url) — refuses otherwise.
  * Verifies the resulting state before committing the DB transaction.

Usage:
    python scripts/founder_pan_mark_cleanup.py            # dry-run (no DB write)
    python scripts/founder_pan_mark_cleanup.py --commit   # apply
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

CHARACTER_ID = 59
REMOVE_IDS = {"pbm_e5fe91db", "pbm_83ab0fc7"}   # stale markless duplicates
KEEP_IDS = {"pbm_9d986c0a", "pbm_a3c99534"}     # new detail-cropped marks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Apply the deletion")
    args = ap.parse_args()

    from app.core.database import SessionLocal
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.models.character_image import CharacterImage
    from app.services import canon_service as cs

    db = SessionLocal()
    try:
        canon = db.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == CHARACTER_ID
        ).first()
        if canon is None:
            print(f"ABORT: no canon for character_id={CHARACTER_ID}")
            return 2

        body = cs.load_body_canon(canon)
        marks = {m.id: m for m in (body.permanent_body_marks if body else [])}
        print(f"BEFORE: {len(marks)} marks")
        for mid, m in marks.items():
            has_img = bool(m.detail_crop_url or m.reference_image_url)
            print(f"  {mid}  label={m.label!r}  region={m.body_region}  side={m.side}  "
                  f"has_image={has_img}")

        # Safety gate: the removal targets are explicitly enumerated by id (and
        # authorised by the user). The one invariant we enforce mechanically is
        # that we NEVER delete a mark carrying a detail_crop_url — that is the
        # distinguishing feature of the two new marks we must keep. (The stale
        # duplicates carry only a reference_image_url, not a detail crop.)
        if REMOVE_IDS & KEEP_IDS:
            print("ABORT: remove/keep id sets overlap")
            return 2
        for mid in REMOVE_IDS:
            m = marks.get(mid)
            if m is None:
                print(f"ABORT: target {mid} not found")
                return 2
            if m.detail_crop_url:
                print(f"ABORT: target {mid} has a detail_crop_url — refusing to delete")
                return 2
        for kid in KEEP_IDS:
            m = marks.get(kid)
            if m is None:
                print(f"ABORT: keep-target {kid} missing")
                return 2
            if not m.detail_crop_url:
                print(f"ABORT: keep-target {kid} lacks a detail_crop_url — unexpected")
                return 2

        if not args.commit:
            print("\nDRY-RUN: would remove", sorted(REMOVE_IDS), "— no DB write.")
            return 0

        for mid in REMOVE_IDS:
            ok = cs.remove_permanent_mark(canon, mid)
            print(f"removed {mid}: {ok}")
        db.commit()
        db.refresh(canon)

        # ── Verify ────────────────────────────────────────────────────
        body = cs.load_body_canon(canon)
        remaining = {m.id: m for m in body.permanent_body_marks}
        checks = {
            "char locked": canon.status == "locked" and canon.face_locked and canon.body_locked,
            "exactly 2 marks remain": len(remaining) == 2,
            "remaining are the kept ids": set(remaining) == KEEP_IDS,
            "both have an image ref": all(
                bool(m.detail_crop_url or m.reference_image_url) for m in remaining.values()),
        }
        left = remaining.get("pbm_9d986c0a")
        right = remaining.get("pbm_a3c99534")
        if left:
            checks["left scripture = left_full_arm"] = (
                left.side == "left" and left.body_region == "left_full_arm")
        if right:
            checks["right wolf = right_full_arm"] = (
                right.side == "right" and right.body_region == "right_full_arm")

        scene_ids = [1956, 1957, 1958]
        present = {
            i for (i,) in db.query(CharacterImage.id)
            .filter(CharacterImage.id.in_(scene_ids)).all()
        }
        checks["validation images 1956-1958 exist"] = present == set(scene_ids)

        print("\n=== VERIFY ===")
        for k, v in checks.items():
            print(f"  [{'OK' if v else 'FAIL'}] {k}")
        print("\nAFTER:", len(remaining), "marks")
        for mid, m in remaining.items():
            print(f"  {mid}  label={m.label!r}  region={m.body_region}  side={m.side}  "
                  f"detail_crop={m.detail_crop_url}")

        if not all(checks.values()):
            print("\nVERIFY FAILED — rolling back is recommended (rollback tag exists).")
            return 1
        print("\nCLEANUP OK.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
