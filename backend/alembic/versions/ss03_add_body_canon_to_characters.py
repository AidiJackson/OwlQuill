"""Add body_canon_json to characters table

Revision ID: ss03_body_canon
Revises: ss02_style_shops
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ss03_body_canon"
down_revision: Union[str, None] = "ss02_style_shops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("body_canon_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("characters", "body_canon_json")
