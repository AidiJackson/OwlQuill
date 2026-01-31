"""Add realm_id to scenes

Revision ID: c7d4e8f21a3b
Revises: b5e8d2f41c7a
Create Date: 2026-01-31 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d4e8f21a3b'
down_revision: Union[str, None] = 'b5e8d2f41c7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scenes', sa.Column('realm_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_scenes_realm_id_realms',
        'scenes', 'realms',
        ['realm_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('fk_scenes_realm_id_realms', 'scenes', type_='foreignkey')
    op.drop_column('scenes', 'realm_id')
