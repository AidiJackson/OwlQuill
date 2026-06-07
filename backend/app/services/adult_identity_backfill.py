"""Adult Studio Phase 2 — legacy → new identity backfill (cutover bridge).

One-time, idempotent mapping of legacy ``adult_studio_identities`` rows onto the
Phase 1 ``AdultIdentityModel`` system (docs/ADULT_STUDIO_PHASE2_DESIGN.md §3, §4.4).

Status reconciliation (the load-bearing part): legacy ``ready`` meant only "a
manifest exists" — it was NEVER trained — so it maps to the new ``prepared``, not
``ready`` (which now means "an active trained version exists").

    legacy not_trained → not_trained
    legacy preparing   → not_trained   (re-prepare to reach prepared)
    legacy ready       → prepared      (manifest existed, never trained)
    legacy failed      → failed

This READS the legacy table and WRITES only ``adult_identity_models`` — the legacy
table is left UNTOUCHED (no writes, no schema change). Idempotent: a character that
already has an ``AdultIdentityModel`` is skipped, so re-running is a no-op. No canon
writes, no provider, no training, no generation, no external calls.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.adult_identity import AdultIdentityModel
from app.models.adult_studio import AdultStudioIdentity
from app.services.adult_studio import trigger_token

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Legacy 4-value vocabulary → new 6-value vocabulary (docs §3).
LEGACY_TO_NEW_STATUS: dict[str, str] = {
    "not_trained": "not_trained",
    "preparing": "not_trained",
    "ready": "prepared",
    "failed": "failed",
}


def map_legacy_status(legacy_status: str | None) -> str:
    """Map a legacy status to its new-vocabulary equivalent (default not_trained)."""
    return LEGACY_TO_NEW_STATUS.get((legacy_status or "").strip(), "not_trained")


def backfill_legacy_identity(
    legacy: AdultStudioIdentity, db: "Session"
) -> AdultIdentityModel | None:
    """Create an AdultIdentityModel from one legacy row, if none exists yet.

    Returns the new (or pre-existing) model, or None when there is nothing to do.
    Idempotent: never overwrites an existing model and never mutates ``legacy``.
    """
    existing = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == legacy.character_id)
        .first()
    )
    if existing is not None:
        return existing  # already cut over — leave it alone

    char_name = getattr(getattr(legacy, "character", None), "name", None)
    model = AdultIdentityModel(
        character_id=legacy.character_id,
        status=map_legacy_status(legacy.status),
        trigger_token=trigger_token(char_name) if char_name else None,
        # Preserve the legacy manifest so training-pack/ref-counts keep working
        # until a subsequent prepare refreshes fingerprint + mark routes.
        prepared_manifest_json=legacy.training_notes_json or None,
    )
    db.add(model)
    return model


def backfill_all(db: "Session") -> int:
    """Backfill every legacy row that has no new model yet. Returns rows created.

    Commits once at the end. Safe to run repeatedly (idempotent).
    """
    created = 0
    for legacy in db.query(AdultStudioIdentity).all():
        existing = (
            db.query(AdultIdentityModel)
            .filter(AdultIdentityModel.character_id == legacy.character_id)
            .first()
        )
        if existing is not None:
            continue
        backfill_legacy_identity(legacy, db)
        created += 1
    if created:
        db.commit()
    return created
