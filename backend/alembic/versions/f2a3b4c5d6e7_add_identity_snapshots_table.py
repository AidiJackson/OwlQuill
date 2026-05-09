"""add identity_snapshots table for rollback support

Revision ID: f2a3b4c5d6e7
Revises: 4643bfb95d96
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = '4643bfb95d96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'identity_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_version', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('anchor_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('identity_anchor_json', sa.Text(), nullable=True),
        sa.Column('identity_spec_json', sa.Text(), nullable=True),
        sa.Column('reason', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_identity_snapshots_id', 'identity_snapshots', ['id'])
    op.create_index('ix_identity_snapshots_character_id', 'identity_snapshots', ['character_id'])


def downgrade() -> None:
    op.drop_index('ix_identity_snapshots_character_id', table_name='identity_snapshots')
    op.drop_index('ix_identity_snapshots_id', table_name='identity_snapshots')
    op.drop_table('identity_snapshots')
