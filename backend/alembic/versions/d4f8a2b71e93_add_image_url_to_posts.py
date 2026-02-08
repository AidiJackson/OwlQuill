"""add image_url to posts

Revision ID: d4f8a2b71e93
Revises: ab764bd441f6
Create Date: 2026-02-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4f8a2b71e93'
down_revision: Union[str, None] = 'ab764bd441f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('posts', sa.Column('image_url', sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column('posts', 'image_url')
