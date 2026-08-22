"""fsi02: add image_generation_jobs for async founder image generation.

Purely additive: creates one new table + indexes. No existing table is touched,
so the migration is safe to apply to the current production database.

The unique index ``ux_image_generation_jobs_idem`` on (user_id, idempotency_key)
is the paid-spend guarantee: one generation intent can only ever own one job
row, so a double-tap / proxy retry / reconnect resolves to the existing job
instead of buying a second image. It is intentionally NOT partial — a terminal
job keeps its key reserved.

Revision ID: fsi02_image_generation_jobs
Revises: fsi01_uploaded_image_kind
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "fsi02_image_generation_jobs"
down_revision: Union[str, tuple] = "fsi01_uploaded_image_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "image_generation_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("progress_message", sa.String(length=200), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column(
            "image_id",
            sa.Integer(),
            sa.ForeignKey("character_images.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("error_message", sa.String(length=400), nullable=True),
        sa.Column("diag_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_image_generation_jobs_id", "image_generation_jobs", ["id"])
    op.create_index(
        "ix_image_generation_jobs_public_id", "image_generation_jobs", ["public_id"], unique=True
    )
    op.create_index("ix_image_generation_jobs_user_id", "image_generation_jobs", ["user_id"])
    op.create_index(
        "ix_image_generation_jobs_character_id", "image_generation_jobs", ["character_id"]
    )
    op.create_index("ix_image_generation_jobs_status", "image_generation_jobs", ["status"])
    op.create_index(
        "ix_image_generation_jobs_idempotency_key",
        "image_generation_jobs",
        ["idempotency_key"],
    )
    # One generation intent per user → one job row → one paid submission.
    op.create_index(
        "ux_image_generation_jobs_idem",
        "image_generation_jobs",
        ["user_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_image_generation_jobs_idem", table_name="image_generation_jobs")
    op.drop_index(
        "ix_image_generation_jobs_idempotency_key", table_name="image_generation_jobs"
    )
    op.drop_index("ix_image_generation_jobs_status", table_name="image_generation_jobs")
    op.drop_index("ix_image_generation_jobs_character_id", table_name="image_generation_jobs")
    op.drop_index("ix_image_generation_jobs_user_id", table_name="image_generation_jobs")
    op.drop_index("ix_image_generation_jobs_public_id", table_name="image_generation_jobs")
    op.drop_index("ix_image_generation_jobs_id", table_name="image_generation_jobs")
    op.drop_table("image_generation_jobs")
