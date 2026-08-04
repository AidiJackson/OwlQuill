"""add writer_unlocked_at and username_changed_at to users

Two independent account facts, both nullable and both defaulting to NULL, so
existing rows need no backfill:

* ``writer_unlocked_at`` — NULL means Wanderer. Every pre-existing account
  therefore starts as a Wanderer for the purposes of *creating a new*
  character; accounts that already own one keep their creator workspaces via
  the character-count term in ``app.core.entitlements.can_use_creator_tools``.
* ``username_changed_at`` — NULL means "never renamed", so no account begins
  life inside the rename cooldown.

Revision ID: tw01_writer_unlock
Revises: s35_01_identity_pack_jobs
Create Date: 2026-07-25 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'tw01_writer_unlock'
down_revision: Union[str, None] = 's35_01_identity_pack_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('writer_unlocked_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('username_changed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'username_changed_at')
    op.drop_column('users', 'writer_unlocked_at')
