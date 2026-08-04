"""add writer_waitlist_joined_at to users

Expression of interest in the Writer Unlock, kept strictly separate from the
entitlement itself:

* ``writer_waitlist_joined_at`` — NULL means "not waiting". Nullable with no
  default and no backfill, so every existing row starts off the waitlist and no
  account's permissions change. Nothing in ``app.core.entitlements`` reads this
  column; joining the waitlist grants nothing.

A timestamp rather than a boolean so the operator readout can report joins over
the last 7 and 30 days, and so withdrawing is simply setting it back to NULL.

Revision ID: tw02_writer_waitlist
Revises: tw01_writer_unlock
Create Date: 2026-08-03 20:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'tw02_writer_waitlist'
down_revision: Union[str, None] = 'tw01_writer_unlock'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('writer_waitlist_joined_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'writer_waitlist_joined_at')
