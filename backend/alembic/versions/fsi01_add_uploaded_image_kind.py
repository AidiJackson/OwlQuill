"""fsi01: add the 'uploaded' value to imagekindenum (founder/seeder uploads).

Extends imagekindenum with:
  uploaded — an image the founder/seeder supplied from their own device. It is
             ordinary private character media, usable as a generation
             reference. It is NOT canon and NOT an identity slot.

Purely additive. No existing row changes kind, no existing table is altered.

On SQLite (tests) the column is plain TEXT, so no DDL is required — the same
no-op the earlier enum migrations (bc01, bc03, ios01) take.
On PostgreSQL, ALTER TYPE ... ADD VALUE IF NOT EXISTS is used.
Downgrade is a no-op: PostgreSQL cannot remove enum values.

Revision ID: fsi01_uploaded_image_kind
Revises: fsi00_merge_founder_images
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "fsi01_uploaded_image_kind"
down_revision: Union[str, tuple] = "fsi00_merge_founder_images"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = ("uploaded",)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE imagekindenum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass
