"""b33.8: add cover_position_y to characters

Revision ID: b33_8_cover_position_y
Revises: b33_add_cover_kind
Create Date: 2026-03-24

Adds a nullable Float column cover_position_y to the characters table.
Values: 0.0 = top, 0.5 = center (default), 1.0 = bottom.
Existing rows default to 0.5 (center) via server_default.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b33_8_cover_position_y'
down_revision: Union[str, None] = 'b33_add_cover_kind'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'characters',
        sa.Column('cover_position_y', sa.Float(), nullable=True, server_default='0.5'),
    )


def downgrade() -> None:
    op.drop_column('characters', 'cover_position_y')
