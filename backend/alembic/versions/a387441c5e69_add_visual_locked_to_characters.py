"""add_visual_locked_to_characters

Revision ID: a387441c5e69
Revises: 72e94203f23d
Create Date: 2026-02-01 19:18:28.138204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a387441c5e69'
down_revision: Union[str, None] = '72e94203f23d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('visual_locked', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('characters', 'visual_locked')
