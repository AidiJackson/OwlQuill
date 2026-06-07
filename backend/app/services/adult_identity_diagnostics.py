"""Adult Studio identity diagnostics (Phase 2, Sprint 4).

Read-only operational visibility into WHY a character's Adult Studio identity sits in
its current lifecycle state (prepared / stale / training / ready / failed). It joins the
model + versions + training jobs + mark-render plan into one inspectable payload and, for
stale models, surfaces the current-vs-trained canon fingerprint comparison.

Strictly read-only: it never writes any table, never constructs a provider, never trains,
and never generates. Canon is not touched at all (it reads only adult_identity_* rows).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
    AdultIdentityTrainingJob,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _mark_route(r: AdultIdentityMarkRender) -> dict[str, Any]:
    return {
        "canon_mark_id": r.canon_mark_id,
        "mark_type": r.mark_type,
        "body_region": r.body_region,
        "side": r.side,
        "route": r.route,
        "reason": (r.params_json or {}).get("reason"),
        "mark_fingerprint": r.mark_fingerprint,
    }


def _version(v: AdultIdentityModelVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "version_index": v.version_index,
        "state": v.state,
        "canon_fingerprint": v.canon_fingerprint,
        "lora_weights_uri": v.lora_weights_uri,
        "created_at": _iso(v.created_at),
    }


def build_diagnostics(character_id: int, db: "Session") -> dict[str, Any]:
    """Assemble the read-only diagnostics payload for a character.

    Returns ``exists=False`` (with zeroed counts) when the character has no
    AdultIdentityModel yet — a valid diagnostic answer, not an error.
    """
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )

    if model is None:
        return {
            "character_id": character_id,
            "exists": False,
            "status": None,
            "model_status": None,
            "stale": False,
            "canon_fingerprint": None,
            "active_version_id": None,
            "version_count": 0,
            "training_job_count": 0,
            "mark_render_count": 0,
            "last_error": None,
            "mark_routes": [],
            "versions": [],
            "fingerprint_comparison": {
                "current_fingerprint": None,
                "trained_fingerprint": None,
                "mismatch": False,
            },
        }

    versions = (
        db.query(AdultIdentityModelVersion)
        .filter(AdultIdentityModelVersion.identity_id == model.id)
        .order_by(AdultIdentityModelVersion.version_index)
        .all()
    )
    training_job_count = (
        db.query(AdultIdentityTrainingJob)
        .filter(AdultIdentityTrainingJob.identity_id == model.id)
        .count()
    )
    mark_rows = (
        db.query(AdultIdentityMarkRender)
        .filter(AdultIdentityMarkRender.identity_id == model.id)
        .order_by(AdultIdentityMarkRender.body_region)
        .all()
    )

    # ── Current-vs-trained fingerprint comparison ────────────────────────────
    # The trained fingerprint is the canon the ACTIVE version was trained against
    # (None until a model is actually trained — Phase 2 never trains, so None).
    current_fp = model.canon_fingerprint
    trained_fp: Optional[str] = None
    if model.active_version_id is not None:
        active = next((v for v in versions if v.id == model.active_version_id), None)
        if active is None:
            active = db.get(AdultIdentityModelVersion, model.active_version_id)
        trained_fp = active.canon_fingerprint if active is not None else None
    mismatch = trained_fp is not None and current_fp != trained_fp

    return {
        "character_id": character_id,
        "exists": True,
        "status": model.status,
        "model_status": model.status,
        "stale": model.status == "stale",
        "canon_fingerprint": current_fp,
        "active_version_id": model.active_version_id,
        "version_count": len(versions),
        "training_job_count": training_job_count,
        "mark_render_count": len(mark_rows),
        "last_error": model.last_error,
        "trigger_token": model.trigger_token,
        "provider": model.provider,
        "base_model": model.base_model,
        "created_at": _iso(model.created_at),
        "updated_at": _iso(model.updated_at),
        "mark_routes": [_mark_route(r) for r in mark_rows],
        "versions": [_version(v) for v in versions],
        "fingerprint_comparison": {
            "current_fingerprint": current_fp,
            "trained_fingerprint": trained_fp,
            "mismatch": mismatch,
        },
    }
