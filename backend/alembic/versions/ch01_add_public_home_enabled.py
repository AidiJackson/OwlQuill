"""add public_home_enabled to characters (Character Home Step 2)

Founder-granted permission for a character to have an anonymous public
Character Home. Permission only: publication requires this flag AND PUBLIC
visibility, evaluated together by
``app.services.character_publication.character_home_is_publishable``.

Design notes
------------
* Constant ``server_default='false'`` plus ``nullable=False``, matching the
  ``visual_locked`` column already on this table. On Postgres 11+ the
  ``ADD COLUMN`` is metadata-only — no table rewrite, no long lock.

* **No backfill.** Every existing row becomes ``false`` from the server
  default, including characters that are already PUBLIC. Nothing is published
  by this migration; enabling is an explicit founder action per character.

* Independently reversible: the downgrade drops exactly the one column this
  revision added and touches no other data.

Revision ID: ch01_public_home_enabled
Revises: fsi02_image_generation_jobs
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ch01_public_home_enabled'
down_revision: Union[str, None] = 'fsi02_image_generation_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'characters',
        sa.Column(
            'public_home_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('characters', 'public_home_enabled')
