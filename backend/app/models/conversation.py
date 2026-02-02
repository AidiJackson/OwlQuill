"""Conversation model for 1:1 character messaging."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class Conversation(Base):
    """A 1:1 conversation between exactly two characters."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    character_a_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
    )
    character_b_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    character_a = relationship("Character", foreign_keys=[character_a_id])
    character_b = relationship("Character", foreign_keys=[character_b_id])
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    __table_args__ = (
        UniqueConstraint(
            "character_a_id", "character_b_id", name="uq_conversation_pair"
        ),
        Index("ix_conversation_pair", "character_a_id", "character_b_id"),
    )
