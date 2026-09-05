"""Phase 4B2 — every image asset must have an owning account

Makes ``character_images.user_id`` NOT NULL and moves its foreign key from
``ON DELETE SET NULL`` to ``ON DELETE RESTRICT``.

WHY BOTH, AND WHY TOGETHER
--------------------------
NOT NULL and ``SET NULL`` are not a stricter schema — they are a schema in
which deleting an account raises a not-null violation from inside the FK
action, with no explanation attached. The nullability and the delete rule are
one decision and have to move in one revision.

``RESTRICT`` is the honest interim answer to "what happens to someone's images
when their account is deleted?". Ficshon has not decided that yet: there is no
retention policy, no tombstone model, no deletion worker, and no R2 story for
the bytes. ``CASCADE`` would decide it silently — destroying rows (and their
safety decisions) while leaving the objects in the bucket — as a side effect of
a constraint tidy-up. ``RESTRICT`` instead makes an account deletion FAIL while
owned assets remain, which is a refusal somebody has to read and answer rather
than a policy nobody chose.

Nothing is lost by that today: there is no account-deletion route in the API,
and ``scripts/reset_account.py`` already refuses while the account owns any
character.

WHY IT MUST LAND BEFORE PHASE 4C
--------------------------------
4C makes ``character_id`` nullable and moves its FK to ``SET NULL`` so an asset
survives its character. Combine that with the OLD ``user_id`` rule and deleting
an account produces rows with no character and no owner: bytes in a bucket that
no query can attribute to anyone. That is the ownerless-asset model this whole
sequence exists to prevent, and this revision is the gate.

WHAT THIS REVISION DOES NOT DO
------------------------------
``character_id`` is untouched — still NOT NULL, still ``ON DELETE CASCADE``.
``Character.images`` keeps ``all, delete-orphan``. No ORM cascade is added from
``User``: choosing ``RESTRICT`` at the database and then re-creating the
destruction in SQLAlchemy would defeat the entire point, since the ORM deletes
children itself and the FK never gets asked.

SAFE TO RUN
-----------
The backfill in Phase 4B1 left DEV with 1,429 rows, zero NULL ``user_id``, zero
owners disagreeing with ``characters.owner_id`` and zero dangling references.
``upgrade()`` re-asserts the first of those against the live database before it
alters anything, so a target that has drifted gets a named refusal instead of an
opaque constraint violation mid-ALTER.

Written by hand. Autogenerate is not trustworthy against this schema (see
``p4a01``), and it would not produce the pre-flight check or the correct FK
action anyway.

Revision ID: p4b02_user_id_not_null
Revises: p4a01_image_safety_state
Create Date: 2026-09-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p4b02_user_id_not_null"
down_revision: Union[str, None] = "p4a01_image_safety_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "character_images"
_COLUMN = "user_id"

#: The name the constraint carries on DEV, read from ``pg_constraint`` rather
#: than assumed — it was created inline by ``f1a2b3c4d5e6`` and therefore got
#: PostgreSQL's default ``<table>_<column>_fkey`` form. :func:`_existing_fk_name`
#: still looks it up at run time, so a database where it was recreated under a
#: different name is handled rather than crashed into.
_KNOWN_FK_NAME = "character_images_user_id_fkey"


def _existing_fk_name(bind) -> str:
    """Return the live name of the ``user_id`` foreign key.

    Uses the database's own catalog instead of trusting a literal, because
    dropping a constraint by a guessed name fails halfway through a migration
    that has already altered something else.
    """
    inspector = sa.inspect(bind)
    matches = [
        fk["name"]
        for fk in inspector.get_foreign_keys(_TABLE)
        if fk["constrained_columns"] == [_COLUMN]
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one foreign key on {_TABLE}.{_COLUMN}, found "
            f"{len(matches)}. Refusing to guess which one to replace."
        )
    return matches[0]


def upgrade() -> None:
    bind = op.get_bind()

    # ── pre-flight ────────────────────────────────────────────────────────
    # A NULL here means some writer created an ownerless row after the 4B1
    # backfill. Say so plainly; the alternative is a NotNullViolation from
    # inside ALTER COLUMN that names no cause.
    orphaned = bind.execute(
        sa.text(f"SELECT count(*) FROM {_TABLE} WHERE {_COLUMN} IS NULL")
    ).scalar_one()
    if orphaned:
        raise RuntimeError(
            f"{orphaned} {_TABLE} row(s) have no owning account. Run "
            "scripts/backfill_character_image_owners.py and fix whichever "
            "writer is still creating ownerless rows before applying this "
            "revision."
        )

    fk_name = _existing_fk_name(bind)

    # Order matters: the old SET NULL action must be gone before the column
    # becomes NOT NULL, or the two contradict each other in between.
    op.drop_constraint(fk_name, _TABLE, type_="foreignkey")
    op.alter_column(
        _TABLE, _COLUMN, existing_type=sa.Integer(), nullable=False
    )
    op.create_foreign_key(
        _KNOWN_FK_NAME,
        _TABLE,
        "users",
        [_COLUMN],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Restore a nullable ``user_id`` with ``ON DELETE SET NULL``.

    THIS WEAKENS THE OWNERSHIP INVARIANT. After downgrading, a row may again
    exist with no owning account, and deleting an account silently detaches its
    assets instead of refusing. Every ownership check added in Phase 4B1 reads
    ``user_id``, so an ownerless row created while downgraded belongs to nobody:
    it is absent from its owner's library and cannot be used as an avatar or
    cover by anyone at all.

    No data is changed. Existing ``user_id`` values are left exactly as they
    are — a downgrade must not undo the backfill, because re-running the
    upgrade would then depend on data this function destroyed.
    """
    bind = op.get_bind()
    fk_name = _existing_fk_name(bind)

    op.drop_constraint(fk_name, _TABLE, type_="foreignkey")
    op.alter_column(
        _TABLE, _COLUMN, existing_type=sa.Integer(), nullable=True
    )
    op.create_foreign_key(
        _KNOWN_FK_NAME,
        _TABLE,
        "users",
        [_COLUMN],
        ["id"],
        ondelete="SET NULL",
    )
