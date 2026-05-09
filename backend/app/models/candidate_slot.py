"""Candidate slot replacement model for identity evolution Phase 2."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base

VALID_SLOTS = frozenset({"front", "three_quarter", "torso", "full_body"})
VALID_STATUSES = frozenset({"candidate", "promoted", "rejected"})
VALID_VALIDATION_STATUSES = frozenset({"pending", "valid", "warning", "invalid"})


class CandidateSlot(Base):
    """
    Proposed replacement image for a single slot in a character's identity anchor.

    Lifecycle: candidate → (validated) → promoted | rejected.
    Promotion takes a snapshot first, then writes the new image_url into
    identity_anchor_json["anchors"][slot]. Accessories and all other slots
    are preserved. Rollback is always available via the snapshot system.
    """
    __tablename__ = "candidate_slots"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot = Column(String(20), nullable=False)
    image_url = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="candidate")
    validation_status = Column(String(20), nullable=False, default="pending")
    validation_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    character = relationship("Character", foreign_keys=[character_id])
