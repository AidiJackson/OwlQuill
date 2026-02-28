"""storylab: add user ownership to story_state

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-02-28

Adds user_id FK to story_state so every story workspace is tied to its
owning authenticated user.  Existing rows (pre-auth) keep user_id=NULL
and are effectively invisible through the auth-gated API.  The column is
nullable intentionally — a NOT NULL constraint cannot be added without a
backfill strategy, and NULL is a safe sentinel for legacy data.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("story_state") as batch_op:
        batch_op.add_column(
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            )
        )
        batch_op.create_index("ix_story_state_user_id", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("story_state") as batch_op:
        batch_op.drop_index("ix_story_state_user_id")
        batch_op.drop_column("user_id")
