"""bc02: add body_canon_json column to identity_snapshots

Revision ID: bc02_body_canon_snapshot
Revises: bc01_body_identity_kinds
Create Date: 2026-05-23

Captures body_canon_json (tattoos/scars/burns/birthmarks) at snapshot time
so rollback does not silently drop body markings added after the snapshot.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bc02_body_canon_snapshot"
down_revision: Union[str, None] = "bc01_body_identity_kinds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "identity_snapshots",
        sa.Column("body_canon_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("identity_snapshots", "body_canon_json")
