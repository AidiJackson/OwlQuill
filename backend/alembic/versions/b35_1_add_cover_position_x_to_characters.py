"""b35.1: add cover_position_x to characters

Revision ID: b35_1_cover_position_x
Revises: b33_8_cover_position_y
Create Date: 2026-03-26

Adds a nullable Float column cover_position_x to the characters table.
Values: 0.0 = left, 0.5 = center (default), 1.0 = right.
Existing rows default to 0.5 (center) via server_default.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b35_1_cover_position_x'
down_revision: Union[str, None] = 'b33_8_cover_position_y'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'characters',
        sa.Column('cover_position_x', sa.Float(), nullable=True, server_default='0.5'),
    )


def downgrade() -> None:
    op.drop_column('characters', 'cover_position_x')
