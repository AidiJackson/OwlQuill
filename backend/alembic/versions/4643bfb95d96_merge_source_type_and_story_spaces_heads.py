"""merge source type and story spaces heads

Revision ID: 4643bfb95d96
Revises: e1f2a3b4c5d6, ss01
Create Date: 2026-05-09 18:59:13.712316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4643bfb95d96'
down_revision: Union[str, None] = ('e1f2a3b4c5d6', 'ss01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
