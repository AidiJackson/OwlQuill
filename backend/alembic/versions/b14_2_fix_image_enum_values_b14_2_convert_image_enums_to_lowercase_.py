"""b14_2: convert image enums to lowercase values, add identity_sketch and friends

Revision ID: b14_2_fix_image_enum_values
Revises: 08567e37d16e
Create Date: 2026-03-06 22:08:06.955050

Problem
-------
The original migration created PostgreSQL ENUM types with *uppercase member names*
(ANCHOR_FRONT, ACTIVE, PRIVATE …) matching the Python enum member names.  Since
B10/B11 new members were added to ImageKindEnum (ANCHOR_FULL_BODY, IDENTITY_FACE_REF,
IDENTITY_SKETCH) without a matching PostgreSQL migration, any attempt to insert an
image with those kinds raises ``invalid input value for enum imagekindenum``.

Fix
---
1. Recreate all three image enum types using lowercase *values* so they match
   the Python enum member values and the new model ``values_callable`` setting.
2. Convert existing rows from uppercase -> lowercase via lower(col::text).
3. Add the three missing kind values.

This migration is a no-op on SQLite (used in tests) — SQLite does not enforce
native enum types and stores the column as plain TEXT.

Down migration is intentionally omitted (would require re-uppercasing data).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b14_2_fix_image_enum_values'
down_revision: Union[str, None] = '08567e37d16e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        # SQLite / other dialects: nothing to do — column is stored as plain TEXT
        return

    # ── imagekindenum ─────────────────────────────────────────────────
    # Old values (names):  ANCHOR_FRONT ANCHOR_THREE_QUARTER ANCHOR_TORSO GENERATED
    # New values (values): anchor_front anchor_three_quarter anchor_torso anchor_full_body
    #                      generated identity_face_ref identity_sketch

    op.execute("""
        CREATE TYPE imagekindenum_new AS ENUM (
            'anchor_front',
            'anchor_three_quarter',
            'anchor_torso',
            'anchor_full_body',
            'generated',
            'identity_face_ref',
            'identity_sketch'
        )
    """)
    op.execute("""
        ALTER TABLE character_images
            ALTER COLUMN kind
            TYPE imagekindenum_new
            USING lower(kind::text)::imagekindenum_new
    """)
    op.execute("DROP TYPE imagekindenum")
    op.execute("ALTER TYPE imagekindenum_new RENAME TO imagekindenum")

    # ── imagestatusenum ────────────────────────────────────────────────
    # Old: ACTIVE ARCHIVED  ->  New: active archived

    op.execute("CREATE TYPE imagestatusenum_new AS ENUM ('active', 'archived')")
    op.execute("""
        ALTER TABLE character_images
            ALTER COLUMN status
            TYPE imagestatusenum_new
            USING lower(status::text)::imagestatusenum_new
    """)
    op.execute("DROP TYPE imagestatusenum")
    op.execute("ALTER TYPE imagestatusenum_new RENAME TO imagestatusenum")

    # ── imagevisibilityenum ────────────────────────────────────────────
    # Old: PRIVATE PUBLIC  ->  New: private public

    op.execute("CREATE TYPE imagevisibilityenum_new AS ENUM ('private', 'public')")
    op.execute("""
        ALTER TABLE character_images
            ALTER COLUMN visibility
            TYPE imagevisibilityenum_new
            USING lower(visibility::text)::imagevisibilityenum_new
    """)
    op.execute("DROP TYPE imagevisibilityenum")
    op.execute("ALTER TYPE imagevisibilityenum_new RENAME TO imagevisibilityenum")


def downgrade() -> None:
    # Not implemented: re-uppercasing existing data is unsafe without knowing
    # which new values (anchor_full_body, identity_face_ref, identity_sketch)
    # were actually inserted.
    pass
