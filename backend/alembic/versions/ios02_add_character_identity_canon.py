"""ios02: add character_identity_canon table — clean identity source of truth

Revision ID: ios02_character_identity_canon
Revises: ios01_identity_os_beta
Create Date: 2026-05-30

Creates the new character_identity_canon table which replaces the fragmented
identity data spread across identity_spec_json, identity_anchor_json, and
body_canon_json fields on the characters table. Those legacy fields are kept
for backward compatibility but are NOT written by the new system.
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "ios02_character_identity_canon"
down_revision: Union[str, tuple] = "ios01_identity_os_beta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "character_identity_canon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("face_canon_json", sa.Text(), nullable=True),
        sa.Column("face_locked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("face_locked_at", sa.DateTime(), nullable=True),
        sa.Column("body_canon_json", sa.Text(), nullable=True),
        sa.Column("body_locked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("body_locked_at", sa.DateTime(), nullable=True),
        sa.Column("accessories_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id"),
    )
    op.create_index(
        op.f("ix_character_identity_canon_character_id"),
        "character_identity_canon",
        ["character_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_character_identity_canon_id"),
        "character_identity_canon",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_character_identity_canon_character_id"),
        table_name="character_identity_canon",
    )
    op.drop_index(
        op.f("ix_character_identity_canon_id"),
        table_name="character_identity_canon",
    )
    op.drop_table("character_identity_canon")
