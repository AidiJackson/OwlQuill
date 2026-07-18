"""Add identity_pack_jobs table for async v2 canon-pack generation (Sprint 35).

Purely additive: creates one new table + indexes. No existing table is touched,
so the migration is safe to apply to the current production database.

Revision ID: s35_01_identity_pack_jobs
Revises: s33_01_active_character
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa

revision = "s35_01_identity_pack_jobs"
down_revision = "s33_01_active_character"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_pack_jobs",
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
        sa.Column("progress_percent", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("diag_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_identity_pack_jobs_id", "identity_pack_jobs", ["id"])
    op.create_index(
        "ix_identity_pack_jobs_public_id", "identity_pack_jobs", ["public_id"], unique=True
    )
    op.create_index("ix_identity_pack_jobs_user_id", "identity_pack_jobs", ["user_id"])
    op.create_index("ix_identity_pack_jobs_character_id", "identity_pack_jobs", ["character_id"])
    op.create_index("ix_identity_pack_jobs_status", "identity_pack_jobs", ["status"])
    op.create_index(
        "ix_identity_pack_jobs_idempotency_key", "identity_pack_jobs", ["idempotency_key"]
    )
    # One active (queued/running) job per character — DB-level race protection.
    op.create_index(
        "ux_identity_pack_jobs_one_active",
        "identity_pack_jobs",
        ["character_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ux_identity_pack_jobs_one_active", table_name="identity_pack_jobs")
    op.drop_index("ix_identity_pack_jobs_idempotency_key", table_name="identity_pack_jobs")
    op.drop_index("ix_identity_pack_jobs_status", table_name="identity_pack_jobs")
    op.drop_index("ix_identity_pack_jobs_character_id", table_name="identity_pack_jobs")
    op.drop_index("ix_identity_pack_jobs_user_id", table_name="identity_pack_jobs")
    op.drop_index("ix_identity_pack_jobs_public_id", table_name="identity_pack_jobs")
    op.drop_index("ix_identity_pack_jobs_id", table_name="identity_pack_jobs")
    op.drop_table("identity_pack_jobs")
