"""add cover_scale and avatar crop fields to characters

Revision ID: b41_add_cover_scale_avatar_crop
Revises: b35_1_cover_position_x
Create Date: 2026-03-28

"""
from alembic import op
import sqlalchemy as sa

revision = 'b41_add_cover_scale_avatar_crop'
down_revision = 'b35_1_cover_position_x'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('cover_scale', sa.Float(), nullable=True, server_default='1.0'))
    op.add_column('characters', sa.Column('avatar_position_x', sa.Float(), nullable=True, server_default='0.5'))
    op.add_column('characters', sa.Column('avatar_position_y', sa.Float(), nullable=True, server_default='0.5'))
    op.add_column('characters', sa.Column('avatar_scale', sa.Float(), nullable=True, server_default='1.0'))


def downgrade() -> None:
    op.drop_column('characters', 'cover_scale')
    op.drop_column('characters', 'avatar_position_x')
    op.drop_column('characters', 'avatar_position_y')
    op.drop_column('characters', 'avatar_scale')
