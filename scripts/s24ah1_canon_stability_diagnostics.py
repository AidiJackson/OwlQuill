#!/usr/bin/env python3
"""S24AH.1 diagnostics — verify Canon Studio restored to pre-S24AB behaviour
with S24AD safety intact. Dry-run prompt compilation + ref routing only (NO
provider calls). Self-contained: builds a synthetic canon with arm marks, so it
runs anywhere without a DB.

Contract under test (S24AH.1 — Restore Canon Stability):
  * The aggressive S24AB "mandatory identity features" directive is GONE.
  * Naturally visible marks are still preserved on EXPLICIT exposure
    (shirtless, rolled sleeves) — routed + surfaced, never force-exposed.
  * VAGUE scene cues (casual, beach, summer clothes, sweater) no longer force
    exposure — covered marks stay hidden under the clothing-truth guard.

Run from backend/:
    cd backend && python3 ../scripts/s24ah1_canon_stability_diagnostics.py
"""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.canon_compiler import compile_canon_prompt
from app.services.scene_router import route_canon_refs

FACE_FRONT = "https://cdn.test/face_front.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"
FINAL_CARD = "https://cdn.test/final_card.png"
LEFT_SLEEVE_CROP = "https://cdn.test/crop_left_sleeve.png"
RIGHT_WOLF_CROP = "https://cdn.test/crop_right_wolf.png"

# The reverted directive must never appear again.
_FORBIDDEN = "mandatory identity features"


def _make_canon() -> CharacterIdentityCanon:
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 1
    face = FaceCanonData(face_front_image_url=FACE_FRONT)
    body = BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_map_image_url=BODY_MAP,
        final_character_card_image_url=FINAL_CARD,
        permanent_body_marks=[
            PermanentBodyMark(
                label="Left sleeve", type="tattoo", body_region="left_full_arm",
                side="left", description="gothic script sleeve",
                reference_image_url=LEFT_SLEEVE_CROP,
            ),
            PermanentBodyMark(
                label="Wolf", type="tattoo", body_region="right_upper_arm",
                side="right", description="wolf howling",
                reference_image_url=RIGHT_WOLF_CROP,
            ),
        ],
    )
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = None
    return canon


# (label, prompt, expect_exposed_marks)
CASES = [
    ("Pan rolled sleeves",  "Pan in a black shirt with sleeves rolled to the elbows", True),
    ("Pan shirtless",       "Pan standing shirtless in a dark forest",                True),
    ("Summer casual",       "Summer in casual summer clothes at a cafe",              False),
    ("Summer beach casual", "Summer standing on a beach, casual outfit",              False),
    ("Summer sweater",      "Summer wearing a cosy sweater in a coffee shop",         False),
]


def main() -> int:
    canon = _make_canon()
    failures: list[str] = []

    for label, prompt, expect_exposed in CASES:
        urls, meta = route_canon_refs(prompt, canon)
        compiled = compile_canon_prompt(canon, prompt).lower()
        surfaced = "skin-bound anatomy" in compiled
        forbidden_present = _FORBIDDEN in compiled
        clothing_guard = "permanent markings obey scene clothing" in compiled

        print(f"\n{'='*74}\n{label}: {prompt!r}")
        print(f"  camera={meta.camera} exposure={meta.exposure} "
              f"crops={meta.mark_crops} refs={len(urls)}")
        print(f"  marks_surfaced={surfaced} clothing_guard={clothing_guard} "
              f"forbidden_directive={forbidden_present}")

        if forbidden_present:
            failures.append(f"{label}: S24AB '{_FORBIDDEN}' directive still present")
        if not clothing_guard:
            failures.append(f"{label}: clothing-truth guard missing")
        if expect_exposed:
            if not surfaced:
                failures.append(f"{label}: explicit exposure but marks NOT surfaced")
            if meta.mark_crops < 1:
                failures.append(f"{label}: explicit exposure but no mark crop routed")
        else:
            if surfaced:
                failures.append(f"{label}: vague cue FORCED marks visible (regression)")
            if meta.mark_crops != 0:
                failures.append(f"{label}: vague cue routed {meta.mark_crops} crop(s)")

    print(f"\n{'='*74}\nRESULT:",
          "PASS — Canon restored to pre-S24AB behaviour with S24AD safety"
          if not failures else "FAIL\n  - " + "\n  - ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
