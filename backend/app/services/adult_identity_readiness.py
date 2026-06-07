"""Adult Studio identity readiness validation (Phase 2, Sprint 5).

Answers one operational question for admins: *is this character ready to train an
Adult Studio identity?* It checks the locked canon preconditions, the prepared identity
state (fingerprint + resolved mark routes), and per-mark reference availability, then
returns a single ``ready_to_train`` boolean plus actionable ``blocking_reasons``.

Strictly read-only: it reads the locked Canon Pack as source of truth and the
``adult_identity_*`` rows, and writes NOTHING. It never constructs a provider, trains,
or generates. (Reading canon is not a Canon Studio change.)

Note: ``ready_to_train`` is independent of the training feature flag — it reports whether
the identity *would* be trainable, not whether training is currently enabled.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from app.models.adult_identity import AdultIdentityMarkRender, AdultIdentityModel
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services import canon_service as cs
from app.services.adult_identity_routing import resolve_marks

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# The training state machine only creates a job from a 'prepared' identity
# (see adult_identity_training.create_training_job).
_TRAINABLE_STATUS = "prepared"


def build_readiness(character_id: int, db: "Session") -> dict[str, Any]:
    """Assemble the read-only readiness report for a character."""
    canon = (
        db.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == character_id)
        .first()
    )
    face_locked = bool(canon and canon.face_locked)
    body_locked = bool(canon and canon.body_locked)

    # Canon marks + their resolved routes/references (pure, read-only).
    marks: list = []
    if canon is not None:
        body = cs.load_body_canon(canon)
        marks = list(getattr(body, "permanent_body_marks", []) or [])
    plans = resolve_marks(marks)
    canon_mark_count = len(marks)
    unreferenced_marks = [p.canon_mark_id for p in plans if not p.reference_url]
    mark_references_exist = len(unreferenced_marks) == 0

    # Prepared identity state.
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    identity_exists = model is not None
    fingerprint_exists = bool(model and model.canon_fingerprint)
    status: Optional[str] = model.status if model else None
    stale = bool(model and model.status == "stale")

    # Routes are "resolved" when the persisted render plan covers every canon mark
    # with a concrete (non-skip) route — i.e. prepare has run against current canon.
    if model is not None:
        renders = (
            db.query(AdultIdentityMarkRender)
            .filter(AdultIdentityMarkRender.identity_id == model.id)
            .all()
        )
    else:
        renders = []
    mark_render_count = len(renders)
    routes_resolved = (
        identity_exists
        and mark_render_count == canon_mark_count
        and all(r.route and r.route != "skip" for r in renders)
    )

    checks = {
        "face_locked": face_locked,
        "body_locked": body_locked,
        "identity_exists": identity_exists,
        "fingerprint_exists": fingerprint_exists,
        "mark_references_exist": mark_references_exist,
        "routes_resolved": routes_resolved,
        "not_stale": not stale,
        "status_trainable": status == _TRAINABLE_STATUS,
    }

    # ── Actionable blocking reasons (ordered; no redundant noise) ─────────────
    blocking_reasons: list[str] = []
    if not face_locked:
        blocking_reasons.append("face canon is not locked")
    if not body_locked:
        blocking_reasons.append("body canon is not locked")
    if not mark_references_exist:
        blocking_reasons.append(
            f"{len(unreferenced_marks)} permanent mark(s) have no reference image: "
            + ", ".join(unreferenced_marks)
        )
    if not identity_exists:
        blocking_reasons.append("no Adult Studio identity has been prepared")
    else:
        if not fingerprint_exists:
            blocking_reasons.append("identity has no canon fingerprint (run prepare)")
        if not routes_resolved:
            blocking_reasons.append(
                "mark render routes are not fully resolved for current canon (run prepare)"
            )
        if stale:
            blocking_reasons.append(
                "identity is stale — canon changed since last prepare; re-prepare"
            )
        elif status != _TRAINABLE_STATUS:
            blocking_reasons.append(
                f"identity status is '{status}', expected '{_TRAINABLE_STATUS}'"
            )

    ready_to_train = len(blocking_reasons) == 0

    return {
        "character_id": character_id,
        "ready_to_train": ready_to_train,
        "status": status,
        "stale": stale,
        "blocking_reasons": blocking_reasons,
        "checks": checks,
        "canon_mark_count": canon_mark_count,
        "mark_render_count": mark_render_count,
        "unreferenced_marks": unreferenced_marks,
    }
