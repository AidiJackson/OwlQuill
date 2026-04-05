"""Add stories table for StoryLab story objects

Revision ID: b63_add_stories_table
Revises: 08567e37d16e
Create Date: 2026-04-02

Adds the top-level `stories` table that gives each StoryLab workspace a real
identity: title, genre, premise, optional realm, optional cast.
Existing story_state / story_chapter rows keyed by localStorage IDs are
unaffected — they continue to work by story_id string as before.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b63_add_stories_table'
down_revision: Union[str, None] = 'b46_add_invite_codes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('genre', sa.String(50), nullable=True),
        sa.Column('premise', sa.Text(), nullable=True),
        sa.Column('realm_id', sa.Integer(), nullable=True),
        sa.Column('character_ids', sa.JSON(), nullable=False),
        sa.Column('cover_color', sa.String(20), nullable=False, server_default='#1a1a2e'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_stories_id', 'stories', ['id'], unique=False)
    op.create_index('ix_stories_user_id', 'stories', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_stories_user_id', table_name='stories')
    op.drop_index('ix_stories_id', table_name='stories')
    op.drop_table('stories')
