"""V2 canon pack builder (S24AN).

Orchestrates a full v2 canon pack (the 13 face/body cards + permanent-mark
detail crops) for ONE character, and is the engine behind the self-serve
creation endpoint POST /characters/{id}/identity-canon/generate-v2-pack.

This replaces the legacy 4-anchor identity-pack path for new users: instead of
generating 4 anchors and bridging a subset into canon, it populates ALL 13 v2
canon slots directly via canon_card_generator (the grounded card pipeline).

Safety / policy (mirrors scripts/founder_v2_build.py, the founder-run harness):
  * Gemini (option2) is the only first-line provider.
  * Hard $ cap via SpendTracker — any call that would exceed it stops the run.
  * OpenAI admin fallback is used ONLY after the consistency gate fails twice
    (generate_card with admin_fallback=False already does gen + 1 same-provider
    retry, so a returned status of "gate_failed" == two Gemini gate failures).
  * face_front has no gate (it IS the reference); a repeated generation failure
    stops the run.
  * Re-runnable: already-populated slots / cropped marks are skipped, so a
    resume (or a regenerate of a partially-built canon) never double-spends.
  * Does NOT lock the canon — locking is a separate, explicit step (the creation
    flow's Dossier step calls face/lock + body/lock).
  * No Adult Studio, no RunPod, no LoRA.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Optional

from app.schemas.canon import AddPermanentMarkRequest
from app.services import canon_service as cs
from app.services.canon_card_generator import (
    SpendCapExceeded,
    SpendTracker,
    _generate_png,
    _slot_url,
    generate_card,
)
from app.services.canon_card_prompts import (
    CARD_PIPELINE,
    FounderIdentity,
    MarkSpec,
    build_mark_prompt,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.character import Character
    from app.models.character_identity_canon import CharacterIdentityCanon

logger = logging.getLogger(__name__)

FACE_FRONT_MAX_ATTEMPTS = 3
DEFAULT_MAX_SPEND_USD = 8.0

# Grouping for the review UI — keep the slot→section mapping in one place so the
# frontend and the dry-run plan agree on what "Face" / "Body" mean.
FACE_SLOTS = ("face_front", "face_left_3q", "face_right_3q", "face_profile", "face_expression")
BODY_SLOTS = ("body_front", "body_left", "body_right", "body_back",
              "torso_front", "torso_side", "standing_relaxed", "seated_relaxed")


class _StopBuild(RuntimeError):
    """Internal: abort the build immediately (cap hit / face_front failed)."""


# ── Identity assembly ─────────────────────────────────────────────────

def _spec_face_description(spec: dict) -> str:
    """Compose a face description line from a CharacterIdentitySpec dict.

    Age/gender are intentionally NOT included here — build_preamble already
    leads with "name, age gender", so this returns facial features only to
    avoid duplication.
    """
    ident = spec.get("identity") or {}
    bits: list[str] = []
    if ident.get("skin_tone"):
        bits.append(f"{ident['skin_tone']} skin")
    # Hair: texture + length + colour + styled cut (B15). Preserves the
    # characterful hair the user chose instead of flattening to colour only.
    hair_core = " ".join(
        b for b in (spec.get("hair_texture"), ident.get("hair_length"), ident.get("hair_color")) if b
    )
    if hair_core:
        bits.append(f"{hair_core} hair")
    style = spec.get("hair_style")
    if style and style != "none":
        bits.append(f"{str(style).replace('_', ' ')} hairstyle")
    if ident.get("eye_color"):
        bits.append(f"{ident['eye_color']} eyes")
    feats = ident.get("face_features") or []
    if isinstance(feats, list):
        bits.extend(feats)
    # Facial geometry — labelled so it reads as appealing detail, not a bare
    # adjective list ("oval face, high cheekbones" not "oval, high").
    geometry = (
        ("face_shape", "{} face"),
        ("jaw_type", "{} jaw"),
        ("cheekbone_type", "{} cheekbones"),
        ("eye_shape", "{} eyes"),
        ("eyebrow_shape", "{} eyebrows"),
        ("nose_type", "{} nose"),
        ("lip_type", "{} lips"),
        ("facial_hair_type", "{} facial hair"),
    )
    for key, tmpl in geometry:
        v = spec.get(key)
        if v and v != "none":
            bits.append(tmpl.format(str(v).replace("_", " ")))
    tells = spec.get("species_tells") or []
    if isinstance(tells, list):
        bits.extend(t.replace("_", " ") for t in tells)
    return ", ".join(b for b in bits if b)


def _spec_body_description(spec: dict) -> str:
    build = spec.get("build") or {}
    bits: list[str] = []
    bt = build.get("body_type") or spec.get("body_build")
    if bt:
        bits.append(f"{bt} build")
    hb = build.get("height_band") or spec.get("body_height")
    if hb:
        bits.append(f"{hb} height")
    return ", ".join(b for b in bits if b)


def founder_identity_from_character(
    character: "Character", canon: "CharacterIdentityCanon", db: "Session",
) -> FounderIdentity:
    """Build a FounderIdentity from a character's DNA / identity spec / canon.

    Priority for the description text: existing canon descriptions → identity
    spec → DNA visual traits. We never invent values; an under-specified
    character simply gets a thinner (but still usable) preamble.
    """
    face = cs.load_face_canon(canon)
    body = cs.load_body_canon(canon)

    # Identity spec (richest source) if the character carries one.
    spec: dict = {}
    if character.identity_spec_json:
        try:
            spec = json.loads(character.identity_spec_json) or {}
        except (ValueError, TypeError):
            spec = {}

    # DNA fallback.
    dna = None
    try:
        from app.models.character_dna import CharacterDNA
        dna = db.query(CharacterDNA).filter(CharacterDNA.character_id == character.id).first()
    except Exception:  # noqa: BLE001
        dna = None

    # The self-serve creation flow stores the rich identity spec inside the DNA
    # (visual_traits_json["identity_spec"]); character.identity_spec_json is only
    # populated by other flows. Without this fallback the user's entire facial
    # appearance intent (hair, eyes, geometry, vibe) is dropped and cards come
    # out generic (S24AT root cause).
    if not spec and dna and dna.visual_traits_json:
        spec = (dna.visual_traits_json or {}).get("identity_spec") or {}

    face_desc = (face.face_description if face and face.face_description else "") or \
        _spec_face_description(spec)
    body_desc = (body.body_description if body and body.body_description else "") or \
        _spec_body_description(spec)

    # Fold in morphology persisted on the canon body (set by the creation UI's
    # Body Identity controls) when the text is otherwise thin.
    if body:
        morph = []
        if body.build and "build" not in (body_desc or "").lower():
            morph.append(f"{body.build} build")
        if body.height and "height" not in (body_desc or "").lower():
            morph.append(f"{body.height} height")
        if morph:
            body_desc = ", ".join(b for b in (body_desc, ", ".join(morph)) if b)

    # DNA visual-trait fallback when neither canon nor spec provided text.
    if not face_desc and dna and dna.visual_traits_json:
        vt = dna.visual_traits_json or {}
        face_desc = ", ".join(
            b for b in (vt.get("skin_tone"), vt.get("hair_color"), vt.get("eye_color")) if b
        )
    if not body_desc and dna and dna.structural_profile_json:
        sp = dna.structural_profile_json or {}
        body_desc = ", ".join(
            b for b in (sp.get("body_type_category"), sp.get("age_band")) if b
        )

    gender = spec.get("gender") or (dna.gender_presentation if dna else "") or ""
    age_band = spec.get("age_band") or ""

    # Character vibe — personality traits + free-text vibe from the DNA. Keeps the
    # roleplay/fantasy flavour in the prompt so cards feel characterful (S24AT).
    vibe = ""
    if dna and dna.visual_traits_json:
        vt = dna.visual_traits_json or {}
        traits = vt.get("personality_traits") or []
        vibe_bits: list[str] = []
        if isinstance(traits, list) and traits:
            vibe_bits.append(", ".join(str(t) for t in traits if t))
        if vt.get("vibe"):
            vibe_bits.append(str(vt["vibe"]))
        vibe = "; ".join(b for b in vibe_bits if b)

    return FounderIdentity(
        name=character.name,
        gender=gender,
        age_band=age_band,
        face_description=face_desc or None,
        body_description=body_desc or None,
        vibe=vibe,
        # Marks come from the canon body (added via CanonManager / API), not the
        # spec — they are anatomical truth and own the detail-crop pipeline.
        marks=[],
    )


# ── Card generation ───────────────────────────────────────────────────

def _slot_url_safe(canon, slot) -> Optional[str]:
    try:
        return _slot_url(canon, slot)
    except Exception:  # noqa: BLE001
        return None


def _gen_card(slot, *, canon, identity, spend, provider_option, is_admin, admin_fallback):
    try:
        return generate_card(
            canon=canon, slot=slot, identity=identity, spend=spend,
            provider_option=provider_option, is_admin=is_admin,
            admin_fallback=admin_fallback, dry_run=False,
        )
    except SpendCapExceeded as exc:
        raise _StopBuild(f"spend cap reached generating {slot!r}: {exc}") from exc


def _record_verdict(slot, res, report):
    v = res.face_verify
    if v and v.get("ok"):
        report["verdicts"][slot] = {"match": v.get("match"), "similarity": v.get("similarity")}
    elif v and v.get("skip_reason"):
        report["verdicts"][slot] = {"unverified": v.get("skip_reason")}


def _build_face_front(canon, identity, spend, report):
    for attempt in range(1, FACE_FRONT_MAX_ATTEMPTS + 1):
        res = _gen_card("face_front", canon=canon, identity=identity, spend=spend,
                        provider_option="option2", is_admin=False, admin_fallback=False)
        if res.status == "generated" and res.url:
            if attempt > 1:
                report["regenerations"].append(f"face_front: succeeded on attempt {attempt}")
            return res.url
        report["regenerations"].append(
            f"face_front: attempt {attempt} failed ({res.error or res.status})")
    raise _StopBuild(f"face_front failed {FACE_FRONT_MAX_ATTEMPTS} times (seed unusable)")


def _build_dependent_card(slot, canon, identity, spend, report, *, is_admin, admin_fallback):
    res = _gen_card(slot, canon=canon, identity=identity, spend=spend,
                    provider_option="option2", is_admin=False, admin_fallback=False)
    _record_verdict(slot, res, report)

    if res.status == "generated":
        return res.url

    if res.status == "gate_failed":
        # Gate failed twice on Gemini → escalate to admin OpenAI, if permitted.
        if admin_fallback and is_admin:
            report["regenerations"].append(f"{slot}: Gemini gate failed twice → OpenAI fallback")
            oa = _gen_card(slot, canon=canon, identity=identity, spend=spend,
                           provider_option="option1", is_admin=True, admin_fallback=True)
            report["openai_fallback"].append(slot)
            _record_verdict(slot, oa, report)
            if oa.status == "generated":
                return oa.url
            report["gate_failed"].append(slot)
            return oa.url or res.url
        report["gate_failed"].append(slot)
        return res.url  # populate slot best-effort; flagged not-clean

    # status == "error": one Gemini retry, then OpenAI if permitted.
    report["regenerations"].append(f"{slot}: generation error → retry")
    res2 = _gen_card(slot, canon=canon, identity=identity, spend=spend,
                     provider_option="option2", is_admin=False, admin_fallback=False)
    if res2.status == "generated":
        return res2.url
    if admin_fallback and is_admin:
        oa = _gen_card(slot, canon=canon, identity=identity, spend=spend,
                       provider_option="option1", is_admin=True, admin_fallback=True)
        report["openai_fallback"].append(slot)
        if oa.status == "generated":
            return oa.url
        return oa.url or res2.url
    return res2.url


def _build_marks(canon, identity, spend, db, report, *, dry_run):
    """Generate a detail crop for each permanent mark lacking one."""
    from app.core.storage import load_image_bytes, save_image
    from app.services.image_provider import get_fallback_provider, get_provider_for_option

    body = cs.load_body_canon(canon)
    marks = list(body.permanent_body_marks) if body else []
    side_slot = {"left": "body_left", "right": "body_right"}

    for mark in marks:
        if mark.detail_crop_url:
            report["marks"].append({"label": mark.label, "mark_id": mark.id,
                                    "detail_crop_url": mark.detail_crop_url, "skipped": True})
            continue

        ms = MarkSpec(label=mark.label, type=mark.type, body_region=mark.body_region,
                      side=mark.side, description=mark.description)
        prompt = build_mark_prompt(identity, ms)

        if dry_run:
            report["marks"].append({"label": mark.label, "mark_id": mark.id,
                                    "detail_crop_url": None, "prompt": prompt,
                                    "estimated_cost": SpendTracker.cost_for("google")})
            continue

        if spend.would_exceed("google"):
            raise _StopBuild(f"spend cap reached before mark crop {mark.label!r}")

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
        cs.assign_mark_detail_crop(canon, mark.id, crop_url)
        db.commit()
        report["marks"].append({"label": mark.label, "mark_id": mark.id,
                                "detail_crop_url": crop_url})


# ── Public entry ──────────────────────────────────────────────────────

def build_v2_pack(
    *,
    canon: "CharacterIdentityCanon",
    identity: FounderIdentity,
    db: "Session",
    spend: SpendTracker,
    provider_option: str = "option2",
    is_admin: bool = False,
    admin_fallback: bool = False,
    dry_run: bool = True,
    on_progress=None,
) -> dict:
    """Generate (or, in dry-run, plan) the full v2 canon pack for one character.

    Returns a report dict. Slots are assigned + committed as they generate so
    dependent cards can ground on them; the canon is NOT locked here.

    ``on_progress(stage_key, done, total)`` — optional callback fired at real
    pipeline boundaries (Sprint 35 async jobs): once per card slot before it
    generates (``"card:<slot>"``) and once before mark detail crops
    (``"mark_details"``). Failures inside the callback never break the build.
    """
    def _progress(stage_key: str, done: int, total: int) -> None:
        if on_progress is None:
            return
        try:
            on_progress(stage_key, done, total)
        except Exception:  # noqa: BLE001 — progress is observability, never fatal
            logger.warning("v2_pack on_progress callback failed", exc_info=True)

    report: dict = {
        "pack_id": uuid.uuid4().hex,
        "dry_run": dry_run,
        "cards": [],
        "marks": [],
        "verdicts": {},
        "regenerations": [],
        "openai_fallback": [],
        "gate_failed": [],
        "errors": [],
        "skipped": [],
        "stopped": None,
    }

    _total_cards = len(CARD_PIPELINE)

    try:
        for _card_idx, spec in enumerate(CARD_PIPELINE):
            slot = spec.slot
            section = "face" if slot in FACE_SLOTS else "body"
            _progress(f"card:{slot}", _card_idx, _total_cards)

            if dry_run:
                res = generate_card(
                    canon=canon, slot=slot, identity=identity, spend=spend,
                    provider_option=provider_option, is_admin=is_admin,
                    admin_fallback=admin_fallback, dry_run=True,
                )
                report["cards"].append({
                    "slot": slot, "section": section, "role": slot,
                    "url": None, "status": "planned",
                    "provider": res.provider_name, "grounds_on": list(res.grounds_on),
                    "prompt": res.prompt, "estimated_cost": res.estimated_cost,
                })
                continue

            existing = _slot_url_safe(canon, slot)
            if existing:
                report["skipped"].append(slot)
                report["cards"].append({"slot": slot, "section": section, "role": slot,
                                        "url": existing, "status": "skipped",
                                        "provider": None})
                continue

            if slot == "face_front":
                url = _build_face_front(canon, identity, spend, report)
            else:
                url = _build_dependent_card(slot, canon, identity, spend, report,
                                            is_admin=is_admin, admin_fallback=admin_fallback)

            if not url:
                report["errors"].append(f"{slot}: no image produced")
                report["cards"].append({"slot": slot, "section": section, "role": slot,
                                        "url": None, "status": "error", "provider": None})
                continue

            cs.assign_canon_slot_image(canon, slot, url)
            db.commit()
            status = "gate_failed" if slot in report["gate_failed"] else "generated"
            report["cards"].append({
                "slot": slot, "section": section, "role": slot, "url": url,
                "status": status, "provider": "openai" if slot in report["openai_fallback"] else "google",
                "similarity": (report["verdicts"].get(slot) or {}).get("similarity"),
            })

        _progress("mark_details", _total_cards, _total_cards)
        _build_marks(canon, identity, spend, db, report, dry_run=dry_run)

    except _StopBuild as exc:
        report["stopped"] = str(exc)

    report["total_spend"] = round(spend.spent_usd, 4)
    report["image_count"] = spend.image_count
    if dry_run:
        per = SpendTracker.cost_for("google" if provider_option == "option2" else "openai")
        n = len(report["cards"]) + len(report["marks"])
        report["estimated_cost"] = round(n * per * 1.5, 2)  # +50% regen headroom
    report["clean_pass"] = (
        not report["openai_fallback"] and not report["gate_failed"]
        and not report["errors"] and report["stopped"] is None
    )
    return report
