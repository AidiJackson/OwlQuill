"""Add scenes table and post scene_id

Revision ID: 990c9a56fae1
Revises: 8b18cfce864f
Create Date: 2025-11-17 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '990c9a56fae1'
down_revision: Union[str, None] = '8b18cfce864f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add scenes table and restructure posts to belong to scenes.

    WARNING: This is a BREAKING migration that will delete all existing posts!
    Posts now belong to Scenes, which belong to Realms.
    """
    # Create scenes table
    op.create_table(
        'scenes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('realm_id', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['realm_id'], ['realms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scenes_id'), 'scenes', ['id'], unique=False)

    # Drop existing posts table and recreate with scene_id
    # This is necessary because posts now require a scene_id
    op.drop_table('posts')

    # Recreate posts table with scene_id
    op.create_table(
        'posts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scene_id', sa.Integer(), nullable=False),
        sa.Column('realm_id', sa.Integer(), nullable=False),
        sa.Column('author_user_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_type', sa.Enum('IC', 'OOC', 'NARRATION', name='contenttypeenum'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['realm_id'], ['realms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_posts_id'), 'posts', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade is not supported for this migration as it involves data loss."""
    # Drop new posts table
    op.drop_table('posts')

    # Drop scenes table
    op.drop_index(op.f('ix_scenes_id'), table_name='scenes')
    op.drop_table('scenes')

    # Recreate old posts table without scene_id
    op.create_table(
        'posts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('realm_id', sa.Integer(), nullable=True),
        sa.Column('author_user_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_type', sa.Enum('IC', 'OOC', 'NARRATION', name='contenttypeenum'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['realm_id'], ['realms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_posts_id'), 'posts', ['id'], unique=False)
