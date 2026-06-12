"""e5: add Editor Studio async-job table

Revision ID: e5_editor_jobs
Revises: as04_adult_founder_jobs
Create Date: 2026-06-12

Adds editor_jobs — fire-and-poll backing table for the self_hosted Editor Studio
provider (Sprint E5 Part A). ADDITIVE and non-breaking: no existing table is
modified; Canon Studio, Adult Studio, and the sync /editor/generate path are
untouched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5_editor_jobs"
down_revision: Union[str, tuple] = "as04_adult_founder_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "editor_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False,
                  server_default="self_hosted"),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("pod_id", sa.String(), nullable=True),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("quality_status", sa.String(length=16), nullable=True),
        sa.Column("final_image_url", sa.String(), nullable=True),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_editor_job_run_id"),
    )
    op.create_index(op.f("ix_editor_jobs_id"), "editor_jobs", ["id"])
    op.create_index(op.f("ix_editor_jobs_character_id"), "editor_jobs", ["character_id"])
    op.create_index(op.f("ix_editor_jobs_user_id"), "editor_jobs", ["user_id"])
    op.create_index(op.f("ix_editor_jobs_state"), "editor_jobs", ["state"])
    op.create_index(op.f("ix_editor_jobs_run_id"), "editor_jobs", ["run_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_editor_jobs_run_id"), table_name="editor_jobs")
    op.drop_index(op.f("ix_editor_jobs_state"), table_name="editor_jobs")
    op.drop_index(op.f("ix_editor_jobs_user_id"), table_name="editor_jobs")
    op.drop_index(op.f("ix_editor_jobs_character_id"), table_name="editor_jobs")
    op.drop_index(op.f("ix_editor_jobs_id"), table_name="editor_jobs")
    op.drop_table("editor_jobs")
