"""add public_gallery_enabled to character_images (Character Home Step 6.5)

Creator selection for the Character Home gallery: "the creator has picked this
image to be displayed in the Character Home gallery." One meaning, one column.

Design notes
------------
* A NEW column rather than a new state on ``character_images.visibility``.
  ``visibility`` is left completely untouched — same type, same values, same
  meaning — because gallery curation and image visibility are different
  questions and one field cannot answer both without becoming ambiguous.

* Constant ``server_default='false'`` plus ``nullable=False``, matching
  ``characters.public_home_enabled`` added by ``ch01``. On Postgres 11+ the
  ``ADD COLUMN`` is metadata-only — no table rewrite, no long lock, which
  matters on a table this large.

* **No backfill.** Every existing row becomes ``false``, including images that
  are already gallery-eligible and already visible to signed-in members.
  Nothing becomes publicly selected as a side effect of this migration:
  selecting an image is an explicit creator act, per image.

* Selection is not authority. An image reaches an anonymous Character Home
  gallery only when the Home is published AND the creator selected it AND
  ``is_public_gallery_image`` allows it. This column is only the middle layer.

* Independently reversible: the downgrade drops exactly the one column this
  revision added and touches no other data.

Revision ID: ch02_public_gallery_enabled
Revises: ch01_public_home_enabled
Create Date: 2026-09-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ch02_public_gallery_enabled'
down_revision: Union[str, None] = 'ch01_public_home_enabled'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'character_images',
        sa.Column(
            'public_gallery_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('character_images', 'public_gallery_enabled')
