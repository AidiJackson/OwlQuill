"""p4d3_02: add the v2 face-card image kinds to imagekindenum

Revision ID: p4d3_02_v2_face_card_kinds
Revises: p4d3_01_canon_image_kinds
Create Date: 2026-09-06

Adds ``identity_face_front``, ``identity_face_left_3q`` and
``identity_face_right_3q``.

WHY THESE EXIST SEPARATELY FROM THE ANCHOR_* KINDS. Phase 4D3-3 first mapped the
v2 pack's three face slots onto ``anchor_front`` and ``anchor_three_quarter``,
which look like the same thing and are not. The ANCHOR_* kinds are legacy
identity-pack infrastructure with live operational meaning:

  * they are the whole of ``PROTECTED_IMAGE_KINDS``, so rows carrying them
    cannot be archived by their owner;
  * the identity lock requires four ACTIVE anchor rows before a character can
    be locked;
  * ``canon_bridge`` resolves an anchor by kind + status.

A v2 pack writing those kinds therefore injected rows into three mechanisms it
has nothing to do with — inflating anchor counts and making ordinary pack output
permanently undeletable. ``test_generate_v2_pack_creates_no_legacy_anchors``
caught it: it asserts zero legacy anchors after a pack and found three.

Left and right are separate values rather than one shared three-quarter kind,
because the canon slots are distinct, the scene router grounds on them
independently, and one label would make the side unrecoverable from the column.

The legacy ANCHOR_* kinds are untouched and keep every one of their existing
semantics. No historical row is migrated or backfilled: rows written before this
change keep the kind they were written with, and nothing reinterprets them.

On SQLite (tests) the column is plain TEXT — no DDL required.
On PostgreSQL, ALTER TYPE … ADD VALUE IF NOT EXISTS; idempotent, so re-running
against a partially-upgraded database is safe.
Downgrade is a no-op: PostgreSQL cannot remove enum values.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p4d3_02_v2_face_card_kinds"
down_revision: Union[str, tuple] = "p4d3_01_canon_image_kinds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: In declaration order on ``ImageKindEnum``; pinned against the model by
#: ``tests/test_phase4d3_canon_image_kinds.py``.
_NEW_VALUES = (
    "identity_face_front",
    "identity_face_left_3q",
    "identity_face_right_3q",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
