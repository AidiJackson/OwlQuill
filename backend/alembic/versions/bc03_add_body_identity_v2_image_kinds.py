"""bc03: add body identity pack v2 image kind values to imagekindenum

Revision ID: bc03_body_identity_v2
Revises: bc02_body_canon_snapshot, rp01_rp_story_threads
Create Date: 2026-05-25

Extends imagekindenum with:
  identity_body_left_detail, identity_body_right_detail,
  identity_body_map, identity_final_character_card

On SQLite (tests) the column is plain TEXT — no DDL required.
On PostgreSQL, ALTER TYPE … ADD VALUE IF NOT EXISTS is used.
Downgrade is a no-op: PostgreSQL cannot remove enum values.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "bc03_body_identity_v2"
down_revision: Union[str, tuple] = ("bc02_body_canon_snapshot", "rp01_rp_story_threads")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "identity_body_left_detail",
    "identity_body_right_detail",
    "identity_body_map",
    "identity_final_character_card",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
