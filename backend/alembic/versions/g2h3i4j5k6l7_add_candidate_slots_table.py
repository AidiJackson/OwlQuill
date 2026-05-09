"""add candidate_slots table for slot replacement workflow

Revision ID: g2h3i4j5k6l7
Revises: f2a3b4c5d6e7
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'g2h3i4j5k6l7'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'candidate_slots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('slot', sa.String(20), nullable=False),
        sa.Column('image_url', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='candidate'),
        sa.Column('validation_status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('validation_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_candidate_slots_id', 'candidate_slots', ['id'])
    op.create_index('ix_candidate_slots_character_id', 'candidate_slots', ['character_id'])


def downgrade() -> None:
    op.drop_index('ix_candidate_slots_character_id', table_name='candidate_slots')
    op.drop_index('ix_candidate_slots_id', table_name='candidate_slots')
    op.drop_table('candidate_slots')
