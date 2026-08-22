"""fsi00: merge the three open alembic heads before the founder-image sprint.

The tree had THREE heads — ``b46_add_invite_codes`` (closed-beta invite gate),
``s35_01_identity_pack_jobs`` (async v2 pack jobs) and ``prov01_provenance``
(this branch's provenance sprint) — so ``alembic upgrade head`` could not run at
all, and any new revision would have created a fourth. That pre-existed this
sprint; it is merged here because the founder-image migrations below cannot
otherwise be applied.

This is a pure merge point: no upgrade or downgrade body, no table touched. All
three branches are already independently additive, so ordering between them
carries no data risk.

Revision ID: fsi00_merge_founder_images
Revises: b46_add_invite_codes, s35_01_identity_pack_jobs, prov01_provenance
Create Date: 2026-08-20
"""
from typing import Sequence, Union

revision: str = "fsi00_merge_founder_images"
down_revision: Union[str, tuple, None] = (
    "b46_add_invite_codes",
    "s35_01_identity_pack_jobs",
    "prov01_provenance",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
