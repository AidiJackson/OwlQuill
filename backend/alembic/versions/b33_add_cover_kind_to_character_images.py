"""b33: add 'cover' value to imagekindenum

Revision ID: b33_add_cover_kind
Revises: b32b_add_cover_url_to_characters
Create Date: 2026-03-22

Extends the imagekindenum PostgreSQL type with the 'cover' value so that
cover/banner images can be stored in character_images alongside the existing
generated/anchor/identity kinds.

On SQLite (tests) the column is plain TEXT so no DDL is needed.
Downgrade is intentionally a no-op: PostgreSQL cannot remove enum values.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b33_add_cover_kind'
down_revision: Union[str, None] = 'b32b_add_cover_url_to_characters'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute("ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS 'cover'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    pass
