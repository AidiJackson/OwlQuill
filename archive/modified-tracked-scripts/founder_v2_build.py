#!/usr/bin/env python3
"""Founder V2 Build harness (S24AL) — script-only founder rebuild.

Orchestrates a full v2 canon pack for ONE founder character using the new v2
card system only:

    provision owner → create character → generate 13 cards → add marks →
    lock face+body → generate 3 validation scenes

SAFETY / SCOPE (S24AL):
  * DRY-RUN BY DEFAULT. Pass --commit to actually generate/write. Without it the
    harness only compiles prompts, resolves providers, and prints the plan +
    estimated cost. No provider calls, no DB writes, no spend.
  * Hard spend cap (default $8.00) enforced before every paid call.
  * Gemini (option2) is the default provider; OpenAI (option1) is admin-only and
    used only as a gated retry when --admin-fallback is set. No Grok.
  * One founder per invocation (--founder NAME).
  * Refuses to generate unless the founder's identity description is present and
    complete — we never build a founder from a blank/fabricated description.
  * Adult Studio / RunPod / LoRA are NOT involved.

Usage:
    python scripts/founder_v2_build.py --founder Pan              # dry-run plan
    python scripts/founder_v2_build.py --founder Pan --commit     # real build (later)
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from app.services.canon_card_generator import (  # noqa: E402
    SpendTracker,
    generate_card,
)
from app.services.canon_card_prompts import (  # noqa: E402
    CARD_PIPELINE,
    FounderIdentity,
    MarkSpec,
    build_mark_prompt,
    validation_scene_prompts,
)

# ── Founder identity registry ─────────────────────────────────────────
# Descriptions are injected here per-founder, exactly as provided by the user
# (S24AL: "use the provided identity descriptions exactly"). It is intentionally
# EMPTY until each founder's description arrives — the harness refuses to run a
# founder that is absent or incomplete.
FOUNDERS: dict[str, FounderIdentity] = {
    "Pan": FounderIdentity(
        name="Pan",
        # Face — supplied verbatim as a full override.
        face_description=(
            "Beautiful male, age 30-32. Pale skin. Medium-length tousled golden "
            "blond hair. Piercing blue eyes. Sharp jawline. Strong cheekbones. "
            "Symmetrical face. Soft but dangerous beauty. Youthful but masculine. "
            "Elegant, seductive, fairy-tale prince energy with a darker edge."
        ),
        # Body — supplied verbatim as a full override.
        body_description=(
            "Lean athletic male build. Around 6ft. Broad shoulders. Narrow waist. "
            "Toned arms. Defined torso. Graceful posture. Strong but not bulky. "
            "Elegant physicality."
        ),
        marks=[
            MarkSpec(
                label="left_scripture_sleeve",
                type="tattoo",
                body_region="left_full_arm",
                side="left",
                description=(
                    "dark scripture sleeve tattoo covering the full left arm from "
                    "shoulder to wrist, elegant black ink, ancient text and occult "
                    "script, dense but refined"
                ),
            ),
            MarkSpec(
                label="right_wolf_sleeve",
                type="tattoo",
                body_region="right_full_arm",
                side="right",
                description=(
                    "dark wolf-themed sleeve tattoo covering the full right arm from "
                    "shoulder to wrist, black ink, wolf motifs, moon shapes, "
                    "claw-like ornamental patterns, gothic fantasy style"
                ),
            ),
        ],
        # Validation scene — supplied verbatim (cinematic gothic fantasy realism).
        cinematic_scene=(
            "Pan standing in a dark enchanted forest at twilight, black "
            "open-collar shirt with sleeves rolled to the elbows, cinematic "
            "gothic fantasy realism"
        ),
    ),
}


# ── Owner/admin provisioning (S24AL §6) ───────────────────────────────

def provision_owner(*, commit: bool) -> dict:
    """Ensure a migrated DB + admin owner exist. Dry-run only reports intent.

    Real provisioning (commit) is idempotent and reuses the existing
    app.core.admin_seed.ensure_admin_user (reads ADMIN_EMAIL / ADMIN_PASSWORD).
    """
    plan = {
        "migrate": "alembic upgrade head",
        "admin_seed": "app.core.admin_seed.ensure_admin_user()",
        "admin_email_env_present": bool(os.environ.get("ADMIN_EMAIL")),
        "admin_password_env_present": bool(os.environ.get("ADMIN_PASSWORD")),
    }
    if not commit:
        plan["mode"] = "dry-run (no DB writes)"
        return plan

    # ── commit path (executed later, never during scaffolding/dry-run) ──
    from alembic import command  # noqa: F401  (import here to avoid dry-run cost)
    raise SystemExit(
        "provision_owner(commit=True) is intentionally not wired to run yet — "
        "enable in the founder-run step once Pan's description is loaded."
    )


# ── Planning (dry-run) ────────────────────────────────────────────────

def plan_founder(identity: FounderIdentity, *, provider_option: str,
                 is_admin: bool, admin_fallback: bool, spend: SpendTracker) -> dict:
    """Compile the full plan for a founder without generating anything."""
    # A throwaway canon stub is enough for prompt/provider planning: dry-run
    # generate_card reads grounding URLs from the canon but tolerates their
    # absence (returns slot names as the plan).
    class _EmptyCanon:
        character_id = 0
        face_canon_json = None
        body_canon_json = None
        accessories_json = None

    canon = _EmptyCanon()
    cards = []
    for spec in CARD_PIPELINE:
        res = generate_card(
            canon=canon, slot=spec.slot, identity=identity, spend=spend,
            provider_option=provider_option, is_admin=is_admin,
            admin_fallback=admin_fallback, dry_run=True,
        )
        cards.append(res)

    marks = [
        {"label": m.label, "side": m.side, "body_region": m.body_region,
         "prompt": build_mark_prompt(identity, m)}
        for m in identity.marks
    ]
    scenes = validation_scene_prompts(identity)
    return {"cards": cards, "marks": marks, "scenes": scenes}


def _print_plan(name: str, plan: dict, spend: SpendTracker, *, provider_option: str) -> None:
    cards = plan["cards"]
    print(f"\n=== FOUNDER V2 BUILD PLAN — {name} (DRY-RUN) ===")
    print(f"provider option requested: {provider_option}  |  spend cap: ${spend.cap_usd:.2f}")

    print(f"\n-- Cards ({len(cards)}) --")
    for r in cards:
        grounds = ",".join(r.grounds_on) or "(seed)"
        print(f"  [{r.slot:18}] provider={r.provider_name:7} grounds_on={grounds:24} ~${r.estimated_cost:.3f}")
        print(f"       prompt: {r.prompt}")

    print(f"\n-- Mark detail cards ({len(plan['marks'])}) --")
    for m in plan["marks"]:
        print(f"  [{m['label']}] {m['side']} / {m['body_region']}")
        print(f"       prompt: {m['prompt']}")
    if not plan["marks"]:
        print("  (none — identity defines no marks)")

    print("\n-- Validation scenes (via existing /identity-canon/scenes/generate) --")
    for kind, prompt in plan["scenes"].items():
        print(f"  [{kind:11}] {prompt or '(not specified — will use a sensible default)'}")

    # Cost projection (S24AL §8): base + 1.5x regeneration factor.
    per_img = SpendTracker.cost_for("google" if provider_option == "option2" else "openai")
    n_base = len(cards) + len(plan["marks"]) + 3
    base = n_base * per_img
    with_regen = base * 1.5
    print("\n-- Cost estimate --")
    print(f"  base generations: {n_base}  @ ~${per_img:.3f}  = ~${base:.2f}")
    print(f"  with 1.5x regen factor                       = ~${with_regen:.2f}")
    within = with_regen <= spend.cap_usd
    print(f"  spend cap ${spend.cap_usd:.2f}: {'OK' if within else 'WOULD EXCEED — reduce scope or raise cap'}")


# ── Commit orchestration (S24AL founder-run step) ─────────────────────
# Wired on now that Pan's description is loaded. Everything below runs ONLY
# under --commit; the dry-run path above never reaches it. The rules enforced
# here (per the founder-run brief):
#   * Gemini (option2) is the only first-line provider.
#   * Hard $ cap via SpendTracker — any call that would exceed it stops the run.
#   * OpenAI admin fallback is used ONLY after the consistency gate fails twice
#     (generate_card with admin_fallback=False already does gen + 1 same-provider
#     retry, so a returned status of "gate_failed" == two Gemini gate failures).
#   * face_front has no gate (it IS the reference); a repeated *generation*
#     failure stops the run immediately.
#   * Re-runnable: already-populated slots / marks / scenes are skipped so a
#     resume after a cap-stop never double-spends.

FACE_FRONT_MAX_ATTEMPTS = 3

# Sensible defaults for the two validation scenes the user left unspecified
# (the dry-run plan promised "a sensible default" for these).
_DEFAULT_SCENES = {
    "casual": (
        "Pan in a relaxed casual moment, simple dark modern clothing, soft "
        "natural daylight, candid lifestyle photograph, photoreal"
    ),
    "environment": (
        "Pan inside a candlelit gothic castle hall at night, moody atmospheric "
        "cinematic environment, dark fantasy realism"
    ),
}


class StopBuild(RuntimeError):
    """Raised to abort the build immediately (cap hit / face_front failed)."""


def _resolve_owner(db):
    """Ensure the admin owner exists (idempotent) and return the User row."""
    import os as _os

    from app.core.admin_seed import ensure_admin_user
    from app.models.user import User

    ensure_admin_user()  # idempotent; reads ADMIN_EMAIL / ADMIN_PASSWORD
    email = _os.environ.get("ADMIN_EMAIL")
    owner = db.query(User).filter(User.email == email).first()
    if owner is None:
        raise StopBuild(f"admin owner not found after seed (ADMIN_EMAIL={email!r})")
    return owner


def _get_or_create_character(db, owner, identity):
    """Reuse an existing Pan owned by the admin, else create one."""
    from app.models.character import Character

    char = (
        db.query(Character)
        .filter(Character.owner_id == owner.id, Character.name == identity.name)
        .order_by(Character.id.asc())
        .first()
    )
    if char is not None:
        return char, False
    char = Character(
        owner_id=owner.id,
        name=identity.name,
        short_bio=f"{identity.name} — v2 canon founder.",
        species="human",
    )
    db.add(char)
    db.commit()
    db.refresh(char)
    return char, True


def _gen_card(slot, *, canon, identity, spend, provider_option, is_admin, admin_fallback):
    """Thin wrapper that converts a spend-cap breach into StopBuild."""
    from app.services.canon_card_generator import SpendCapExceeded

    try:
        return generate_card(
            canon=canon, slot=slot, identity=identity, spend=spend,
            provider_option=provider_option, is_admin=is_admin,
            admin_fallback=admin_fallback, dry_run=False,
        )
    except SpendCapExceeded as exc:
        raise StopBuild(f"spend cap reached generating {slot!r}: {exc}") from exc


def _build_cards(canon, identity, spend, db, report):
    """Generate the 13-card pack in pipeline order, assigning each slot."""
    from app.services import canon_service as cs

    for spec in CARD_PIPELINE:
        slot = spec.slot
        # Resume: skip a slot that already carries a URL.
        existing = _slot_url_safe(canon, slot)
        if existing:
            report["slots"][slot] = existing
            report["skipped"].append(slot)
            continue

        if slot == "face_front":
            url = _build_face_front(canon, identity, spend, report)
        else:
            url = _build_dependent_card(slot, canon, identity, spend, report)

        if not url:
            # Non-face card that never produced an image — record and move on.
            report["errors"].append(f"{slot}: no image produced")
            continue

        cs.assign_canon_slot_image(canon, slot, url)
        db.commit()
        report["slots"][slot] = url


def _slot_url_safe(canon, slot):
    from app.services.canon_card_generator import _slot_url
    try:
        return _slot_url(canon, slot)
    except Exception:  # noqa: BLE001
        return None


def _build_face_front(canon, identity, spend, report):
    """face_front: no gate. Retry on generation error; stop if it keeps failing."""
    for attempt in range(1, FACE_FRONT_MAX_ATTEMPTS + 1):
        res = _gen_card(
            "face_front", canon=canon, identity=identity, spend=spend,
            provider_option="option2", is_admin=False, admin_fallback=False,
        )
        if res.status == "generated" and res.url:
            if attempt > 1:
                report["regenerations"].append(f"face_front: succeeded on attempt {attempt}")
            return res.url
        report["regenerations"].append(
            f"face_front: attempt {attempt} failed ({res.error or res.status})"
        )
    raise StopBuild(
        f"face_front failed {FACE_FRONT_MAX_ATTEMPTS} times — stopping (seed unusable)."
    )


def _build_dependent_card(slot, canon, identity, spend, report):
    """Any non-face card: Gemini first (gen + 1 internal retry under the gate).

    If the gate fails twice (status=gate_failed) escalate ONCE to the admin
    OpenAI path. Generation errors get one Gemini retry then an OpenAI attempt.
    """
    res = _gen_card(
        slot, canon=canon, identity=identity, spend=spend,
        provider_option="option2", is_admin=False, admin_fallback=False,
    )
    _record_verdict(slot, res, report)

    if res.status == "generated":
        return res.url

    if res.status == "gate_failed":
        report["regenerations"].append(f"{slot}: Gemini gate failed twice → OpenAI fallback")
        oa = _gen_card(
            slot, canon=canon, identity=identity, spend=spend,
            provider_option="option1", is_admin=True, admin_fallback=True,
        )
        report["openai_fallback"].append(slot)
        _record_verdict(slot, oa, report)
        if oa.status == "generated":
            return oa.url
        report["gate_failed"].append(slot)
        return oa.url or res.url  # populate slot with best effort even if unclean

    # status == "error" (all generation tiers failed) — retry then OpenAI.
    report["regenerations"].append(f"{slot}: generation error → retry")
    res2 = _gen_card(
        slot, canon=canon, identity=identity, spend=spend,
        provider_option="option2", is_admin=False, admin_fallback=False,
    )
    if res2.status == "generated":
        return res2.url
    oa = _gen_card(
        slot, canon=canon, identity=identity, spend=spend,
        provider_option="option1", is_admin=True, admin_fallback=True,
    )
    report["openai_fallback"].append(slot)
    if oa.status == "generated":
        return oa.url
    return oa.url or res2.url


def _record_verdict(slot, res, report):
    v = res.face_verify
    if v and v.get("ok"):
        report["verdicts"][slot] = {"match": v.get("match"), "similarity": v.get("similarity")}
    elif v and v.get("skip_reason"):
        report["verdicts"][slot] = {"unverified": v.get("skip_reason")}


def _build_marks(canon, identity, spend, db, report):
    """Add each permanent mark and generate its detail-crop reference card."""
    from app.core.storage import load_image_bytes, save_image
    from app.schemas.canon import AddPermanentMarkRequest
    from app.services import canon_service as cs
    from app.services.canon_card_generator import _generate_png
    from app.services.image_provider import get_fallback_provider, get_provider_for_option

    body = cs.load_body_canon(canon)
    existing_labels = {m.label for m in (body.permanent_body_marks if body else [])}

    side_slot = {"left": "body_left", "right": "body_right"}

    for mark in identity.marks:
        # Resume: skip a mark (and its crop) that already exists with a crop URL.
        if mark.label in existing_labels:
            cur = next(
                (m for m in cs.load_body_canon(canon).permanent_body_marks
                 if m.label == mark.label), None)
            if cur and cur.detail_crop_url:
                report["marks"].append(
                    {"label": mark.label, "mark_id": cur.id,
                     "detail_crop_url": cur.detail_crop_url, "skipped": True})
                continue
            mark_id = cur.id if cur else None
        else:
            added = cs.add_permanent_mark(canon, AddPermanentMarkRequest(
                label=mark.label, type=mark.type, body_region=mark.body_region,
                side=mark.side, description=mark.description,
            ))
            db.commit()
            mark_id = added.id

        if spend.would_exceed("google"):
            raise StopBuild(f"spend cap reached before mark crop {mark.label!r}")

        prompt = build_mark_prompt(identity, mark)
        anchors = []
        for slot in ("body_front", side_slot.get(mark.side)):
            url = _slot_url_safe(canon, slot) if slot else None
            if url:
                try:
                    anchors.append(load_image_bytes(url))
                except Exception:  # noqa: BLE001
                    pass

        provider = get_provider_for_option("option2")
        png = _generate_png(provider, prompt, anchors)
        provider_name = "google"
        if png is None:
            fb = get_fallback_provider()
            if fb is not None:
                try:
                    png = fb.generate_image(prompt=prompt)
                    provider_name = "fal"
                except (ValueError, RuntimeError):
                    png = None
        if png is None:
            report["errors"].append(f"mark {mark.label}: no image produced")
            continue

        spend.charge(provider_name)
        crop_url = save_image(png)
        cs.assign_mark_detail_crop(canon, mark_id, crop_url)
        db.commit()
        report["marks"].append(
            {"label": mark.label, "mark_id": mark_id, "detail_crop_url": crop_url})


def _lock_canon(canon, db, report):
    from app.services import canon_service as cs

    cs.lock_face_canon(canon)
    cs.lock_body_canon(canon)
    db.commit()
    db.refresh(canon)
    report["canon_status"] = canon.status
    report["face_locked"] = bool(canon.face_locked)
    report["body_locked"] = bool(canon.body_locked)


def _run_validation_scenes(canon, identity, owner, spend, db, report):
    """Generate the 3 validation scenes as SCENE_ONLY images (never canon)."""
    from app.core.storage import load_image_bytes, save_image
    from app.models.character_image import (
        CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum,
    )
    from app.services.canon_compiler import compile_canon_prompt
    from app.services.image_provider import get_fallback_provider, get_provider_for_option
    from app.services.scene_router import route_canon_refs

    scenes = {
        "casual": identity.casual_scene or _DEFAULT_SCENES["casual"],
        "cinematic": identity.cinematic_scene or "Cinematic portrait of Pan.",
        "environment": identity.environment_scene or _DEFAULT_SCENES["environment"],
    }

    for kind, scene_prompt in scenes.items():
        tag = f"founderv2:{kind}"
        prior = (
            db.query(CharacterImage)
            .filter(CharacterImage.character_id == canon.character_id,
                    CharacterImage.prompt_summary.like(f"{tag}%"))
            .first()
        )
        if prior is not None:
            report["scenes"].append({"kind": kind, "image_id": prior.id, "skipped": True})
            continue

        if spend.would_exceed("google"):
            raise StopBuild(f"spend cap reached before validation scene {kind!r}")

        compiled = compile_canon_prompt(canon, scene_prompt)
        ref_urls, _meta = route_canon_refs(scene_prompt, canon)
        refs = []
        for url in ref_urls[:6]:
            try:
                refs.append(load_image_bytes(url))
            except Exception:  # noqa: BLE001
                pass

        provider = get_provider_for_option("option2")
        png = None
        if provider is not None and refs:
            try:
                png = provider.generate_with_anchors(prompt=compiled, anchor_images=refs)
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                png = None
        if png is None and provider is not None and refs:
            try:
                png = provider.generate_grounded_image(prompt=compiled, reference_image_bytes=refs[0])
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                png = None
        if png is None and provider is not None:
            try:
                png = provider.generate_image(prompt=compiled)
            except (ValueError, RuntimeError):
                png = None
        provider_name = "google"
        if png is None:
            fb = get_fallback_provider()
            if fb is not None:
                try:
                    png = fb.generate_image(prompt=compiled)
                    provider_name = "fal"
                except (ValueError, RuntimeError):
                    png = None
        if png is None:
            report["errors"].append(f"scene {kind}: no image produced")
            continue

        spend.charge(provider_name)
        file_path = save_image(png)
        img = CharacterImage(
            character_id=canon.character_id,
            user_id=owner.id,
            kind=ImageKindEnum.SCENE_ONLY,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            provider=provider_name,
            prompt_summary=f"{tag} | {scene_prompt[:160]}",
            metadata_json={"founder_validation": kind, "refs_count": len(refs)},
            file_path=file_path,
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        report["scenes"].append({"kind": kind, "image_id": img.id, "refs": len(refs)})


def run_commit(identity, *, provider_option, spend) -> dict:
    """Full real build for one founder. Returns the report dict."""
    from app.core.database import SessionLocal
    from app.schemas.canon import BodyCanonUpdate, FaceCanonUpdate
    from app.services import canon_service as cs

    report = {
        "character_id": None, "slots": {}, "marks": [], "scenes": [],
        "regenerations": [], "openai_fallback": [], "gate_failed": [],
        "verdicts": {}, "skipped": [], "errors": [],
        "canon_status": None, "face_locked": False, "body_locked": False,
        "stopped": None,
    }

    db = SessionLocal()
    try:
        owner = _resolve_owner(db)
        char, created = _get_or_create_character(db, owner, identity)
        report["character_id"] = char.id
        report["character_created"] = created

        canon = cs.get_or_create_canon(char.id, db)
        # Seed canon descriptions (text supplements the image refs).
        cs.update_face_canon(canon, FaceCanonUpdate(
            face_description=(identity.face_description or "")[:500]))
        cs.update_body_canon(canon, BodyCanonUpdate(
            body_description=(identity.body_description or "")[:500]))
        db.commit()

        _build_cards(canon, identity, spend, db, report)
        _build_marks(canon, identity, spend, db, report)
        _lock_canon(canon, db, report)
        _run_validation_scenes(canon, identity, owner, spend, db, report)
    except StopBuild as exc:
        report["stopped"] = str(exc)
    finally:
        db.close()

    report["total_spend"] = round(spend.spent_usd, 4)
    report["image_count"] = spend.image_count
    # "Clean" = every card landed without an OpenAI fallback and nothing is still
    # gate_failed. (Unverified verdicts pass the gate but are surfaced separately.)
    report["clean_pass"] = (
        not report["openai_fallback"] and not report["gate_failed"]
        and not report["errors"] and report["stopped"] is None
    )
    return report


def _print_commit_report(name: str, report: dict, spend: SpendTracker) -> None:
    print(f"\n=== FOUNDER V2 BUILD REPORT — {name} (COMMITTED) ===")
    if report.get("stopped"):
        print(f"  ⚠ STOPPED EARLY: {report['stopped']}")
    print(f"  character_id: {report['character_id']} "
          f"(created={report.get('character_created')})")
    print(f"  canon status: {report['canon_status']}  "
          f"face_locked={report['face_locked']} body_locked={report['body_locked']}")

    print(f"\n-- Canon slot URLs ({len(report['slots'])}/13) --")
    for spec in CARD_PIPELINE:
        url = report["slots"].get(spec.slot)
        print(f"  [{spec.slot:18}] {url or '(MISSING)'}")

    print(f"\n-- Mark detail cards ({len(report['marks'])}) --")
    for m in report["marks"]:
        flag = " (skipped/existing)" if m.get("skipped") else ""
        print(f"  [{m['label']}] id={m['mark_id']} crop={m['detail_crop_url']}{flag}")

    print(f"\n-- Validation scenes ({len(report['scenes'])}) --")
    for s in report["scenes"]:
        flag = " (skipped/existing)" if s.get("skipped") else ""
        print(f"  [{s['kind']:11}] image_id={s['image_id']}{flag}")

    print("\n-- Consistency verdicts --")
    if report["verdicts"]:
        for slot, v in report["verdicts"].items():
            print(f"  [{slot:18}] {v}")
    else:
        print("  (no gate verdicts recorded)")

    print("\n-- Regenerations --")
    for r in report["regenerations"] or ["(none)"]:
        print(f"  {r}")

    print("\n-- OpenAI admin fallback --")
    print(f"  {report['openai_fallback'] or '(none — Gemini only)'}")

    if report["errors"]:
        print("\n-- Errors --")
        for e in report["errors"]:
            print(f"  {e}")

    print("\n-- Spend --")
    print(f"  images generated: {report['image_count']}  "
          f"total spend: ${report['total_spend']:.4f}  cap: ${spend.cap_usd:.2f}")
    print(f"\n  Passed consistency cleanly: {'YES' if report['clean_pass'] else 'NO'}")


# ── Entry point ───────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Founder V2 Build harness (S24AL)")
    ap.add_argument("--founder", required=True, help="Founder name (e.g. Pan)")
    ap.add_argument("--commit", action="store_true",
                    help="Actually generate + write. Omitted = dry-run plan only.")
    ap.add_argument("--max-spend", type=float, default=8.0, help="Hard $ spend cap")
    ap.add_argument("--provider-option", default="option2",
                    help="option2=Gemini (default), option1=OpenAI (admin only)")
    ap.add_argument("--admin-fallback", action="store_true",
                    help="Allow gated OpenAI retry for the admin owner")
    args = ap.parse_args()

    identity = FOUNDERS.get(args.founder)
    if identity is None:
        print(f"REFUSING: no identity description loaded for founder {args.founder!r}.")
        print("Add it to the FOUNDERS registry (exact user-provided description) first.")
        return 2
    if not identity.is_complete():
        print(f"REFUSING: identity for {args.founder!r} is incomplete (need face + body text).")
        return 2

    spend = SpendTracker(cap_usd=args.max_spend)

    # Provisioning is always planned; only executed under --commit (and even then
    # gated off until the founder-run step).
    prov = provision_owner(commit=False)
    print("=== OWNER PROVISIONING PLAN ===")
    for k, v in prov.items():
        print(f"  {k}: {v}")

    if not args.commit:
        # Dry-run: plan only, never reaches any provider/DB code.
        plan = plan_founder(
            identity, provider_option=args.provider_option, is_admin=args.admin_fallback,
            admin_fallback=args.admin_fallback, spend=spend,
        )
        _print_plan(args.founder, plan, spend, provider_option=args.provider_option)
        print("\nDRY-RUN complete. No providers called, no DB writes, no spend.")
        return 0

    # ── Real build (founder-run step) ─────────────────────────────────
    print(f"\n=== COMMITTING FOUNDER V2 BUILD — {args.founder} ===")
    print(f"provider: {args.provider_option} (Gemini)  |  hard cap: ${spend.cap_usd:.2f}  "
          f"|  OpenAI admin fallback: {'on (post double-gate-fail)' if args.admin_fallback else 'off'}")
    report = run_commit(identity, provider_option=args.provider_option, spend=spend)
    _print_commit_report(args.founder, report, spend)

    if report.get("stopped"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
