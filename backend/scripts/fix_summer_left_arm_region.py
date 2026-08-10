"""Summer (character 60) — one-off canon FACT correction for the left-arm mark.

WHAT WAS WRONG
--------------
``pbm_8cff990d`` ("Butterfly floral sleeve") was stored as ``left_upper_arm``
with the description "running from the shoulder cap down to the elbow".

That anatomy came from the TEXT LEGEND printed on Summer's own body-map card
("Butterflies & Wildflowers (shoulder to elbow)"). The IMAGES on that same card
— and body_front, body_left, body_right, body_back, the final character card and
its wardrobe strip — all show the work running continuously from the shoulder
cap, across the elbow, down the forearm and ending just above the wrist. The
legend is wrong; the renders are the truth.

Consequence of the wrong region: ``_mark_region_exposed`` correctly treats an
upper-arm mark as COVERED by short/rolled sleeves, so every forearm-exposing
scene routed only the ballerina crop and named only the right forearm in the
prompt — leaving Summer's left forearm generated as bare skin.

WHAT THIS CHANGES
-----------------
Two fields on one mark:
  body_region : left_upper_arm -> left_full_arm   (existing schema vocabulary)
  description : corrected to the anatomy the cards show

Nothing else. The side, label, ids, reference/detail images, the other mark,
marked_regions, every canon image URL and both identity locks are untouched.

Dev canon only. Run with --apply to write; default is a dry run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal                              # noqa: E402
from app.models.character_identity_canon import CharacterIdentityCanon  # noqa: E402
from app.services.canon_service import _save_body, load_body_canon      # noqa: E402

CHARACTER_ID = 60
MARK_ID = "pbm_8cff990d"
NEW_REGION = "left_full_arm"
NEW_DESCRIPTION = (
    "Butterflies and wildflowers in fine black line work, running continuously "
    "from the shoulder cap down the outer arm, across the elbow and down the "
    "forearm, ending just above the wrist; hand unmarked"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the correction")
    ap.add_argument("--backup", default="", help="path to dump the pre-change body_canon_json")
    args = ap.parse_args()

    db = SessionLocal()
    canon = db.query(CharacterIdentityCanon).filter_by(character_id=CHARACTER_ID).first()
    if canon is None:
        raise SystemExit(f"no canon row for character {CHARACTER_ID}")
    if args.backup:
        Path(args.backup).write_text(canon.body_canon_json or "")
        print(f"backup written: {args.backup}")

    body = load_body_canon(canon)
    mark = next((m for m in body.permanent_body_marks if m.id == MARK_ID), None)
    if mark is None:
        raise SystemExit(f"mark {MARK_ID} not found")

    print("BEFORE  region=%r\n        description=%r" % (mark.body_region, mark.description))
    if mark.body_region == NEW_REGION and mark.description == NEW_DESCRIPTION:
        print("already correct — nothing to do")
        return

    mark.body_region = NEW_REGION
    mark.description = NEW_DESCRIPTION
    print("AFTER   region=%r\n        description=%r" % (mark.body_region, mark.description))

    if not args.apply:
        print("\nDRY RUN — no write. Re-run with --apply.")
        return

    _save_body(canon, body)
    db.commit()
    db.refresh(canon)
    stored = json.loads(canon.body_canon_json)
    written = next(m for m in stored["permanent_body_marks"] if m["id"] == MARK_ID)
    print("\nwritten:", written["body_region"], "| locked:", stored["locked"],
          "| marks:", len(stored["permanent_body_marks"]),
          "| marked_regions:", stored.get("marked_regions"))
    db.close()


if __name__ == "__main__":
    main()
