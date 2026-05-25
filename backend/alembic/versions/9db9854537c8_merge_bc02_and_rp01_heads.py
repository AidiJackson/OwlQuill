"""merge_bc02_and_rp01_heads

Revision ID: 9db9854537c8
Revises: bc02_body_canon_snapshot, rp01_rp_story_threads
Create Date: 2026-05-25 14:12:13.242669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9db9854537c8'
down_revision: Union[str, None] = ('bc02_body_canon_snapshot', 'rp01_rp_story_threads')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
