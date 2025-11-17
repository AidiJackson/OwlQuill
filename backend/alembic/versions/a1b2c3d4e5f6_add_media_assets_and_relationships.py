"""Add media assets and relationships

Revision ID: a1b2c3d4e5f6
Revises: 8b18cfce864f
Create Date: 2025-11-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '8b18cfce864f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create media_assets table
    op.create_table(
        'media_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.Enum('USER_AVATAR', 'CHARACTER_AVATAR', 'POST_IMAGE', name='mediakind'), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('path')
    )
    op.create_index(op.f('ix_media_assets_id'), 'media_assets', ['id'], unique=False)

    # Add media relationships to existing tables
    op.add_column('users', sa.Column('avatar_media_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_users_avatar_media', 'users', 'media_assets', ['avatar_media_id'], ['id'], ondelete='SET NULL')

    op.add_column('characters', sa.Column('avatar_media_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_characters_avatar_media', 'characters', 'media_assets', ['avatar_media_id'], ['id'], ondelete='SET NULL')

    op.add_column('posts', sa.Column('image_media_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_posts_image_media', 'posts', 'media_assets', ['image_media_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    # Remove media relationships from existing tables
    op.drop_constraint('fk_posts_image_media', 'posts', type_='foreignkey')
    op.drop_column('posts', 'image_media_id')

    op.drop_constraint('fk_characters_avatar_media', 'characters', type_='foreignkey')
    op.drop_column('characters', 'avatar_media_id')

    op.drop_constraint('fk_users_avatar_media', 'users', type_='foreignkey')
    op.drop_column('users', 'avatar_media_id')

    # Drop media_assets table
    op.drop_index(op.f('ix_media_assets_id'), table_name='media_assets')
    op.drop_table('media_assets')
