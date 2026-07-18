"""Add active_character_id to users (Sprint 33 — identity-first foundation)

Revision ID: s33_01_active_character
Revises: s24s2_01_is_seeder
Create Date: 2026-07-18

Adds ``users.active_character_id`` — the owner's currently selected character,
which becomes their visible Ficshon identity (profile, composer default,
switcher). Nullable: NULL means "no explicit selection", in which case the API
falls back to the account's single character when exactly one exists.

Purely additive and reversible. ON DELETE SET NULL so deleting the active
character silently clears the selection.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = 's33_01_active_character'
down_revision: Union[str, None] = 's24s2_01_is_seeder'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "active_character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "active_character_id")
