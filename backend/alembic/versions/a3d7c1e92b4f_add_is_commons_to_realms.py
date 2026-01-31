"""Add is_commons to realms

Revision ID: a3d7c1e92b4f
Revises: 8b18cfce864f
Create Date: 2026-01-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3d7c1e92b4f'
down_revision: Union[str, None] = '8b18cfce864f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('realms', sa.Column('is_commons', sa.Boolean(), nullable=True, server_default=sa.text('false')))
    op.execute("UPDATE realms SET is_commons = false WHERE is_commons IS NULL")
    with op.batch_alter_table('realms') as batch_op:
        batch_op.alter_column('is_commons', nullable=False, server_default=None)


def downgrade() -> None:
    op.drop_column('realms', 'is_commons')
