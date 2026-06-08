#!/usr/bin/env python3
"""Dry-run Adult Studio tattoo-enforcement PLAN validator — Summer only (Phase 3, S6).

Proves that Summer (character_id=60) has a COMPLETE, internally-consistent tattoo-
enforcement plan that an executor *could* run — WITHOUT running anything. It assembles
the plan from the persisted Adult Studio records (identity + active LoRA version + mark
renders + reference crops + routes) and validates completeness.

Strictly read-only. NO generation, NO inference, NO training, NO provider construction,
NO Replicate / RunPod / ComfyUI, NO external calls, NO Canon Studio access, NO writes.
$0 spend by construction (nothing leaves the process except the report file).

Summer expectations asserted:
  - butterfly/floral sleeve (Right upper arm) → ip_adapter
  - ballerina (Left forearm)                  → controlnet_canny

Writes scripts/summer_adult_studio_enforcement_plan_report.json. Exit 0 iff
ready_for_executor is True.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.database import SessionLocal  # noqa: E402
from app.models.adult_identity import AdultIdentityModel  # noqa: E402
from app.models.character import Character  # noqa: E402
from app.services.adult_identity_enforcement_plan import (  # noqa: E402
    build_enforcement_plan,
)

EXPECTED_CHARACTER_ID = 60  # Summer ONLY
# Substring-of-reason → expected route. The router records butterfly/floral as a
# "sleeve/coverage" match and the ballerina as a "ballerina" figural match.
SUMMER_ROUTE_EXPECTATIONS = {"sleeve": "ip_adapter", "ballerina": "controlnet_canny"}
REPORT = Path(__file__).resolve().parent / "summer_adult_studio_enforcement_plan_report.json"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _enforce_summer(db):
    """Refuse to validate anything but Summer (character_id=60)."""
    ch = db.get(Character, EXPECTED_CHARACTER_ID)
    if ch is None:
        raise SystemExit(f"FATAL: character {EXPECTED_CHARACTER_ID} (Summer) not found")
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == EXPECTED_CHARACTER_ID)
        .first()
    )
    if model is None:
        raise SystemExit("FATAL: Summer has no AdultIdentityModel")
    return ch.name


def main():
    db = SessionLocal()
    try:
        name = _enforce_summer(db)
        log(f"target: {name} (character_id={EXPECTED_CHARACTER_ID}) — DRY RUN, no spend")
        plan = build_enforcement_plan(
            EXPECTED_CHARACTER_ID, db, route_expectations=SUMMER_ROUTE_EXPECTATIONS
        )
    finally:
        db.close()

    REPORT.write_text(json.dumps(plan, indent=2))
    log(f"identity_id={plan['identity_id']} status={plan['status']} "
        f"active_version_id={plan['active_version_id']}")
    log(f"model_artifact_uri={'present' if plan['model_artifact_uri'] else 'MISSING'}")
    for m in plan["marks"]:
        log(f"  mark {m['canon_mark_id']} [{m['region']}/{m['side']}] -> {m['route']} "
            f"(ref={'yes' if m['reference_uri'] else 'NO'})")
    log("CHECKS: " + json.dumps(plan["checks"]))
    log(f"ready_for_executor={plan['ready_for_executor']}")
    if plan["blocking_reasons"]:
        for r in plan["blocking_reasons"]:
            log(f"  BLOCKED: {r}")
    log("REPORT written: " + REPORT.name)
    print(json.dumps(plan, indent=2), flush=True)
    sys.exit(0 if plan["ready_for_executor"] else 1)


if __name__ == "__main__":
    main()
