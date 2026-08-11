"""Summer-only exposure-class supplement to the permanent-mark soak.

MEASUREMENT ONLY — same rules as ``mark_soak.py`` (which supplies every scoring
and retention primitive here): no repair, no retry, no re-rolls, every image
kept, three verdict states.

Why a supplement rather than new rows in ``mark_soak.CLASSES``: that matrix is
shared by five characters and compared row-for-row across passes, so adding
rows to it would break comparability with the recorded runs. These rows are
Summer's four garment/exposure classes as stated in the canon-correction brief:

    bare_arms      — both arms fully bare (bikini / sleeveless)
    short_sleeve   — upper arms covered, forearms bare
    rolled_sleeve  — upper arms covered, forearms bare
    long_sleeve    — both arms fully covered

Expectations are region GROUPS, intersected with Summer's own mark authority by
``mark_soak.score_marks``. Group-level scoring cannot see SIDE, so it cannot
prove "butterfly on the left, ballerina on the right" — that is exactly why
every image from this run must still be inspected by eye. The automated verdict
is diagnostic.

Usage:
    python3 scripts/summer_exposure_soak.py                  # dry run
    python3 scripts/summer_exposure_soak.py --apply --out soak_runs/summer_exposure_p1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal                              # noqa: E402
from app.core.storage import load_image_bytes                           # noqa: E402
from app.models.character_identity_canon import CharacterIdentityCanon  # noqa: E402
from app.services.canon_service import load_body_canon, load_face_canon  # noqa: E402
from app.services.card_coverage import mark_location_authority          # noqa: E402
from app.services.image_providers.google_provider import GoogleImageProvider  # noqa: E402

from mark_soak import run_row, summarise  # noqa: E402

CHARACTER_ID = 60

# key -> (prompt, expect_visible, expect_hidden)
ROWS: dict[str, tuple[str, list[str], list[str]]] = {
    "bare_arms_bikini": (
        "Summer in a bikini on a sunny beach",
        ["upper_arms", "forearms"], []),
    "bare_arms_sleeveless": (
        "Summer in a sleeveless top at a rooftop bar",
        ["upper_arms", "forearms"], ["torso"]),
    "short_sleeve": (
        "Summer in a bar wearing a t-shirt",
        ["forearms"], ["torso", "upper_arms"]),
    "rolled_sleeve": (
        "Summer at her desk with shirt sleeves rolled up",
        ["forearms"], ["torso", "upper_arms"]),
    "long_sleeve_sweater": (
        "Summer in a long-sleeved sweater walking in the park",
        [], ["torso", "upper_arms", "forearms"]),
    "long_sleeve_shirt": (
        "Summer in a buttoned long-sleeve shirt and jeans in a cafe",
        [], ["torso", "upper_arms", "forearms"]),
    # ── The three routing gaps, as generated scenes ───────────────────
    # A: a sports bra is sleeveless, but the phrase carried no exposure signal,
    # so this scene used to render a bare right forearm.
    "sports_bra": (
        "Summer in a sports bra and leggings at the gym",
        ["upper_arms", "forearms"], []),
    # B: the deployment blocker — clothing unstated, marks explicitly asked
    # for. Sampled three times because the failure (a left/right swap) is a
    # sampling outcome, and one clean image would not settle it.
    "emphasis_1": (
        "Summer in her office - any tattoos that should be visible are visible",
        [], []),
    "emphasis_2": (
        "Summer in her office - any tattoos that should be visible are visible",
        [], []),
    "emphasis_3": (
        "Summer in her office - any tattoos that should be visible are visible",
        [], []),
    # B, second phrasing: an explicit request that also names no garment.
    "emphasis_show_tattoos": (
        "Summer at home, show her tattoos",
        [], []),
    # B, adversarial: an explicit request AND a garment that covers the arms.
    # Asking must not uncover them.
    "emphasis_covered": (
        "Summer at a formal dinner in a long-sleeved suit and tie, show her tattoos",
        [], ["upper_arms", "forearms", "torso"]),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pass", dest="pass_no", type=int, default=1)
    ap.add_argument("--out", default="soak_runs/summer_exposure")
    args = ap.parse_args()

    rows = [
        {"character_id": CHARACTER_ID, "name": "Summer", "role": "tattooed",
         "class": key, "prompt": prompt, "expect_visible": vis, "expect_hidden": hid}
        for key, (prompt, vis, hid) in ROWS.items()
    ]
    print(f"matrix rows: {len(rows)}  pass={args.pass_no}")
    for r in rows:
        print(f"  {r['class']:22} {r['prompt']}")
    if not args.apply:
        print("\nDRY RUN — no generations.")
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    canon = db.query(CharacterIdentityCanon).filter_by(character_id=CHARACTER_ID).first()
    body = load_body_canon(canon)
    authority = mark_location_authority(body) or frozenset()
    face_ref = load_image_bytes(load_face_canon(canon).face_front_image_url)
    provider = GoogleImageProvider()

    results = []
    for i, row in enumerate(rows, 1):
        rec = run_row(row, canon, provider, authority, face_ref, out_dir, args.pass_no)
        results.append(rec)
        print(f"[{i}/{len(rows)}] {rec['class']:22} mark={rec['mark']['state']:12} "
              f"face={rec['face']['state']:12} crops={rec.get('mark_crops')} "
              f"regions={rec.get('crop_regions')} viol={rec['mark'].get('violations')} "
              f"miss={rec['mark'].get('missing')}", flush=True)
        (out_dir / f"results_pass{args.pass_no}.json").write_text(json.dumps(results, indent=2))
    db.close()
    summarise(results)
    print(f"\nartefacts: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
