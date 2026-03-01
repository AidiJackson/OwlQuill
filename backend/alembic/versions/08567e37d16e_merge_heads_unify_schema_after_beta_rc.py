"""Merge heads: unify schema after beta RC

Revision ID: 08567e37d16e
Revises: e2f3a4b5c6d7, f1a2b3c4d5e6, g1h2i3j4k5l6, h1i2j3k4l5m6
Create Date: 2026-03-01 09:49:21.511854

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08567e37d16e'
down_revision: Union[str, None] = ('e2f3a4b5c6d7', 'f1a2b3c4d5e6', 'g1h2i3j4k5l6', 'h1i2j3k4l5m6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
