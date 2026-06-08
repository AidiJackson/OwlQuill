"""Adult Studio tattoo-enforcement PLAN validator (Phase 3, Sprint 6).

A strictly **dry-run, read-only** assembler. It joins the persisted Adult Studio
records into the full tattoo-enforcement plan an executor *would* run, and validates
that the plan is complete and internally consistent — WITHOUT running anything.

It assembles from:
  - AdultIdentityModel              (identity + lifecycle status)
  - active AdultIdentityModelVersion (the LoRA artifact = model_artifact_uri)
  - AdultIdentityMarkRender rows     (per-mark route + reference crop + reason)

It validates:
  - identity status == "ready"
  - active_version_id exists and resolves to a version
  - model_artifact_uri (active version lora_weights_uri) exists
  - at least one mark render exists to enforce
  - every mark render has a reference_uri (no missing references)
  - every route is executor-supported (ip_adapter / controlnet_canny / inpaint_direct)
  - optional route expectations hold (e.g. butterfly→ip_adapter, ballerina→controlnet_canny)

It NEVER: trains, generates, runs inference, constructs a provider, calls Replicate /
RunPod / ComfyUI, or writes ANY table (no Canon Studio access at all — it reads only
adult_identity_* rows that prepare already persisted). The output is a plan + a single
``ready_for_executor`` boolean + actionable ``blocking_reasons``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# The lifecycle status an identity must be in to be servable for enforcement.
REQUIRED_STATUS = "ready"

# Routes a tattoo-enforcement executor can actually run. "hybrid"/"skip" are valid
# routing vocabulary but are NOT enforceable passes, so they block an enforcement plan.
EXECUTOR_SUPPORTED_ROUTES = frozenset({"ip_adapter", "controlnet_canny", "inpaint_direct"})


def _reason(r: AdultIdentityMarkRender) -> Optional[str]:
    return (r.params_json or {}).get("reason")


def _mark_dict(r: AdultIdentityMarkRender) -> dict[str, Any]:
    return {
        "canon_mark_id": r.canon_mark_id,
        "region": r.body_region,
        "side": r.side,
        "route": r.route,
        "reference_uri": r.reference_uri,
        "reason": _reason(r),
        "mark_fingerprint": r.mark_fingerprint,
    }


def _empty_plan(character_id: int, reason: str) -> dict[str, Any]:
    return {
        "character_id": character_id,
        "identity_id": None,
        "status": None,
        "active_version_id": None,
        "model_artifact_uri": None,
        "marks": [],
        "checks": {
            "identity_exists": False,
            "status_ready": False,
            "active_version_present": False,
            "model_artifact_present": False,
            "has_mark_renders": False,
            "all_references_present": False,
            "all_routes_supported": False,
            "route_expectations_met": True,
        },
        "executor_required": True,
        "ready_for_executor": False,
        "blocking_reasons": [reason],
    }


def build_enforcement_plan(
    character_id: int,
    db: "Session",
    *,
    route_expectations: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Assemble + validate the dry-run tattoo-enforcement plan for a character.

    ``route_expectations`` (optional) maps a case-insensitive substring → expected
    route. A mark whose ``reason`` contains the substring must carry that route, else
    it blocks. Summer passes ``{"sleeve": "ip_adapter", "ballerina": "controlnet_canny"}``
    to assert butterfly→ip_adapter and ballerina→controlnet_canny.

    Pure read-only. No writes, no provider, no generation, no external calls.
    """
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if model is None:
        return _empty_plan(character_id, "no Adult Studio identity exists for this character")

    # ── Resolve active version + artifact URI ────────────────────────────────
    active_version: Optional[AdultIdentityModelVersion] = None
    if model.active_version_id is not None:
        active_version = db.get(AdultIdentityModelVersion, model.active_version_id)
    model_artifact_uri = active_version.lora_weights_uri if active_version else None

    # ── Mark renders (stable order: region then mark id) ─────────────────────
    mark_rows = (
        db.query(AdultIdentityMarkRender)
        .filter(AdultIdentityMarkRender.identity_id == model.id)
        .order_by(AdultIdentityMarkRender.body_region, AdultIdentityMarkRender.canon_mark_id)
        .all()
    )
    marks = [_mark_dict(r) for r in mark_rows]

    missing_reference = [m["canon_mark_id"] for m in marks if not m["reference_uri"]]
    unsupported = [
        {"canon_mark_id": m["canon_mark_id"], "route": m["route"]}
        for m in marks
        if m["route"] not in EXECUTOR_SUPPORTED_ROUTES
    ]

    # ── Optional route expectations (substring of reason → expected route) ────
    expectation_failures: list[str] = []
    expectations = route_expectations or {}
    for needle, expected_route in expectations.items():
        n = needle.lower()
        matched = [m for m in marks if n in (m["reason"] or "").lower()]
        if not matched:
            expectation_failures.append(
                f"no mark matched expectation '{needle}' (expected route {expected_route})"
            )
            continue
        for m in matched:
            if m["route"] != expected_route:
                expectation_failures.append(
                    f"mark {m['canon_mark_id']} ('{needle}') route is "
                    f"'{m['route']}', expected '{expected_route}'"
                )

    # ── Checks ───────────────────────────────────────────────────────────────
    checks = {
        "identity_exists": True,
        "status_ready": model.status == REQUIRED_STATUS,
        "active_version_present": active_version is not None,
        "model_artifact_present": bool(model_artifact_uri),
        "has_mark_renders": len(marks) > 0,
        "all_references_present": len(missing_reference) == 0,
        "all_routes_supported": len(unsupported) == 0,
        "route_expectations_met": len(expectation_failures) == 0,
    }

    # ── Actionable blocking reasons (ordered) ────────────────────────────────
    blocking_reasons: list[str] = []
    if not checks["status_ready"]:
        blocking_reasons.append(
            f"identity status is '{model.status}', expected '{REQUIRED_STATUS}'"
        )
    if not checks["active_version_present"]:
        blocking_reasons.append(
            "no active version (active_version_id is unset or does not resolve)"
        )
    if not checks["model_artifact_present"]:
        blocking_reasons.append("active version has no model artifact (lora_weights_uri)")
    if not checks["has_mark_renders"]:
        blocking_reasons.append("no mark renders to enforce")
    if not checks["all_references_present"]:
        blocking_reasons.append(
            f"{len(missing_reference)} mark render(s) missing reference_uri: "
            + ", ".join(missing_reference)
        )
    if not checks["all_routes_supported"]:
        blocking_reasons.append(
            "unsupported route(s): "
            + ", ".join(f"{u['canon_mark_id']}={u['route']}" for u in unsupported)
        )
    if not checks["route_expectations_met"]:
        blocking_reasons.extend(expectation_failures)

    ready_for_executor = len(blocking_reasons) == 0

    return {
        "character_id": character_id,
        "identity_id": model.id,
        "status": model.status,
        "active_version_id": model.active_version_id,
        "model_artifact_uri": model_artifact_uri,
        "marks": marks,
        "checks": checks,
        "executor_required": True,
        "ready_for_executor": ready_for_executor,
        "blocking_reasons": blocking_reasons,
    }
