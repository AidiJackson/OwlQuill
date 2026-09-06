"""p4d3_01: add the canon-cluster image kinds to imagekindenum

Revision ID: p4d3_01_canon_image_kinds
Revises: p4c01_character_id_optional
Create Date: 2026-09-06

Phase 4D3 gives the identity-canon writers owned ``CharacterImage`` rows. Until
now those images were written by ``storage.save_image()`` — bytes with no row —
so nothing ever had to say what they WERE. A row has to, and six of the thirteen
v2 canon card slots plus the permanent-mark references had no honest label:

    identity_face_profile        identity_torso_front     identity_mark_reference
    identity_face_expression     identity_torso_side      identity_mark_detail
    identity_body_left           identity_pose_standing
    identity_body_right          identity_pose_seated

WHY NEW VALUES RATHER THAN REUSE. ``kind`` is the column PUBLIC_GALLERY_KINDS,
POST_ATTACHABLE_IMAGE_KINDS and (from 4D3-2) AVATAR_ELIGIBLE_KINDS all read, so
an approximate label is not a naming inconvenience — it is a policy statement
about bytes it does not describe. Two reuses were specifically considered and
rejected:

* ``generated`` for the unlabelled slots. It is IN ``PUBLIC_GALLERY_KINDS``, so
  canon working references would enter the public gallery. That is not
  hypothetical: nine canon URLs on DEV already carry ``kind=generated`` and are
  gallery-eligible today, from writers that took exactly this shortcut.
* ``identity_body_left_detail`` / ``_right_detail`` for the full-body side
  VIEWS. Those labels mean a tight, high-fidelity crop of a marking and are in
  use for that; overloading them would make "detail crop" unqueryable.

Generated marking anchors and uploaded mark reference photos deliberately SHARE
``identity_mark_reference``: they are one semantic object at one fidelity, and
``provider`` already records which is which (``None`` for founder bytes).

This migration adds enum values and nothing else. No column, no constraint, no
row, no backfill, and no writer produces any of these kinds yet — 4D3-3 does
that, after the avatar policy in 4D3-2 is in place. An enum value nobody writes
and no allowlist admits changes no behaviour, which is what makes it safe to
land on its own.

On SQLite (tests) the column is plain TEXT — no DDL required.
On PostgreSQL, ALTER TYPE … ADD VALUE IF NOT EXISTS is used; it is idempotent,
so re-running against a partially-upgraded database is safe.
Downgrade is a no-op: PostgreSQL cannot remove enum values.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p4d3_01_canon_image_kinds"
down_revision: Union[str, tuple] = "p4c01_character_id_optional"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The ten values, in the order they are declared on ``ImageKindEnum``.
#: ``tests/test_phase4d3_canon_image_kinds.py`` pins this tuple against the model
#: so a member added in one place and forgotten in the other fails a test rather
#: than a production INSERT.
_NEW_VALUES = (
    "identity_face_profile",
    "identity_face_expression",
    "identity_body_left",
    "identity_body_right",
    "identity_torso_front",
    "identity_torso_side",
    "identity_pose_standing",
    "identity_pose_seated",
    "identity_mark_reference",
    "identity_mark_detail",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
