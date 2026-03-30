"""add invite_codes table for closed-beta registration gate

Revision ID: b46_add_invite_codes
Revises: b41_add_cover_scale_avatar_crop
Create Date: 2026-03-30

"""
from alembic import op
import sqlalchemy as sa

revision = 'b46_add_invite_codes'
down_revision = 'b41_add_cover_scale_avatar_crop'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'invite_codes',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('code', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('invite_codes')
