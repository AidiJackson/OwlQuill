"""Add is_seeder flag to users (Step 2 — seeding exemption)

Revision ID: s24s2_01_is_seeder
Revises: s24az01_gen_telemetry
Create Date: 2026-07-15

Adds a dedicated ``is_seeder`` boolean flag to the ``users`` table. Seeder
accounts are exempt from the one-character-per-account limit (so founder /
seeding accounts can hold multiple characters) WITHOUT being granted full admin
powers. See app/services/seeding.py::is_seeder_account for how the exemption is
scoped (is_admin flag / is_seeder flag / ADMIN_EMAILS / SEEDER_EMAILS).

Purely additive with a server_default of ``false`` so existing rows become
non-seeders — safe to apply and roll back.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = 's24s2_01_is_seeder'
down_revision: Union[str, None] = 's24az01_gen_telemetry'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_seeder",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_seeder")
