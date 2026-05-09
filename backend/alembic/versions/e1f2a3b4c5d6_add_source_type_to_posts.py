"""add source_type to posts and story_space_posts

Revision ID: e1f2a3b4c5d6
Revises: 08567e37d16e
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = '08567e37d16e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable so existing rows get NULL; application layer defaults NULL → "user" at read time.
    op.add_column('posts', sa.Column('source_type', sa.String(20), nullable=True))
    op.add_column('story_space_posts', sa.Column('source_type', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('story_space_posts', 'source_type')
    op.drop_column('posts', 'source_type')
