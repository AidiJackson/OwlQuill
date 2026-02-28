"""Add safety reports table + ban/admin fields to users

Revision ID: g1h2i3j4k5l6
Revises: b2c3d4e5f6a7
Create Date: 2026-02-28

- users: is_admin (bool), is_banned (bool), banned_at (datetime?), ban_reason (str?)
- reports table: reporter_id, target_type, target_id, reason, detail, status,
                 resolved_by_id, resolved_at, created_at
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users: add moderation / role fields ──────────────────────────
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
        batch_op.add_column(
            sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
        batch_op.add_column(sa.Column("banned_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("ban_reason", sa.String(), nullable=True))

    # ── reports table ────────────────────────────────────────────────
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reporter_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_type",
            sa.String(),
            nullable=False,
        ),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column(
            "resolved_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_created_at", "reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_reports_created_at", table_name="reports")
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_reporter_id", table_name="reports")
    op.drop_table("reports")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("ban_reason")
        batch_op.drop_column("banned_at")
        batch_op.drop_column("is_banned")
        batch_op.drop_column("is_admin")
