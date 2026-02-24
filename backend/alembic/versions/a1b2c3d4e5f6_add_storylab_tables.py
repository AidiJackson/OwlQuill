"""add storylab tables (story_state + generation_log)

Revision ID: a1b2c3d4e5f6
Revises: c8f5a1d26e93
Create Date: 2026-02-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c8f5a1d26e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'story_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('story_id', sa.String(), nullable=False),
        sa.Column('story_summary', sa.Text(), nullable=True),
        sa.Column('state_json', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_story_state_id'), 'story_state', ['id'], unique=False)
    op.create_index(op.f('ix_story_state_story_id'), 'story_state', ['story_id'], unique=True)

    op.create_table(
        'generation_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('story_id', sa.String(), nullable=False),
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('controls_json', sa.JSON(), nullable=False),
        sa.Column('prompt_snapshot', sa.Text(), nullable=True),
        sa.Column('response_text', sa.Text(), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_generation_log_id'), 'generation_log', ['id'], unique=False)
    op.create_index(op.f('ix_generation_log_story_id'), 'generation_log', ['story_id'], unique=False)
    op.create_index(op.f('ix_generation_log_request_id'), 'generation_log', ['request_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_generation_log_request_id'), table_name='generation_log')
    op.drop_index(op.f('ix_generation_log_story_id'), table_name='generation_log')
    op.drop_index(op.f('ix_generation_log_id'), table_name='generation_log')
    op.drop_table('generation_log')
    op.drop_index(op.f('ix_story_state_story_id'), table_name='story_state')
    op.drop_index(op.f('ix_story_state_id'), table_name='story_state')
    op.drop_table('story_state')
