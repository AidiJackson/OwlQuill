"""add story_chapter table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'story_chapter',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('story_id', sa.String(), nullable=False),
        sa.Column('chapter_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('prompt_text', sa.Text(), nullable=True),
        sa.Column('mode', sa.String(), nullable=False, server_default='roleplay'),
        sa.Column('controls_json', sa.JSON(), nullable=False),
        sa.Column('generated_text', sa.Text(), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('story_id', 'chapter_number', name='uq_story_chapter'),
    )
    op.create_index(op.f('ix_story_chapter_id'), 'story_chapter', ['id'], unique=False)
    op.create_index(op.f('ix_story_chapter_story_id'), 'story_chapter', ['story_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_story_chapter_story_id'), table_name='story_chapter')
    op.drop_index(op.f('ix_story_chapter_id'), table_name='story_chapter')
    op.drop_table('story_chapter')
