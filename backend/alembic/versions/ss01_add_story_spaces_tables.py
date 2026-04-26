"""Add story spaces tables

Revision ID: ss01
Revises: 08567e37d16e
Create Date: 2026-04-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ss01"
down_revision: Union[str, None] = "b63_add_stories_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "story_spaces",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_story_spaces_id", "story_spaces", ["id"])
    op.create_index("ix_story_spaces_owner_id", "story_spaces", ["owner_id"])

    op.create_table(
        "story_space_members",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("story_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("invited_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("space_id", "user_id", name="uq_space_member"),
    )
    op.create_index("ix_story_space_members_id", "story_space_members", ["id"])
    op.create_index("ix_story_space_members_space_id", "story_space_members", ["space_id"])
    op.create_index("ix_story_space_members_user_id", "story_space_members", ["user_id"])

    op.create_table(
        "story_space_channels",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("story_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("space_id", "channel_type", name="uq_space_channel_type"),
    )
    op.create_index("ix_story_space_channels_id", "story_space_channels", ["id"])
    op.create_index("ix_story_space_channels_space_id", "story_space_channels", ["space_id"])

    op.create_table(
        "story_space_posts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("story_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("story_space_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(20), nullable=False, server_default="ic"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_story_space_posts_id", "story_space_posts", ["id"])
    op.create_index("ix_story_space_posts_space_id", "story_space_posts", ["space_id"])
    op.create_index("ix_story_space_posts_channel_id", "story_space_posts", ["channel_id"])
    op.create_index("ix_story_space_posts_author_user_id", "story_space_posts", ["author_user_id"])
    op.create_index("ix_space_post_channel_created", "story_space_posts", ["channel_id", "created_at"])

    op.create_table(
        "published_stories",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("space_id", sa.Integer(), sa.ForeignKey("story_spaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("publisher_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.String(512), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("realm_id", sa.Integer(), sa.ForeignKey("realms.id", ondelete="SET NULL"), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_published_stories_id", "published_stories", ["id"])
    op.create_index("ix_published_stories_publisher_user_id", "published_stories", ["publisher_user_id"])

    op.create_table(
        "published_story_segments",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("published_story_id", sa.Integer(), sa.ForeignKey("published_stories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_post_id", sa.Integer(), sa.ForeignKey("story_space_posts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("character_name_snap", sa.String(200), nullable=True),
        sa.Column("content_type", sa.String(20), nullable=False, server_default="ic"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("published_story_id", "position", name="uq_segment_position"),
    )
    op.create_index("ix_published_story_segments_id", "published_story_segments", ["id"])
    op.create_index("ix_published_story_segments_story_id", "published_story_segments", ["published_story_id"])


def downgrade() -> None:
    op.drop_table("published_story_segments")
    op.drop_table("published_stories")
    op.drop_table("story_space_posts")
    op.drop_table("story_space_channels")
    op.drop_table("story_space_members")
    op.drop_table("story_spaces")
