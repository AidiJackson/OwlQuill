"""Add rp_story_threads and rp_story_turns tables

Revision ID: rp01_rp_story_threads
Revises: ss03_body_canon
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "rp01_rp_story_threads"
down_revision: Union[str, None] = "ss03_body_canon"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rp_story_threads",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("selected_character_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("partner_label", sa.String(100), nullable=True),
        sa.Column("partner_pov", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("summary_memory", sa.Text(), nullable=True),
        sa.Column("style_memory", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rp_story_threads_id", "rp_story_threads", ["id"])
    op.create_index("ix_rp_story_threads_user_id", "rp_story_threads", ["user_id"])

    op.create_table(
        "rp_story_turns",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("rp_story_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("author_type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("godmod_detected", sa.Boolean(), nullable=True),
        sa.Column("godmod_severity", sa.String(10), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("thread_id", "turn_index", name="uq_rp_story_turn"),
    )
    op.create_index("ix_rp_story_turns_id", "rp_story_turns", ["id"])
    op.create_index("ix_rp_story_turns_thread_id", "rp_story_turns", ["thread_id"])


def downgrade() -> None:
    op.drop_table("rp_story_turns")
    op.drop_table("rp_story_threads")
