"""as03: backfill legacy adult_studio_identities → adult_identity_models

Revision ID: as03_backfill_adult_identity
Revises: as02_adult_identity_models
Create Date: 2026-06-07

Phase 2, Sprint 1 cutover (docs/ADULT_STUDIO_PHASE2_DESIGN.md §3, §4.4). Copies each
legacy adult_studio_identities row into the new adult_identity_models table using the
status reconciliation map (legacy ``ready`` → new ``prepared`` — it was never trained).

ADDITIVE and idempotent. The legacy table is left UNTOUCHED (read-only here — no writes,
no schema change, not dropped). Only adult_identity_models rows are inserted, and only
for characters that do not already have one. No canon table is modified. No provider,
training, generation, or external call occurs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "as03_backfill_adult_identity"
down_revision: Union[str, tuple] = "as02_adult_identity_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Legacy 4-value vocabulary → new 6-value vocabulary (docs §3). Kept inline so the
# migration is self-contained and does not depend on app code at upgrade time.
_LEGACY_TO_NEW_STATUS = {
    "not_trained": "not_trained",
    "preparing": "not_trained",
    "ready": "prepared",
    "failed": "failed",
}


def upgrade() -> None:
    bind = op.get_bind()
    legacy = sa.table(
        "adult_studio_identities",
        sa.column("character_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("training_notes_json", sa.JSON),
    )
    new = sa.table(
        "adult_identity_models",
        sa.column("character_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("prepared_manifest_json", sa.JSON),
    )

    # Characters that already have a new model — skip them (idempotent).
    existing_ids = {
        row[0] for row in bind.execute(sa.select(new.c.character_id)).fetchall()
    }

    rows = bind.execute(
        sa.select(legacy.c.character_id, legacy.c.status, legacy.c.training_notes_json)
    ).fetchall()

    to_insert = [
        {
            "character_id": cid,
            "status": _LEGACY_TO_NEW_STATUS.get((status or "").strip(), "not_trained"),
            "prepared_manifest_json": manifest or None,
        }
        for (cid, status, manifest) in rows
        if cid not in existing_ids
    ]
    if to_insert:
        op.bulk_insert(new, to_insert)


def downgrade() -> None:
    # No-op: the backfill only adds rows that mirror the still-present legacy table.
    # Dropping them would be indistinguishable from rows created by normal use, so the
    # safe reversal is to leave adult_identity_models untouched.
    pass
