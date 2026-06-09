"""as04: add Adult Studio founder async-job table

Revision ID: as04_adult_founder_jobs
Revises: as03_backfill_adult_identity
Create Date: 2026-06-09

Adds adult_founder_jobs — the single tiny table backing the founder-only fire-and-poll
Generate path (Phase 3, Sprint 13). ADDITIVE and non-breaking. No existing table is
modified; Canon Studio and the normal image generator are untouched. The detached RunPod
driver writes a run_id-scoped report file; the service reconciles each row from that file.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "as04_adult_founder_jobs"
down_revision: Union[str, tuple] = "as03_backfill_adult_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "adult_founder_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("pod_id", sa.String(), nullable=True),
        sa.Column("final_image_url", sa.String(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_adult_founder_job_run_id"),
    )
    op.create_index(op.f("ix_adult_founder_jobs_id"), "adult_founder_jobs", ["id"])
    op.create_index(op.f("ix_adult_founder_jobs_character_id"),
                    "adult_founder_jobs", ["character_id"])
    op.create_index(op.f("ix_adult_founder_jobs_state"), "adult_founder_jobs", ["state"])
    op.create_index(op.f("ix_adult_founder_jobs_run_id"),
                    "adult_founder_jobs", ["run_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_adult_founder_jobs_run_id"), table_name="adult_founder_jobs")
    op.drop_index(op.f("ix_adult_founder_jobs_state"), table_name="adult_founder_jobs")
    op.drop_index(op.f("ix_adult_founder_jobs_character_id"), table_name="adult_founder_jobs")
    op.drop_index(op.f("ix_adult_founder_jobs_id"), table_name="adult_founder_jobs")
    op.drop_table("adult_founder_jobs")
