"""ak01: durable authorship provenance on posts and comments (author_kind)

Revision ID: ak01_author_kind
Revises: p4d3_02_v2_face_card_kinds
Create Date: 2026-10-04

Adds a nullable ``author_kind`` (VARCHAR(16)) to ``posts`` and ``comments``.
See ``app.models.authorship`` for the values and the privacy rule.

WHY. ``character_id`` is ``ON DELETE SET NULL`` on both tables, so after a
character is deleted its posts and comments could not be told apart from a
legacy account-authored post or a Wanderer comment — and the serializers then
published the Writer's private account username to other signed-in readers.
``author_kind`` is written at creation and survives the deletion.

BACKFILL — DETERMINISTIC ONLY.

* ``character_id IS NOT NULL`` → ``'character'``. Certain: the row is attributed
  to a character that still exists.
* ``character_id IS NULL`` → left NULL (UNKNOWN). Such a row may be a genuine
  legacy account-authored post / Wanderer comment, or character content already
  orphaned by an earlier deletion, and nothing in the schema says which. No
  inference is made from account type, timestamps, usernames, ownership or
  content. NULL is privacy-safe by construction: the serializers never show
  account identity for it.

No data outside these two columns is touched, and nothing here reads or
classifies an individual row beyond the ``character_id IS NOT NULL`` test.

Downgrade drops the columns (batch mode, so it also runs on SQLite).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ak01_author_kind"
down_revision: Union[str, tuple] = "p4d3_02_v2_face_card_kinds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("posts", "comments")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("author_kind", sa.String(16), nullable=True))
        op.execute(
            f"UPDATE {table} SET author_kind = 'character' "
            "WHERE character_id IS NOT NULL AND author_kind IS NULL"
        )


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("author_kind")
