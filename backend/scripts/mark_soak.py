"""Permanent-mark soak harness — MEASUREMENT ONLY.

Measures how reliably generated images obey a character's permanent-mark canon,
so an enforcement layer can be sized against the CURRENT failure rate.

This tool measures the generator. It deliberately does NOT:
  * repair or regenerate any image,
  * retry a failed generation,
  * alter prompts in response to a verdict,
  * feed any verifier output back into generation.
A run that changed the thing it measures would be worthless.

Design rules learned from the first (invalid) soak:

  RETENTION — every generated image is written to disk with its metadata.
  The first run kept nothing, so three failures could never be diagnosed and
  the whole run had to be discarded.

  THREE STATES — mark and face verdicts are PASS / FAIL / NOT_SCORABLE and are
  reported SEPARATELY. Insufficient evidence (face turned away, face too small
  to read) is never folded into FAIL: the first run scored back-facing shots on
  face similarity and counted the inevitable low score as an identity failure.

  NO CHERRY-PICKING — prompts are fixed up front, every row is recorded, and a
  row is never re-rolled.

Usage:
    python3 scripts/mark_soak.py                     # dry run, prints matrix
    python3 scripts/mark_soak.py --apply --pass 1
    python3 scripts/mark_soak.py --apply --pass 2

Outputs land in --out (default ./soak_runs), which is OUTSIDE application
storage: soak images are test artefacts and must never appear in a user's
gallery or in canon.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings                                   # noqa: E402
from app.core.database import SessionLocal                             # noqa: E402
from app.core.storage import load_image_bytes                          # noqa: E402
from app.models.character_identity_canon import CharacterIdentityCanon  # noqa: E402
from app.services.canon_compiler import compile_canon_prompt           # noqa: E402
from app.services.canon_service import load_body_canon, load_face_canon  # noqa: E402
from app.services.card_coverage import mark_location_authority         # noqa: E402
from app.services.face_verifier import prompt_is_face_away, verify_face_match  # noqa: E402
from app.services.image_providers.google_provider import GoogleImageProvider   # noqa: E402
from app.services.mark_verifier import verify_mark_regions             # noqa: E402
from app.services.scene_router import route_canon_refs, slot_names_for_urls    # noqa: E402

PASS, FAIL, NOT_SCORABLE = "PASS", "FAIL", "NOT_SCORABLE"

# ── Prompt classes ────────────────────────────────────────────────────
# key -> (template, expect_visible, expect_hidden). Expectations are region
# GROUPS and are intersected with each character's own authority at run time,
# so a character is never marked down for a mark they do not have.
CLASSES: dict[str, tuple[str, list[str], list[str]]] = {
    "vague_work":   ("{name} in {poss} office", ["hands"], ["torso", "back"]),
    "vague_gym":    ("{name} in the gym", ["hands"], []),
    "covered_suit": ("{name} at a formal dinner in a long-sleeved suit and tie",
                     ["hands"], ["torso", "back", "upper_arms", "forearms"]),
    "short_sleeve": ("{name} in a bar wearing a t-shirt", ["forearms", "hands"], ["torso", "back"]),
    "rolled":       ("{name} at {poss} desk with shirt sleeves rolled up",
                     ["forearms", "hands"], ["torso", "back"]),
    "shirtless":    ("{name} shirtless in the gym", ["torso", "forearms"], []),
    "emphasis":     ("{name} in {poss} office - any tattoos that should be visible are visible",
                     ["hands"], ["torso", "back"]),
    "back_view":    ("{name} from behind, shirtless", ["back"], []),
    "gloved":       ("{name} in {poss} office wearing leather gloves", [], ["hands", "torso"]),
}

ROSTER: dict[int, dict] = {
    38: {"name": "Davies", "poss": "his", "role": "tattooed",
         "classes": ["vague_work", "vague_gym", "covered_suit", "short_sleeve",
                     "rolled", "shirtless", "emphasis", "gloved", "back_view"]},
    59: {"name": "Pan", "poss": "his", "role": "tattooed",
         "classes": ["vague_work", "vague_gym", "covered_suit", "short_sleeve",
                     "rolled", "shirtless", "emphasis", "gloved"]},
    60: {"name": "Summer", "poss": "her", "role": "tattooed",
         "classes": ["vague_work", "covered_suit", "short_sleeve", "rolled",
                     "shirtless", "emphasis"],
         # The generic templates assume a male character. Reusing them here
         # would be inappropriate AND a measurement problem: a provider safety
         # refusal scores as a failed row and contaminates the rate.
         "overrides": {"shirtless": "Summer in a sports bra and leggings at the gym"}},
    47: {"name": "Angelo", "poss": "his", "role": "control_markless",
         "classes": ["vague_work", "covered_suit"]},
    63: {"name": "Alec", "poss": "his", "role": "control_clean",
         "classes": ["vague_work", "shirtless"]},
}


def build_matrix() -> list[dict]:
    rows = []
    for cid, spec in ROSTER.items():
        for key in spec["classes"]:
            tmpl, vis, hid = CLASSES[key]
            prompt = (spec.get("overrides") or {}).get(key) or tmpl.format(
                name=spec["name"], poss=spec["poss"])
            rows.append({
                "character_id": cid, "name": spec["name"], "role": spec["role"],
                "class": key, "prompt": prompt,
                "expect_visible": vis, "expect_hidden": hid,
            })
    return rows


def score_face(face_ref: bytes, img: bytes, prompt: str) -> dict:
    """Face verdict as PASS / FAIL / NOT_SCORABLE.

    Insufficient evidence is never FAIL. A prompt that provably turns the face
    away is ruled out before spending a call; otherwise the model reports
    whether enough face is visible to judge identity at all. The identity
    THRESHOLD is unchanged for images that are genuinely scorable.
    """
    if prompt_is_face_away(prompt):
        return {"state": NOT_SCORABLE, "reason": "prompt_faces_away", "similarity": None}
    verdict = verify_face_match(face_ref, img, assess_visibility=True)
    if not verdict.get("ok"):
        return {"state": NOT_SCORABLE, "reason": verdict.get("skip_reason") or "verify_failed",
                "similarity": None}
    if not verdict.get("face_visible", True):
        return {"state": NOT_SCORABLE, "reason": "face_not_readable",
                "similarity": verdict.get("similarity")}
    sim = float(verdict.get("similarity") or 0.0)
    ok = bool(verdict.get("match")) and sim >= settings.IDENTITY_FACE_VERIFY_THRESHOLD
    return {"state": PASS if ok else FAIL, "reason": "", "similarity": sim}


def score_marks(mv: dict, authority: frozenset[str], expect_visible: list[str]) -> dict:
    """Mark verdict as PASS / FAIL / NOT_SCORABLE.

    FAIL requires positive evidence of a canon breach: ink outside authority,
    ink on fabric, or an expected-and-exposed mark absent. Border/blurred
    readings are reported but never counted — that ambiguity is precisely what
    produced the false positives this harness was rebuilt to eliminate.
    """
    if not mv.get("ok"):
        return {"state": NOT_SCORABLE, "reason": mv.get("skip_reason") or "verify_failed",
                "violations": [], "missing": []}
    # A region only testifies to a MISSING mark if the image actually shows it
    # bare. A boxer with wrapped hands or a model whose arm is out of frame is
    # not a canon violation — counting it as one measures the harness, not the
    # generator (observed in the first corrected run: gym scenes dressed the
    # character in hand wraps).
    bare = set(mv.get("bare_regions") or [])
    expected = [r for r in expect_visible if r in authority]
    observed = mv.get("observed") or []
    missing = [r for r in expected if r not in observed and r in bare]
    unscorable_expected = [r for r in expected if r not in observed and r not in bare]
    violations = mv.get("violations") or []
    on_clothing = bool(mv.get("on_clothing"))
    failed = bool(violations or missing or on_clothing)
    return {
        "state": FAIL if failed else PASS,
        "reason": "", "violations": violations, "missing": missing,
        "on_clothing": on_clothing,
        "uncertain": mv.get("uncertain") or [],
        "uncertain_violations": mv.get("uncertain_violations") or [],
        "demoted": mv.get("demoted") or [],
        "covered_not_scorable": unscorable_expected,
        "bare_regions": sorted(bare),
        "observed": observed, "expected_visible": expected,
    }


def run_row(row, canon, provider, authority, face_ref, out_dir, pass_no):
    prompt = row["prompt"]
    urls, meta = route_canon_refs(prompt, canon)
    compiled = compile_canon_prompt(canon, prompt)
    slots = list(meta.route_slots) or slot_names_for_urls(canon, urls[:6])

    refs, seen, deduped = [], set(), 0
    for u in urls[:6]:
        b = load_image_bytes(u)
        h = hashlib.sha256(b).hexdigest()
        if h in seen:
            deduped += 1
            continue
        seen.add(h)
        refs.append(b)

    started = time.time()
    try:
        img = provider.generate_with_multi_reference(prompt=compiled, reference_images=refs)
    except Exception as exc:
        return {**row, "pass_no": pass_no, "generated": False,
                "error": str(exc)[:300], "mark": {"state": NOT_SCORABLE, "reason": "no_image"},
                "face": {"state": NOT_SCORABLE, "reason": "no_image"}}
    latency = round(time.time() - started, 1)

    # RETENTION: image first, so a later scoring crash cannot lose it.
    name = f"p{pass_no}_{row['character_id']}_{row['class']}.png"
    (out_dir / name).write_bytes(img)

    mark = score_marks(verify_mark_regions(img, authority), authority, row["expect_visible"])
    face = score_face(face_ref, img, prompt)

    return {
        **row, "pass_no": pass_no, "generated": True, "image": name,
        "latency_s": latency, "refs_sent": len(refs), "refs_deduped": deduped,
        "routed_slots": slots, "mark_crops": meta.mark_crops,
        "crop_regions": [b.body_region for b in meta.mark_crop_bindings],
        "camera": meta.camera,
        "authority": sorted(authority),
        "provider": "google", "model": settings.GOOGLE_IMAGE_MODEL,
        "clauses": {
            "clean_skin": "Clean-skin truth" in compiled,
            "conditional_occlusion": "Wherever clothing covers" in compiled,
            "absolute_occlusion": "Opaque clothing covers" in compiled,
            "per_mark": "immutable skin-bound anatomy" in compiled,
        },
        "compiled_prompt": compiled,
        "mark": mark, "face": face,
    }


def summarise(results: list[dict]) -> None:
    gen = [r for r in results if r.get("generated")]
    def count(key, state):
        return sum(1 for r in gen if r[key]["state"] == state)
    print(f"\n{'':<24}{'PASS':>6}{'FAIL':>6}{'N/S':>6}")
    print(f"{'MARK CORRECTNESS':<24}{count('mark', PASS):>6}{count('mark', FAIL):>6}"
          f"{count('mark', NOT_SCORABLE):>6}")
    print(f"{'FACE IDENTITY':<24}{count('face', PASS):>6}{count('face', FAIL):>6}"
          f"{count('face', NOT_SCORABLE):>6}")
    scorable = [r for r in gen if r["mark"]["state"] != NOT_SCORABLE]
    if scorable:
        rate = 100.0 * sum(1 for r in scorable if r["mark"]["state"] == PASS) / len(scorable)
        print(f"\nstructural mark reliability: {rate:.1f}%  ({len(scorable)} scorable)")
    print("\nper class (mark):")
    by: dict[str, list[str]] = {}
    for r in gen:
        by.setdefault(r["class"], []).append(r["mark"]["state"])
    for k, v in sorted(by.items()):
        print(f"  {k:14} {v.count(PASS)}/{len(v)}"
              + (f"  FAIL={v.count(FAIL)}" if FAIL in v else ""))
    fails = [r for r in gen if r["mark"]["state"] == FAIL or r["face"]["state"] == FAIL]
    if fails:
        print("\nrows needing manual audit:")
        for r in fails:
            print(f"  {r['image']:34} mark={r['mark']['state']:12} face={r['face']['state']:12} "
                  f"viol={r['mark'].get('violations')} miss={r['mark'].get('missing')} "
                  f"cloth={r['mark'].get('on_clothing')} sim={r['face'].get('similarity')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="generate (default: dry run)")
    ap.add_argument("--pass", dest="pass_no", type=int, default=1)
    ap.add_argument("--out", default="soak_runs")
    args = ap.parse_args()

    rows = build_matrix()
    print(f"matrix rows: {len(rows)}  model={settings.GOOGLE_IMAGE_MODEL}  pass={args.pass_no}")
    for r in rows:
        print(f"  {r['character_id']:>3} {r['name']:8} {r['class']:13} {r['prompt']}")
    if not args.apply:
        print("\nDRY RUN — no generations.")
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    provider = GoogleImageProvider()
    cache: dict[int, tuple] = {}
    results = []
    for i, row in enumerate(rows, 1):
        cid = row["character_id"]
        if cid not in cache:
            canon = db.query(CharacterIdentityCanon).filter_by(character_id=cid).first()
            body = load_body_canon(canon)
            cache[cid] = (canon, mark_location_authority(body) or frozenset(),
                          load_image_bytes(load_face_canon(canon).face_front_image_url))
        canon, authority, face_ref = cache[cid]
        rec = run_row(row, canon, provider, authority, face_ref, out_dir, args.pass_no)
        results.append(rec)
        print(f"[{i}/{len(rows)}] {rec['name']:8} {rec['class']:13} "
              f"mark={rec['mark']['state']:12} face={rec['face']['state']:12} "
              f"viol={rec['mark'].get('violations')} miss={rec['mark'].get('missing')}",
              flush=True)
        (out_dir / f"results_pass{args.pass_no}.json").write_text(json.dumps(results, indent=2))
    db.close()
    summarise(results)
    print(f"\nartefacts: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
