"""User block model for safety controls."""
from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserBlock(Base):
    """UserBlock model - represents one user blocking another."""
    __tablename__ = "user_blocks"

    id = Column(Integer, primary_key=True, index=True)
    blocker_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    blocked_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    blocker = relationship("User", foreign_keys=[blocker_id], back_populates="blocking")
    blocked_user = relationship("User", foreign_keys=[blocked_id], back_populates="blocked_by")

    # Unique constraint - can't block same user twice
    __table_args__ = (
        UniqueConstraint('blocker_id', 'blocked_id', name='unique_block'),
    )
