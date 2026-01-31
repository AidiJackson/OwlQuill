"""Add post_kind to posts

Revision ID: b5e8d2f41c7a
Revises: a3d7c1e92b4f
Create Date: 2026-01-30 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5e8d2f41c7a'
down_revision: Union[str, None] = 'a3d7c1e92b4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('posts', sa.Column('post_kind', sa.String(), nullable=True, server_default='general'))
    op.execute("UPDATE posts SET post_kind = 'general' WHERE post_kind IS NULL")
    with op.batch_alter_table('posts') as batch_op:
        batch_op.alter_column('post_kind', nullable=False, server_default=None)


def downgrade() -> None:
    op.drop_column('posts', 'post_kind')
