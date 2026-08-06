"""evidence-based content provenance

Adds the inline provenance columns to every table holding user-visible text,
plus the two supporting tables: composition sessions (shared editor
infrastructure) and AI output fingerprints.

Design notes
------------
* Every added column carries a constant ``server_default``, so on Postgres 11+
  each ``ADD COLUMN`` is metadata-only — no table rewrite and no long lock.

* **No backfill.** Existing rows become ``provenance='unknown'`` with
  ``provenance_rule_version=0`` ("never evaluated"). Backfilling them to
  ``user_written`` would repeat, at scale, the exact defect this replaces: a
  badge asserted without evidence. Clients render ``unknown`` as no badge.

* ``provenance`` is ``String(32)``, not an enum type, and is sized well beyond
  the longest value in use. Adding a state later — the reserved
  ``external`` / ``imported`` verdict — must not require a migration.

* The legacy ``source_type`` columns on ``posts`` and ``story_space_posts`` are
  left in place, unread and unwritten, so this revision can be rolled back
  without data loss. They are dropped in a follow-up.

Revision ID: prov01_provenance
Revises: tw02_writer_waitlist
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'prov01_provenance'
down_revision: Union[str, None] = 'tw02_writer_waitlist'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Every table holding text that can carry a public authorship badge.
PROVENANCE_TABLES = (
    'posts',
    'story_space_posts',
    'comments',
    'scene_posts',
    'published_stories',
    'published_story_segments',
    'rp_story_turns',
)


def upgrade() -> None:
    for table in PROVENANCE_TABLES:
        op.add_column(
            table,
            sa.Column(
                'provenance',
                sa.String(32),
                nullable=False,
                server_default='unknown',
            ),
        )
        op.add_column(table, sa.Column('provenance_evidence', sa.JSON(), nullable=True))
        op.add_column(
            table,
            sa.Column(
                'provenance_rule_version',
                sa.SmallInteger(),
                nullable=False,
                server_default='0',
            ),
        )
        op.add_column(
            table, sa.Column('provenance_decided_at', sa.DateTime(), nullable=True)
        )

    op.create_table(
        'composition_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('surface', sa.String(32), nullable=False),
        sa.Column('target_kind', sa.String(32), nullable=True),
        sa.Column('target_ref', sa.String(64), nullable=True),
        sa.Column(
            'parent_session_id',
            sa.String(36),
            sa.ForeignKey('composition_sessions.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('status', sa.String(16), nullable=False, server_default='open'),
        sa.Column('metrics_json', sa.JSON(), nullable=False),
        sa.Column('state_json', sa.JSON(), nullable=False),
        sa.Column('committed_kind', sa.String(32), nullable=True),
        sa.Column('committed_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_active_at', sa.DateTime(), nullable=False),
        sa.Column('committed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_composition_sessions_user_id', 'composition_sessions', ['user_id'])
    op.create_index(
        'ix_composition_session_user_status', 'composition_sessions', ['user_id', 'status']
    )
    op.create_index('ix_composition_session_created', 'composition_sessions', ['created_at'])

    op.create_table(
        'ai_output_fingerprints',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('shingle_hash', sa.BigInteger(), nullable=False),
        sa.Column('source_kind', sa.String(32), nullable=False),
        sa.Column('source_ref', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_ai_output_fingerprints_id', 'ai_output_fingerprints', ['id'])
    # The only query shape used: "any of these hashes, for this author".
    op.create_index(
        'ix_ai_fingerprint_user_hash', 'ai_output_fingerprints', ['user_id', 'shingle_hash']
    )
    op.create_index('ix_ai_fingerprint_created', 'ai_output_fingerprints', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_ai_fingerprint_created', table_name='ai_output_fingerprints')
    op.drop_index('ix_ai_fingerprint_user_hash', table_name='ai_output_fingerprints')
    op.drop_index('ix_ai_output_fingerprints_id', table_name='ai_output_fingerprints')
    op.drop_table('ai_output_fingerprints')

    op.drop_index('ix_composition_session_created', table_name='composition_sessions')
    op.drop_index('ix_composition_session_user_status', table_name='composition_sessions')
    op.drop_index('ix_composition_sessions_user_id', table_name='composition_sessions')
    op.drop_table('composition_sessions')

    for table in PROVENANCE_TABLES:
        op.drop_column(table, 'provenance_decided_at')
        op.drop_column(table, 'provenance_rule_version')
        op.drop_column(table, 'provenance_evidence')
        op.drop_column(table, 'provenance')
