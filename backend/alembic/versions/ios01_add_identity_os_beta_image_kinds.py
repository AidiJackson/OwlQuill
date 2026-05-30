"""ios01: add Identity OS Beta image kind values to imagekindenum

Revision ID: ios01_identity_os_beta
Revises: ss03_body_canon
Create Date: 2026-05-30

Extends imagekindenum with:
  scene_only        — generated scene image, not canon
  accessory_design  — isolated accessory design sheet
  accessory_fit     — accessory on character (fit reference)

On SQLite (tests) the column is plain TEXT — no DDL required.
On PostgreSQL, ALTER TYPE ... ADD VALUE IF NOT EXISTS is used.
Downgrade is a no-op: PostgreSQL cannot remove enum values.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ios01_identity_os_beta"
down_revision: Union[str, tuple] = "bc03_body_identity_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "scene_only",
    "accessory_design",
    "accessory_fit",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
