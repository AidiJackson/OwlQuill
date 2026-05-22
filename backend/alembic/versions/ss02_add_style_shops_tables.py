"""Add style_presets and character_style_elements tables

Revision ID: ss02_style_shops
Revises: i3j4k5l6m7n8
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "ss02_style_shops"
down_revision: Union[str, None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "style_presets",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "shop_type",
            sa.Enum("barber", "tattoo", "mask", "jewellery", "weapon", name="shoptypeenum"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "attachment_mode",
            sa.Enum("permanent", "removable", name="attachmentmodeenum"),
            nullable=False,
        ),
        sa.Column(
            "placement",
            sa.Enum(
                "hair", "face", "lower_face", "right_arm", "left_arm",
                "chest", "back", "neck", "hand", "custom",
                name="placementenum",
            ),
            nullable=False,
        ),
        sa.Column("prompt_token", sa.Text(), nullable=False),
        sa.Column("preview_image_url", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spec_patch_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "character_style_elements",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "character_id",
            sa.Integer(),
            sa.ForeignKey("characters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "preset_id",
            sa.Integer(),
            sa.ForeignKey("style_presets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "placement",
            sa.Enum(
                "hair", "face", "lower_face", "right_arm", "left_arm",
                "chest", "back", "neck", "hand", "custom",
                name="placementenum",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="styleelementstatusenum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("character_style_elements")
    op.drop_table("style_presets")
