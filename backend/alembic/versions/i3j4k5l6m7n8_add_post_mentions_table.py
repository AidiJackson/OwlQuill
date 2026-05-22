"""Add post_mentions table

Revision ID: i3j4k5l6m7n8
Revises: g2h3i4j5k6l7
Create Date: 2026-05-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, None] = "g2h3i4j5k6l7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "post_id",
            sa.Integer(),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mention_text",
            sa.String(100),
            nullable=False,
        ),
        sa.Column(
            "mentioned_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "mentioned_character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_post_mentions_post_id", "post_mentions", ["post_id"])
    op.create_index("ix_post_mentions_mentioned_user_id", "post_mentions", ["mentioned_user_id"])
    op.create_index("ix_post_mentions_mentioned_character_id", "post_mentions", ["mentioned_character_id"])


def downgrade() -> None:
    op.drop_index("ix_post_mentions_mentioned_character_id", "post_mentions")
    op.drop_index("ix_post_mentions_mentioned_user_id", "post_mentions")
    op.drop_index("ix_post_mentions_post_id", "post_mentions")
    op.drop_table("post_mentions")
