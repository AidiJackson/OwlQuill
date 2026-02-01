"""add_character_dna_and_character_images

Revision ID: 72e94203f23d
Revises: c7d4e8f21a3b
Create Date: 2026-02-01 18:12:39.061955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '72e94203f23d'
down_revision: Union[str, None] = 'c7d4e8f21a3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('character_dna',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('character_id', sa.Integer(), nullable=False),
    sa.Column('species', sa.String(), nullable=True),
    sa.Column('gender_presentation', sa.String(), nullable=True),
    sa.Column('visual_traits_json', sa.JSON(), nullable=True),
    sa.Column('structural_profile_json', sa.JSON(), nullable=True),
    sa.Column('style_permissions_json', sa.JSON(), nullable=True),
    sa.Column('anchor_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_character_dna_character_id'), 'character_dna', ['character_id'], unique=True)
    op.create_index(op.f('ix_character_dna_id'), 'character_dna', ['id'], unique=False)
    op.create_table('character_images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('character_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('ANCHOR_FRONT', 'ANCHOR_THREE_QUARTER', 'ANCHOR_TORSO', 'GENERATED', name='imagekindenum'), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'ARCHIVED', name='imagestatusenum'), nullable=False),
    sa.Column('visibility', sa.Enum('PRIVATE', 'PUBLIC', name='imagevisibilityenum'), nullable=False),
    sa.Column('provider', sa.String(), nullable=True),
    sa.Column('prompt_summary', sa.String(), nullable=True),
    sa.Column('seed', sa.String(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('file_path', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_character_images_character_id'), 'character_images', ['character_id'], unique=False)
    op.create_index(op.f('ix_character_images_id'), 'character_images', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_character_images_id'), table_name='character_images')
    op.drop_index(op.f('ix_character_images_character_id'), table_name='character_images')
    op.drop_table('character_images')
    op.drop_index(op.f('ix_character_dna_id'), table_name='character_dna')
    op.drop_index(op.f('ix_character_dna_character_id'), table_name='character_dna')
    op.drop_table('character_dna')
