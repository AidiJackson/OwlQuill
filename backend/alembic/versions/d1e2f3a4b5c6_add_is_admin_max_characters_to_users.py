"""Add is_admin and max_characters to users

Revision ID: d1e2f3a4b5c6
Revises: b2c3d4e5f6a7
Create Date: 2026-02-28

Adds:
  - users.is_admin  (Boolean, server_default=false)  — marks accounts with admin privileges
  - users.max_characters (Integer, server_default=1)  — per-user character creation cap

Existing rows get the safe defaults (non-admin, cap=1) with no backfill needed.
Uses batch_alter_table for SQLite compatibility; op.add_column with server_default
is safe on PostgreSQL.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "max_characters",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("max_characters")
        batch_op.drop_column("is_admin")
