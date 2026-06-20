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

    plan = plan_founder(
        identity, provider_option=args.provider_option, is_admin=args.admin_fallback,
        admin_fallback=args.admin_fallback, spend=spend,
    )
    _print_plan(args.founder, plan, spend, provider_option=args.provider_option)

    if args.commit:
        print("\n--commit was requested, but the commit path is intentionally not "
              "enabled in this scaffolding step. Wire it on in the founder-run step.")
        return 1

    print("\nDRY-RUN complete. No providers called, no DB writes, no spend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
