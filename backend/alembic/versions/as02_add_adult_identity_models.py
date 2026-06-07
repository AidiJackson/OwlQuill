"""as02: add Adult Studio Phase 1 persistence tables

Revision ID: as02_adult_identity_models
Revises: as01_adult_studio_identities
Create Date: 2026-06-07

Adds the production Adult Studio persistence layer (docs/ADULT_STUDIO_PHASE1_DESIGN.md
§4): adult_identity_models, adult_identity_model_versions, adult_identity_training_jobs,
adult_identity_mark_renders.

ADDITIVE and non-breaking. The legacy adult_studio_identities table (and its live
routes) is intentionally left untouched — no data is backfilled here. While the legacy
table is still the live source, copying rows would fork the data; data cutover happens
in a later sprint when the prepare/generate routes are rewired.

Canon tables (characters excepted as an FK target) are NOT modified.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "as02_adult_identity_models"
down_revision: Union[str, tuple] = "as01_adult_studio_identities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── adult_identity_models ────────────────────────────────────────────
    op.create_table(
        "adult_identity_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="not_trained"),
        sa.Column("trigger_token", sa.String(), nullable=True),
        sa.Column("base_model", sa.String(), nullable=True),
        sa.Column("active_version_id", sa.Integer(), nullable=True),
        sa.Column("canon_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("prepared_manifest_json", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id"),
    )
    op.create_index(op.f("ix_adult_identity_models_id"), "adult_identity_models", ["id"])
    op.create_index(op.f("ix_adult_identity_models_character_id"),
                    "adult_identity_models", ["character_id"], unique=True)
    op.create_index(op.f("ix_adult_identity_models_active_version_id"),
                    "adult_identity_models", ["active_version_id"])

    # ── adult_identity_model_versions ────────────────────────────────────
    op.create_table(
        "adult_identity_model_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("version_index", sa.Integer(), nullable=False),
        sa.Column("lora_weights_uri", sa.String(), nullable=True),
        sa.Column("base_model", sa.String(), nullable=True),
        sa.Column("training_config_json", sa.JSON(), nullable=True),
        sa.Column("source_manifest_json", sa.JSON(), nullable=True),
        sa.Column("canon_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["adult_identity_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_id", "version_index", name="uq_adult_version_identity_index"),
    )
    op.create_index(op.f("ix_adult_identity_model_versions_id"),
                    "adult_identity_model_versions", ["id"])
    op.create_index(op.f("ix_adult_identity_model_versions_identity_id"),
                    "adult_identity_model_versions", ["identity_id"])

    # ── adult_identity_training_jobs ─────────────────────────────────────
    op.create_table(
        "adult_identity_training_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_job_id", sa.String(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("logs_uri", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["adult_identity_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["adult_identity_model_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_adult_identity_training_jobs_id"),
                    "adult_identity_training_jobs", ["id"])
    op.create_index(op.f("ix_adult_identity_training_jobs_identity_id"),
                    "adult_identity_training_jobs", ["identity_id"])
    op.create_index(op.f("ix_adult_identity_training_jobs_external_job_id"),
                    "adult_identity_training_jobs", ["external_job_id"])

    # ── adult_identity_mark_renders ──────────────────────────────────────
    op.create_table(
        "adult_identity_mark_renders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identity_id", sa.Integer(), nullable=False),
        sa.Column("canon_mark_id", sa.String(), nullable=False),
        sa.Column("mark_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("mark_type", sa.String(), nullable=True),
        sa.Column("body_region", sa.String(), nullable=True),
        sa.Column("side", sa.String(length=16), nullable=True),
        sa.Column("route", sa.String(length=24), nullable=False, server_default="skip"),
        sa.Column("reference_uri", sa.String(), nullable=True),
        sa.Column("control_asset_uri", sa.String(), nullable=True),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["adult_identity_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_id", "canon_mark_id", name="uq_adult_mark_render_identity_mark"),
    )
    op.create_index(op.f("ix_adult_identity_mark_renders_id"),
                    "adult_identity_mark_renders", ["id"])
    op.create_index(op.f("ix_adult_identity_mark_renders_identity_id"),
                    "adult_identity_mark_renders", ["identity_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_adult_identity_mark_renders_identity_id"),
                  table_name="adult_identity_mark_renders")
    op.drop_index(op.f("ix_adult_identity_mark_renders_id"),
                  table_name="adult_identity_mark_renders")
    op.drop_table("adult_identity_mark_renders")

    op.drop_index(op.f("ix_adult_identity_training_jobs_external_job_id"),
                  table_name="adult_identity_training_jobs")
    op.drop_index(op.f("ix_adult_identity_training_jobs_identity_id"),
                  table_name="adult_identity_training_jobs")
    op.drop_index(op.f("ix_adult_identity_training_jobs_id"),
                  table_name="adult_identity_training_jobs")
    op.drop_table("adult_identity_training_jobs")

    op.drop_index(op.f("ix_adult_identity_model_versions_identity_id"),
                  table_name="adult_identity_model_versions")
    op.drop_index(op.f("ix_adult_identity_model_versions_id"),
                  table_name="adult_identity_model_versions")
    op.drop_table("adult_identity_model_versions")

    op.drop_index(op.f("ix_adult_identity_models_active_version_id"),
                  table_name="adult_identity_models")
    op.drop_index(op.f("ix_adult_identity_models_character_id"),
                  table_name="adult_identity_models")
    op.drop_index(op.f("ix_adult_identity_models_id"),
                  table_name="adult_identity_models")
    op.drop_table("adult_identity_models")
