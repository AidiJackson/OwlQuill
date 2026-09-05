"""Phase 4A — canonical image asset foundation on character_images

Adds the columns that let an image row say, truthfully and durably, whether
Ficshon ever reviewed it — plus the beginnings of a storage identity that does
not depend on a permanent anonymous delivery URL.

WHAT THIS REVISION DOES NOT DO
------------------------------
Purely additive, and deliberately inert. It changes no existing column, no
existing constraint, and no behaviour: the presentation predicates
(``is_public_surface_safe``, ``is_public_post_image``,
``is_public_gallery_image``) do not read ``safety_state`` and must not begin to
until a moderation path exists to move rows out of ``unreviewed``. Wiring it in
today would either black out every public surface — nothing is approved — or,
worse, read as ``!= 'rejected'``, which is a no-op that looks like protection.

No backfill of any kind. ``user_id`` is untouched, ``storage_key`` is left NULL,
``character_id`` stays NOT NULL. Those are later increments with their own
behavioural consequences.

WHY EVERY EXISTING ROW BECOMES 'unreviewed'
-------------------------------------------
Because that is the only true thing to say about them. Deriving a state from
provider or provenance would record "the old denylist did not reject this" as
"Ficshon approved this", and six months from now the two would be
indistinguishable — which is precisely the confusion these columns exist to end.
``approved`` is writable only by an explicit moderation decision that also
stamps a policy version, a timestamp and a decision source.

Constant server defaults do the work, so no UPDATE runs and every ADD COLUMN is
metadata-only on PostgreSQL 11+ — no table rewrite, no long lock.

THE SERVER DEFAULTS ARE PERMANENT
---------------------------------
Unusually, ``safety_state`` and ``safety_policy_version`` keep their server
defaults rather than having them dropped afterwards. That is the point: an
INSERT from a writing path nobody remembered to update must land on
"not reviewed", fail-closed, at the DDL level — not on whatever a forgotten
Python-side default happens to supply. Thirteen modules currently mint image
files without writing a row at all; when they are fixed, the rows they add
should default to unreviewed without anyone having to remember.

VARCHAR, NOT A POSTGRESQL ENUM
------------------------------
The same call ``prov01`` made for ``provenance``, and this project's own history
is the argument: ``imagekindenum`` has been extended by ``ALTER TYPE ... ADD
VALUE`` three separate times (b33, bc01, bc03), an operation that cannot be
rolled back inside a transaction. Adding a state later — ``review_required`` is
the expected one — must be a CHECK edit, not a type migration.

ALEMBIC LINEAGE
---------------
Descends directly from ``ch02_public_gallery_enabled``, the single head of a
61-revision history. An earlier analysis of this repository reported two heads;
that was an error in the analysis, not in the history — a line-based parser
missed the multi-line ``down_revision`` tuple on
``fsi00_merge_founder_images``, which already joins the provenance branch in.
Alembic's own ScriptDirectory reports one head and the DEV ``alembic_version``
table matches it, so no merge revision is needed or possible.

Written by hand. Autogenerate is not trustworthy against this schema: the enum
type has been rewritten in place (b14_2) and extended by ADD VALUE, and
autogenerate proposes spurious diffs for it.

Revision ID: p4a01_image_safety_state
Revises: ch02_public_gallery_enabled
Create Date: 2026-09-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p4a01_image_safety_state"
down_revision: Union[str, None] = "ch02_public_gallery_enabled"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: An unreviewed row carries NO decision residue, and a decided row carries a
#: complete decision. Nothing in between is representable.
#:
#: ``safety_decided_by`` is constrained only on the unreviewed side. On the
#: decided side it is deliberately free, for two independent reasons: an
#: automated decision has no human account to name, and its FK is ON DELETE SET
#: NULL, so a human decider who later deletes their account turns a populated
#: value into NULL. Requiring it on decided rows would make that FK action
#: illegal — the row would become unsatisfiable at the moment of the delete.
#: ``safety_decision_source`` is what survives both cases, which is why it, and
#: not the FK, is the required field.
#:
#: ``safety_reason`` is deliberately unconstrained. Requiring it for rejections
#: would push automated writers into inserting placeholder text, which is worse
#: than an honest NULL; an automated decision's structured reason lives with its
#: policy version, not in a free-text column.
_AUDIT_COHERENT = """
(
    safety_state = 'unreviewed'
    AND safety_policy_version = 0
    AND safety_decided_at IS NULL
    AND safety_decision_source IS NULL
    AND safety_decided_by IS NULL
)
OR
(
    safety_state IN ('approved', 'rejected')
    AND safety_policy_version > 0
    AND safety_decided_at IS NOT NULL
    AND safety_decision_source IS NOT NULL
)
"""


def upgrade() -> None:
    # ── columns: constant defaults or nullable, so no rewrite ─────────────
    op.add_column(
        "character_images",
        sa.Column(
            "safety_state",
            sa.String(length=32),
            nullable=False,
            server_default="unreviewed",
        ),
    )
    op.add_column(
        "character_images",
        sa.Column(
            "safety_policy_version", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "character_images", sa.Column("safety_decided_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "character_images", sa.Column("safety_decided_by", sa.Integer(), nullable=True)
    )
    op.add_column(
        "character_images",
        sa.Column("safety_decision_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "character_images",
        sa.Column("safety_reason", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "character_images",
        sa.Column("derived_from_image_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "character_images",
        sa.Column("storage_key", sa.String(length=512), nullable=True),
    )

    # ── foreign keys ──────────────────────────────────────────────────────
    # SET NULL on both: losing the decider must not lose the decision, and
    # deleting a source image must not delete everything cropped from it.
    op.create_foreign_key(
        "fk_character_images_safety_decided_by_users",
        "character_images",
        "users",
        ["safety_decided_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_character_images_derived_from_image_id",
        "character_images",
        "character_images",
        ["derived_from_image_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_character_images_safety_state", "character_images", ["safety_state"]
    )

    # ── semantic constraints, last, so they validate the defaulted rows ───
    # No unique index on storage_key yet: it is NULL everywhere until a
    # deterministic backfill has run and been checked for collisions.
    op.create_check_constraint(
        "ck_character_images_safety_state",
        "character_images",
        "safety_state IN ('unreviewed', 'approved', 'rejected')",
    )
    op.create_check_constraint(
        "ck_character_images_safety_decision_source",
        "character_images",
        "safety_decision_source IS NULL "
        "OR safety_decision_source IN ('human', 'automated')",
    )
    op.create_check_constraint(
        "ck_character_images_safety_audit_coherent", "character_images", _AUDIT_COHERENT
    )


def downgrade() -> None:
    """The exact reverse of upgrade.

    Safe while every row is ``unreviewed`` — nothing is lost, because nothing
    has been decided. It stops being safe the moment real moderation decisions
    exist: dropping these columns destroys them, and there is no other record.
    """
    op.drop_constraint(
        "ck_character_images_safety_audit_coherent", "character_images", type_="check"
    )
    op.drop_constraint(
        "ck_character_images_safety_decision_source", "character_images", type_="check"
    )
    op.drop_constraint(
        "ck_character_images_safety_state", "character_images", type_="check"
    )
    op.drop_index("ix_character_images_safety_state", table_name="character_images")
    op.drop_constraint(
        "fk_character_images_derived_from_image_id",
        "character_images",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_character_images_safety_decided_by_users",
        "character_images",
        type_="foreignkey",
    )
    op.drop_column("character_images", "storage_key")
    op.drop_column("character_images", "derived_from_image_id")
    op.drop_column("character_images", "safety_reason")
    op.drop_column("character_images", "safety_decision_source")
    op.drop_column("character_images", "safety_decided_by")
    op.drop_column("character_images", "safety_decided_at")
    op.drop_column("character_images", "safety_policy_version")
    op.drop_column("character_images", "safety_state")
