"""bc01: add body identity image kind values to imagekindenum

Revision ID: bc01_body_identity_kinds
Revises: ss03_body_canon
Create Date: 2026-05-22

Extends imagekindenum with:
  identity_body_front, identity_body_three_quarter,
  identity_body_back, identity_tattoo_layout

On SQLite (tests) the column is plain TEXT — no DDL required.
On PostgreSQL, ALTER TYPE … ADD VALUE IF NOT EXISTS is used.
Downgrade is a no-op: PostgreSQL cannot remove enum values.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "bc01_body_identity_kinds"
down_revision: Union[str, None] = "ss03_body_canon"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "identity_body_front",
    "identity_body_three_quarter",
    "identity_body_back",
    "identity_tattoo_layout",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
