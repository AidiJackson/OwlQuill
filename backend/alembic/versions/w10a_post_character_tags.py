"""w10a: post_character_tags — explicit character tagging on posts

Revision ID: w10a_post_character_tags
Revises: ak01_author_kind
Create Date: 2026-10-06

Adds ``post_character_tags``: one row per character an author deliberately
tagged on a post. See ``app.models.post_character_tag``.

* ``post_id``      -> posts.id       ON DELETE CASCADE
* ``character_id`` -> characters.id  ON DELETE CASCADE (indexed)
* UNIQUE (post_id, character_id)

IDs only: no character name and no account id is stored.

ADDITIVE, NO BACKFILL. Existing posts simply have no tag rows; legacy
``post_mentions`` are untouched and are not converted.

DEPLOY ORDER. ``Post.character_tags`` is eager-loaded, so application code
from this revision onward queries the table on every post read. Apply this
migration to a database BEFORE deploying the code that uses it. The previous
code ignores the table, so running it against an upgraded database is safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "w10a_post_character_tags"
down_revision: Union[str, tuple] = "ak01_author_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post_character_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "post_id",
            sa.Integer(),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("post_id", "character_id", name="uq_post_character_tag"),
    )
    op.create_index(
        "ix_post_character_tags_character_id", "post_character_tags", ["character_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_post_character_tags_character_id", "post_character_tags")
    op.drop_table("post_character_tags")
