"""Add generation_telemetry table for StoryLab token + cost telemetry (S24AZ)

Revision ID: s24az01_gen_telemetry
Revises: e5_editor_jobs
Create Date: 2026-06-24

Adds the ``generation_telemetry`` table — one row per (request, kind) capturing
actual token usage (from the OpenRouter usage object) and estimated USD cost for
every StoryLab generation path: continuation, chapter, summary, rp_reply,
canon_extract. Also serves as the daily-quota counter source for continuation
and RP-reply requests.

Purely additive — no existing table or column is touched, so the migration is
safe to apply and to roll back.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = 's24az01_gen_telemetry'
down_revision: Union[str, None] = 'e5_editor_jobs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_telemetry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("story_id", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_generation_telemetry_id", "generation_telemetry", ["id"])
    op.create_index("ix_generation_telemetry_user_id", "generation_telemetry", ["user_id"])
    op.create_index("ix_generation_telemetry_story_id", "generation_telemetry", ["story_id"])
    op.create_index("ix_generation_telemetry_request_id", "generation_telemetry", ["request_id"])
    op.create_index("ix_generation_telemetry_kind", "generation_telemetry", ["kind"])
    op.create_index("ix_generation_telemetry_created_at", "generation_telemetry", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_generation_telemetry_created_at", table_name="generation_telemetry")
    op.drop_index("ix_generation_telemetry_kind", table_name="generation_telemetry")
    op.drop_index("ix_generation_telemetry_request_id", table_name="generation_telemetry")
    op.drop_index("ix_generation_telemetry_story_id", table_name="generation_telemetry")
    op.drop_index("ix_generation_telemetry_user_id", table_name="generation_telemetry")
    op.drop_index("ix_generation_telemetry_id", table_name="generation_telemetry")
    op.drop_table("generation_telemetry")
