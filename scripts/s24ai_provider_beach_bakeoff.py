#!/usr/bin/env python3
"""S24AI — Admin Provider Beach/Bikini Bakeoff.

Generates each of 4 Summer beach/fashion prompts ONCE per provider
(Gemini/Google, OpenAI, Grok) through the REAL canon image-generator route
(`generate_image`), so identity refs, canon compilation, scene routing and the
S24AD ref-less-fallback safety are all exercised exactly as in production.

Each successful result is already persisted by the route as a PRIVATE,
SCENE_ONLY CharacterImage. This harness then stamps metadata.source=
"provider_bakeoff" (+ bakeoff bookkeeping) so the images are identifiable test
images in Summer's library. Failures/refusals (e.g. Gemini google_refused_image
→ S24AD 422) are recorded, not retried.

Admin-only, read-mostly: NO app defaults are mutated persistently. The only
runtime override is IDENTITY_FACE_VERIFY=False for THIS process, so each prompt
is a single clean generation per provider ("once per provider"), not a
verify+regenerate pair.

Run from backend/:
    cd backend && python3 ../scripts/s24ai_provider_beach_bakeoff.py
Env knobs (optional):
    S24AI_PROVIDERS=option2,option1,option6   # subset/order of providers
    S24AI_PROMPTS=1,3                          # subset of prompt indices (1-4)
    S24AI_DRY_RUN=1                            # plan only, no generation
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

SUMMER_ID = 60
REPORT_DIR = os.path.join(HERE, "s24ai_reports")

# provider_option → human label (mapping per image_provider.get_provider_for_option)
PROVIDERS = [
    ("option2", "google_gemini"),
    ("option1", "openai"),
    ("option6", "grok"),
]

PROMPTS = [
    "Summer on a beach at sunset wearing a flowing gold summer gown, cinematic natural light",
    "Summer on a beach at sunset wearing a white tank top and denim shorts, cinematic natural light",
    "Summer on a beach at sunset wearing a white bikini, cinematic natural light",
    "Summer in a fashion editorial shoot on a sunny coastal street, elegant summer outfit, natural light",
]


def log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _select(env: str, default_indices):
    raw = os.environ.get(env, "").strip()
    if not raw:
        return default_indices
    return [int(x) for x in raw.replace(" ", "").split(",") if x]


def main() -> int:
    from fastapi import HTTPException

    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.character import Character
    from app.models.character_image import CharacterImage
    from app.models.user import User
    from app.api.routes.image_generator import ImageGenerateRequest, generate_image

    dry = os.environ.get("S24AI_DRY_RUN") == "1"

    # Single clean generation per provider (no verify+regenerate). Runtime-only.
    settings.IDENTITY_FACE_VERIFY = False

    prov_filter = os.environ.get("S24AI_PROVIDERS", "").strip()
    providers = (
        [(o, l) for (o, l) in PROVIDERS if o in prov_filter.split(",")]
        if prov_filter else list(PROVIDERS)
    )
    prompt_idx = _select("S24AI_PROMPTS", list(range(1, len(PROMPTS) + 1)))

    db = SessionLocal()
    results: list[dict] = []
    try:
        char = db.query(Character).filter(Character.id == SUMMER_ID).first()
        if not char:
            raise SystemExit(f"character {SUMMER_ID} not found")
        owner = db.query(User).filter(User.id == char.owner_id).first()
        if not owner:
            raise SystemExit(f"owner {char.owner_id} not found")
        log(f"character={char.name!r} owner={owner.email} is_admin={owner.is_admin}")
        if not owner.is_admin:
            raise SystemExit("owner is not admin — admin-only providers (option1/6) would be gated")
        log(f"providers={[l for _, l in providers]} prompts={prompt_idx} "
            f"face_verify={settings.IDENTITY_FACE_VERIFY} dry_run={dry}")

        # Actual model slug per provider (route metadata only carries model for
        # FLUX adapters, so resolve from settings for an accurate audit trail).
        model_for = {
            "openai": settings.IMAGE_MODEL,
            "google_gemini": settings.GOOGLE_IMAGE_MODEL,
            "grok": settings.OPENROUTER_GROK_IMAGE_MODEL,
        }

        for opt, label in providers:
            for i in prompt_idx:
                prompt = PROMPTS[i - 1]
                rec: dict = {
                    "provider_option": opt, "provider_label": label,
                    "prompt_index": i, "prompt": prompt,
                }
                if dry:
                    log(f"DRY {label} p{i}: would generate {prompt[:50]}...")
                    rec["status"] = "dry_run"
                    results.append(rec)
                    continue
                log(f"GEN {label} p{i}: {prompt[:60]}...")
                t0 = time.time()
                try:
                    body = ImageGenerateRequest(
                        prompt=prompt,
                        include_character=True,
                        provider_option=opt,  # type: ignore[arg-type]
                        is_cover=False,
                    )
                    read = generate_image(SUMMER_ID, body, current_user=owner, db=db)
                    img = db.query(CharacterImage).filter(CharacterImage.id == read.id).first()
                    meta = dict(img.metadata_json or {})
                    meta["source"] = "provider_bakeoff"
                    meta["bakeoff_sprint"] = "S24AI"
                    meta["bakeoff_provider_label"] = label
                    meta["bakeoff_prompt_index"] = i
                    img.metadata_json = meta
                    db.add(img)
                    db.commit()
                    db.refresh(img)
                    rec.update({
                        "status": "ok",
                        "image_id": img.id,
                        "actual_provider": meta.get("provider"),
                        "model": meta.get("model") or model_for.get(label),
                        "multi_image_used": meta.get("multi_image_used"),
                        "used_ref": meta.get("used_ref"),
                        "refs_count": meta.get("refs_count"),
                        "refs_not_used_reason": meta.get("refs_not_used_reason"),
                        "visibility": img.visibility.value if hasattr(img.visibility, "value") else str(img.visibility),
                        "kind": img.kind.value if hasattr(img.kind, "value") else str(img.kind),
                        "file_path": img.file_path,
                        "elapsed_s": round(time.time() - t0, 1),
                    })
                    log(f"  OK image_id={img.id} provider={meta.get('provider')} "
                        f"multi={meta.get('multi_image_used')} used_ref={meta.get('used_ref')} "
                        f"refs={meta.get('refs_count')} {rec['elapsed_s']}s")
                except HTTPException as exc:
                    db.rollback()
                    refused = "refused" if exc.status_code == 422 else "failed"
                    rec.update({
                        "status": refused, "http_status": exc.status_code,
                        "detail": str(exc.detail), "elapsed_s": round(time.time() - t0, 1),
                    })
                    log(f"  {refused.upper()} http={exc.status_code} detail={exc.detail!r}")
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    rec.update({
                        "status": "error", "error": str(exc)[:300],
                        "elapsed_s": round(time.time() - t0, 1),
                    })
                    log(f"  ERROR {exc!r}")
                    traceback.print_exc()
                results.append(rec)
    finally:
        db.close()

    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(REPORT_DIR, f"bakeoff_{stamp}.json")
    with open(out, "w") as f:
        json.dump({"sprint": "S24AI", "character_id": SUMMER_ID, "results": results}, f, indent=2)
    log(f"\nwrote {out}")

    # Console summary grouped by provider/prompt.
    print("\n" + "=" * 78)
    print("S24AI BAKEOFF SUMMARY — image ids grouped by provider/prompt")
    print("=" * 78)
    for _, label in providers:
        print(f"\n[{label}]")
        for r in results:
            if r["provider_label"] != label:
                continue
            if r.get("status") == "ok":
                print(f"  p{r['prompt_index']} → image_id={r['image_id']:<6} "
                      f"multi={r.get('multi_image_used')} used_ref={r.get('used_ref')} "
                      f"refs={r.get('refs_count')}")
            else:
                print(f"  p{r['prompt_index']} → {r.get('status').upper()} "
                      f"{r.get('http_status','') or ''} {r.get('detail') or r.get('error') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
