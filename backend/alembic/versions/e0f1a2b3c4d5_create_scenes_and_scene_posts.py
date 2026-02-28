"""Create scenes and scene_posts tables

Revision ID: e0f1a2b3c4d5
Revises: b5e8d2f41c7a
Create Date: 2026-01-30 00:00:02.000000

NOTE: This migration was added retroactively to fix a gap in the migration
chain — the scenes table was never created, causing c7d4e8f21a3b
(add_realm_id_to_scenes) to fail on a fresh database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, None] = 'b5e8d2f41c7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scenes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'visibility',
            sa.Enum('PUBLIC', 'UNLISTED', 'PRIVATE', name='scenevisibilityenum'),
            nullable=False,
        ),
        sa.Column('created_by_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scenes_id'), 'scenes', ['id'], unique=False)

    op.create_table(
        'scene_posts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scene_id', sa.Integer(), nullable=False),
        sa.Column('author_user_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('reply_to_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['character_id'], ['characters.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reply_to_id'], ['scene_posts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scene_posts_id'), 'scene_posts', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_scene_posts_id'), table_name='scene_posts')
    op.drop_table('scene_posts')
    op.drop_index(op.f('ix_scenes_id'), table_name='scenes')
    op.drop_table('scenes')
    sa.Enum(name='scenevisibilityenum').drop(op.get_bind(), checkfirst=True)
