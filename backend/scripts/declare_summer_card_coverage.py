"""Summer (character 60) — declare the depicted skin coverage of her body cards.

WHY
---
Every body-bearing card Summer has (body_front / left / right / back, the body
map and the final character card) photographs her in a bikini. The coverage
engine, however, had no declaration for any of them, so ``card_visible_regions``
returned ``unknown`` — deliberately NOT read as bare and NOT read as clothed.
The consequence is that on an explicitly covered scene (long-sleeved suit,
sweater) the router could not tell that its own reference cards contradict the
requested wardrobe, and routed bare-skin evidence anyway. That is precisely the
Davies bleed-through the coverage system exists to prevent; Summer simply never
had the metadata to trigger it.

WHAT
----
Declares ``coverage_type="swimwear"`` for each body-bearing slot. The preset
expands to (torso, upper_arms, forearms, neck, legs) — which is exactly what a
bikini shot shows, and is verifiable by looking at the cards.

``final_character_card`` is included deliberately: it is a composite whose
figure panels are the same bikini shots, so it *does* depict bare torso, arms,
neck and legs. Its clothed wardrobe strip does not make the bare panels absent.

This is metadata about what the images show. No image, mark, region, side or
lock is touched. Dev canon only; run with --apply (default is a dry run).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal                              # noqa: E402
from app.models.character_identity_canon import CharacterIdentityCanon  # noqa: E402
from app.schemas.canon import CardCoverage                              # noqa: E402
from app.services.canon_service import _save_body, load_body_canon      # noqa: E402

CHARACTER_ID = 60
BIKINI_SLOTS = (
    "body_front", "body_left", "body_right", "body_back",
    "body_map", "final_character_card",
)
COVERAGE_TYPE = "swimwear"

PROMPTS = [
    ("bare arms (bikini)",   "Summer in a bikini on a sunny beach"),
    ("sports bra",           "Summer in a sports bra and leggings at the gym"),
    ("short sleeve",         "Summer in a bar wearing a t-shirt"),
    ("rolled sleeves",       "Summer at her desk with shirt sleeves rolled up"),
    ("long sleeve (suit)",   "Summer at a formal dinner in a long-sleeved suit and tie"),
    ("long sleeve (sweater)", "Summer in a long-sleeved sweater walking in the park"),
    ("ambiguous office",     "Summer in her office"),
    ("tattoo emphasis",      "Summer in her office - any tattoos that should be visible are visible"),
]


def show_routing(canon, label: str) -> None:
    from app.services.scene_router import route_canon_refs
    print(f"\n──── routing {label} ────")
    for name, prompt in PROMPTS:
        urls, meta = route_canon_refs(prompt, canon)
        slots = meta.route_slots or ["<fallback ordering>"]
        print(f"  {name:22} camera={meta.camera:8} crops={meta.mark_crops} "
              f"refs={len(urls)} suppressed={meta.coverage_suppressed} "
              f"anchor={meta.coverage_conflict_anchor}")
        print(f"  {'':22} slots={slots}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup", default="")
    args = ap.parse_args()

    db = SessionLocal()
    canon = db.query(CharacterIdentityCanon).filter_by(character_id=CHARACTER_ID).first()
    if canon is None:
        raise SystemExit(f"no canon row for character {CHARACTER_ID}")
    if args.backup:
        Path(args.backup).write_text(canon.body_canon_json or "")
        print(f"backup written: {args.backup}")

    body = load_body_canon(canon)
    present = [s for s in BIKINI_SLOTS if getattr(body, f"{s}_image_url", None)]
    print("declared before:", dict(body.card_coverage))
    print("slots present  :", present)
    show_routing(canon, "BEFORE")

    for slot in present:
        body.card_coverage[slot] = CardCoverage(coverage_type=COVERAGE_TYPE)

    if not args.apply:
        print("\nDRY RUN — no write. Re-run with --apply.")
        return

    _save_body(canon, body)
    db.commit()
    db.refresh(canon)
    stored = json.loads(canon.body_canon_json)
    print("\ndeclared after:", {k: v["visible_skin_regions"]
                                for k, v in stored["card_coverage"].items()})
    print("marks:", len(stored["permanent_body_marks"]),
          "| locked:", stored["locked"],
          "| marked_regions:", stored.get("marked_regions"))
    show_routing(canon, "AFTER")
    db.close()


if __name__ == "__main__":
    main()
