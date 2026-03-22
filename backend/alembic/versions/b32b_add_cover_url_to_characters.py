"""b32b: add cover_url to characters table

Revision ID: b32b_add_cover_url_to_characters
Revises: b14_2_fix_image_enum_values
Create Date: 2026-03-22 00:00:00.000000

Adds a character-scoped cover_url column so each character can have its own
profile cover banner, independent of the account-level user.cover_url.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b32b_add_cover_url_to_characters'
down_revision: Union[str, None] = 'b14_2_fix_image_enum_values'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('cover_url', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'cover_url')
