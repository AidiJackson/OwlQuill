"""add next_character_allowed_at to users

Revision ID: e5a9b3c82d14
Revises: d4f8a2b71e93
Create Date: 2026-02-08 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5a9b3c82d14'
down_revision: Union[str, None] = 'd4f8a2b71e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('next_character_allowed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'next_character_allowed_at')
