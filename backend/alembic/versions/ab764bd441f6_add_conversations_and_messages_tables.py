"""add conversations and messages tables

Revision ID: ab764bd441f6
Revises: a387441c5e69
Create Date: 2026-02-02 20:52:49.853526

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ab764bd441f6'
down_revision: Union[str, None] = 'a387441c5e69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('character_a_id', sa.Integer(), nullable=False),
        sa.Column('character_b_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['character_a_id'], ['characters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_b_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('character_a_id', 'character_b_id', name='uq_conversation_pair')
    )
    op.create_index('ix_conversation_pair', 'conversations', ['character_a_id', 'character_b_id'], unique=False)
    op.create_index(op.f('ix_conversations_id'), 'conversations', ['id'], unique=False)

    op.create_table('messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('sender_character_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_messages_id'), 'messages', ['id'], unique=False)
    op.create_index(op.f('ix_messages_sender_character_id'), 'messages', ['sender_character_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_messages_sender_character_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_conversations_id'), table_name='conversations')
    op.drop_index('ix_conversation_pair', table_name='conversations')
    op.drop_table('conversations')
