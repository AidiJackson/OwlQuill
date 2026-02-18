"""add_identity_anchor_json_to_characters

Revision ID: c8f5a1d26e93
Revises: b7c3d9e14f82
Create Date: 2026-02-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8f5a1d26e93'
down_revision: Union[str, None] = 'b7c3d9e14f82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('identity_anchor_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'identity_anchor_json')
