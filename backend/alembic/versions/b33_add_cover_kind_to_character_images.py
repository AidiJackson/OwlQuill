"""b33: add 'cover' value to imagekindenum

Revision ID: b33_add_cover_kind
Revises: b32b_add_cover_url_to_characters
Create Date: 2026-03-22 00:00:00.000000

Adds the 'cover' kind to the ImageKindEnum PostgreSQL enum type so that
wide banner cover images generated via the image generator are stored
distinctly from regular 'generated' character images.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b33_add_cover_kind'
down_revision: Union[str, None] = 'b32b_add_cover_url_to_characters'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        conn.execute(sa.text("ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS 'cover'"))


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
