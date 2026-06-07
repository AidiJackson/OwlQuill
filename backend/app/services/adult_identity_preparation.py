"""Adult Studio identity preparation (Phase 1, Sprint 3).

Ties together Sprint 1 persistence + Sprint 2 fingerprint/routing into a single,
idempotent prepare operation that records Adult Studio's preparation state:

  - load LOCKED canon (read-only),
  - compute the canon fingerprint,
  - resolve every permanent mark to a render route,
  - upsert the AdultIdentityModel (create as 'prepared'; flag 'stale' when canon moved),
  - upsert the per-mark render plan into adult_identity_mark_renders.

No image generation, no training, no providers, no RunPod, no canon writes. Canon is
read via canon_service only.

Note: the mark-render `reason` is stored inside `params_json` (no `reason` column in the
Sprint 1 schema) to avoid an unnecessary migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from app.models.adult_identity import AdultIdentityMarkRender, AdultIdentityModel
from app.models.character import Character
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services import canon_service as cs
from app.services.adult_identity_fingerprint import canon_fingerprint
from app.services.adult_identity_routing import resolve_marks
from app.services.adult_studio import trigger_token

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class CanonNotReadyError(Exception):
    """Raised when a character's canon is missing or not fully locked."""


@dataclass
class PreparationResult:
    character_id: int
    fingerprint: str
    model_status: str
    mark_count: int
    routes: list[dict]


def _load_locked_canon(character_id: int, db: "Session") -> CharacterIdentityCanon:
    canon = (
        db.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == character_id)
        .first()
    )
    if not canon or not (canon.face_locked and canon.body_locked):
        raise CanonNotReadyError(
            f"character {character_id} canon must be locked (face and body) before preparing"
        )
    return canon


def prepare_adult_identity(character_id: int, db: "Session") -> PreparationResult:
    """Idempotently record Adult Studio preparation state for a character.

    Reruns with unchanged canon produce no new rows and no status change. A canon
    change since the last prepare flips the model to 'stale'.
    """
    canon = _load_locked_canon(character_id, db)
    face = cs.load_face_canon(canon)
    body = cs.load_body_canon(canon)
    marks = list(getattr(body, "permanent_body_marks", []) or [])

    fingerprint = canon_fingerprint(face, body)
    plans = resolve_marks(marks)

    # ── Upsert the identity model + staleness ────────────────────────────
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if model is None:
        character = db.get(Character, character_id)
        model = AdultIdentityModel(
            character_id=character_id,
            status="prepared",
            trigger_token=trigger_token(character.name) if character else None,
            canon_fingerprint=fingerprint,
        )
        db.add(model)
        db.flush()  # assign model.id for mark_render FKs
    else:
        if model.canon_fingerprint is None:
            # First prepare of a backfilled/never-fingerprinted model: this run
            # establishes the baseline, it is NOT 'stale' (stale means canon moved
            # since a PRIOR prepare/train). A backfilled row sits at 'prepared' or
            # 'not_trained' — promote the latter now that it has a fingerprint+routes.
            if model.status == "not_trained":
                model.status = "prepared"
        elif model.canon_fingerprint != fingerprint:
            # Canon moved since this model was last prepared/trained → stale.
            model.status = "stale"
        model.canon_fingerprint = fingerprint

    # ── Upsert per-mark render plans (idempotent) ────────────────────────
    existing = {
        r.canon_mark_id: r
        for r in db.query(AdultIdentityMarkRender)
        .filter(AdultIdentityMarkRender.identity_id == model.id)
        .all()
    }
    current_ids: set[str] = set()
    for mark, plan in zip(marks, plans):
        current_ids.add(plan.canon_mark_id)
        row = existing.get(plan.canon_mark_id)
        if row is None:
            row = AdultIdentityMarkRender(
                identity_id=model.id, canon_mark_id=plan.canon_mark_id
            )
            db.add(row)
        row.mark_fingerprint = plan.mark_fingerprint
        row.mark_type = getattr(mark, "type", None)
        row.body_region = plan.region
        row.side = plan.side
        row.route = plan.route
        row.reference_uri = plan.reference_url
        # `reason` has no dedicated column; persist it in params_json (no migration).
        row.params_json = {"reason": plan.reason}

    # Prune renders for marks no longer present in canon (keeps reruns in sync).
    for mark_id, row in existing.items():
        if mark_id not in current_ids:
            db.delete(row)

    db.commit()
    db.refresh(model)

    routes = [
        {
            "canon_mark_id": p.canon_mark_id,
            "route": p.route,
            "region": p.region,
            "side": p.side,
            "reason": p.reason,
            "reference_url": p.reference_url,
        }
        for p in plans
    ]
    return PreparationResult(
        character_id=character_id,
        fingerprint=fingerprint,
        model_status=model.status,
        mark_count=len(marks),
        routes=routes,
    )
