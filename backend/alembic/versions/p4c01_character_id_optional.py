"""Phase 4C — an asset may outlive the character it was made for

Makes ``character_images.character_id`` nullable and moves its foreign key from
``ON DELETE CASCADE`` to ``ON DELETE SET NULL``. Does the same for the two job
tables that record who asked for an image: ``image_generation_jobs`` and
``editor_jobs``.

THE INVARIANT THIS COMPLETES
----------------------------
Phase 4B2 made ``user_id`` NOT NULL: every asset has an owning account. This
revision makes the other column optional, and the pair is the whole point:

    user_id      = ownership   — mandatory, RESTRICT
    character_id = association — optional,  SET NULL

Deleting a character is a statement about a character, not a demolition order
for the person's images. Today it is the latter: the row is destroyed, and with
it the safety decision, the provenance, the lineage and the storage pointer,
while the bytes stay in the bucket. After this revision the asset survives its
association and stays in its owner's library.

THIS IS NOT A NEW PATTERN
-------------------------
``character_images.character_id`` was the LAST character-association column in
the schema still NOT NULL. ``posts``, ``comments``, ``scene_posts``,
``story_space_posts`` and ``published_story_segments`` are all already nullable,
and the first two are already ``SET NULL`` behind an ORM relationship that
declares ``cascade="save-update, merge"``. This revision makes images conform to
the rule the rest of the schema already follows.

WHY THE JOB TABLES MOVE TOO
---------------------------
4B2 deliberately kept requester identity OFF the image row, on the grounds that
it belongs to the job layer. That reasoning only holds if the job layer outlives
the image. With ``ON DELETE CASCADE`` it did not: deleting a character destroyed
the job row — the only record of who requested the generation — at the exact
moment this revision starts preserving the image it produced. An asset that
survives with no record of who asked for it is a worse audit position than the
one 4B2 argued for, so the two FKs move together with the image's.

``job.user_id`` is untouched and remains the requester of record.

WHAT THIS REVISION DOES NOT DO
------------------------------
``user_id`` is untouched — still NOT NULL, still ``ON DELETE RESTRICT``. No
existing row's ``character_id`` is changed: this revision only makes NULL
LEGAL, it never produces one. Nothing is re-associated, archived or deleted.

The matching ORM change (``Character.images`` losing its delete cascade) lands
in the same commit but in ``app/models/character.py``. APPLYING THIS REVISION
WITHOUT THAT CHANGE ACHIEVES NOTHING: SQLAlchemy would still load the images and
DELETE them itself before the database is ever asked, which is the same bypass
4B2 documented one level up. Schema and ORM are one decision here.

Revision ID: p4c01_character_id_optional
Revises: p4b02_user_id_not_null
Create Date: 2026-09-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p4c01_character_id_optional"
down_revision: Union[str, None] = "p4b02_user_id_not_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMN = "character_id"

#: ``(table, fk name to create)``. The names are PostgreSQL's default
#: ``<table>_<column>_fkey`` form, which is what each of these carries on DEV
#: because all three were created inline. The name to DROP is looked up from the
#: catalog rather than assumed — see :func:`_existing_fk_name`.
_TABLES = (
    ("character_images", "character_images_character_id_fkey"),
    ("image_generation_jobs", "image_generation_jobs_character_id_fkey"),
    ("editor_jobs", "editor_jobs_character_id_fkey"),
)


def _existing_fk_name(bind, table: str) -> str:
    """Return the live name of *table*'s ``character_id`` foreign key.

    Read from the database's own catalog. Dropping a constraint by a guessed
    name fails halfway through a migration that has already altered something
    else, which is the worst possible place to discover a naming assumption.
    """
    matches = [
        fk["name"]
        for fk in sa.inspect(bind).get_foreign_keys(table)
        if fk["constrained_columns"] == [_COLUMN]
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one foreign key on {table}.{_COLUMN}, found "
            f"{len(matches)}. Refusing to guess which one to replace."
        )
    return matches[0]


def _dangling_count(bind, table: str) -> int:
    """Rows in *table* pointing at a character that no longer exists."""
    return bind.execute(
        sa.text(
            f"SELECT count(*) FROM {table} t "
            f"LEFT JOIN characters c ON c.id = t.{_COLUMN} "
            f"WHERE t.{_COLUMN} IS NOT NULL AND c.id IS NULL"
        )
    ).scalar_one()


def _null_count(bind, table: str) -> int:
    return bind.execute(
        sa.text(f"SELECT count(*) FROM {table} WHERE {_COLUMN} IS NULL")
    ).scalar_one()


def upgrade() -> None:
    bind = op.get_bind()

    # ── pre-flight ────────────────────────────────────────────────────────
    # A dangling reference here would mean CASCADE had already failed to hold,
    # and the new SET NULL rule would inherit rows pointing at nothing. Say so
    # plainly rather than carrying the inconsistency forward under a new rule.
    for table, _ in _TABLES:
        dangling = _dangling_count(bind, table)
        if dangling:
            raise RuntimeError(
                f"{dangling} {table} row(s) reference a character that does not "
                "exist. Resolve them before making the association optional; "
                "this revision will not silently adopt them."
            )

    for table, fk_name in _TABLES:
        existing = _existing_fk_name(bind, table)
        # Order matters: the old CASCADE must be gone before the column becomes
        # nullable, or there is a moment where a nullable column still carries a
        # rule that destroys its rows.
        op.drop_constraint(existing, table, type_="foreignkey")
        op.alter_column(table, _COLUMN, existing_type=sa.Integer(), nullable=True)
        op.create_foreign_key(
            fk_name, table, "characters", [_COLUMN], ["id"], ondelete="SET NULL"
        )

    # ``ix_character_images_character_id`` and the two job indexes are
    # deliberately untouched. Nullability does not affect a btree index —
    # PostgreSQL indexes NULLs, and ``character_id = :id`` still uses it, which
    # is exactly the lookup every character-scoped route performs.


def downgrade() -> None:
    """Restore NOT NULL with ``ON DELETE CASCADE`` — but only if that is honest.

    REFUSES while any affected row has a NULL ``character_id``. There are
    exactly three ways to satisfy NOT NULL for such a row and all three are
    wrong for a migration to choose:

    * invent an association — attribute somebody's asset to a character that
      never produced it;
    * pick an arbitrary character — the same thing, chosen by ``ORDER BY id``;
    * delete the row — destroy an owned asset, its safety decision and its
      provenance to make a schema change fit.

    A downgrade is a schema operation. Which character an ownerless-of-
    association asset belongs to, or whether it should exist at all, is a
    product decision, and the person running the downgrade is the one who has
    to make it. Re-associate or archive the rows first, then downgrade.

    THIS ALSO WEAKENS THE INVARIANT. After downgrading, deleting a character
    once again destroys its images — rows, safety decisions, provenance and
    lineage — and destroys the job records that say who requested them, while
    the objects remain in the bucket.

    No data is changed by either direction. Nothing here re-associates, archives
    or deletes anything.
    """
    bind = op.get_bind()

    for table, _ in _TABLES:
        orphans = _null_count(bind, table)
        if orphans:
            raise RuntimeError(
                f"{orphans} {table} row(s) have no character. Downgrading would "
                "require inventing an association or deleting them, and neither "
                "is a migration's decision to make. Re-associate or archive them "
                "first."
            )

    for table, fk_name in _TABLES:
        existing = _existing_fk_name(bind, table)
        op.drop_constraint(existing, table, type_="foreignkey")
        op.alter_column(table, _COLUMN, existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(
            fk_name, table, "characters", [_COLUMN], ["id"], ondelete="CASCADE"
        )
