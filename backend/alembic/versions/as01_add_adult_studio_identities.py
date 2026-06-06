"""as01: add adult_studio_identities table — 18+ Studio per-character state

Revision ID: as01_adult_studio_identities
Revises: ios02_character_identity_canon
Create Date: 2026-06-06

Creates the adult_studio_identities table for the 18+ Studio pipeline. This is
SEPARATE from Canon Studio tables — Adult Studio reads canon as source truth and
stores its own preparation/training state plus a manifest of source images used.
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "as01_adult_studio_identities"
down_revision: Union[str, tuple] = "ios02_character_identity_canon"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "adult_studio_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="not_trained"),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model_ref", sa.String(), nullable=True),
        sa.Column("training_notes_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id"),
    )
    op.create_index(
        op.f("ix_adult_studio_identities_character_id"),
        "adult_studio_identities",
        ["character_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_adult_studio_identities_id"),
        "adult_studio_identities",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_adult_studio_identities_character_id"),
        table_name="adult_studio_identities",
    )
    op.drop_index(
        op.f("ix_adult_studio_identities_id"),
        table_name="adult_studio_identities",
    )
    op.drop_table("adult_studio_identities")
