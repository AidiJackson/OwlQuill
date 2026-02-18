"""add_identity_spec_to_characters

Revision ID: b7c3d9e14f82
Revises: a5ba0ecf586c
Create Date: 2026-02-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7c3d9e14f82'
down_revision: Union[str, None] = 'a5ba0ecf586c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('identity_spec_json', sa.Text(), nullable=True))
    op.add_column('characters', sa.Column('identity_spec_version', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('characters', 'identity_spec_version')
    op.drop_column('characters', 'identity_spec_json')
