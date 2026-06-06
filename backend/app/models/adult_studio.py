"""Adult Studio identity model — 18+ Studio per-character state.

SEPARATE from Canon Studio. This table does NOT modify or replace any canon
table (CharacterIdentityCanon, CharacterImage, etc.). Adult Studio READS canon
as source of truth and stores its own preparation/training state and the
manifest of canon source images it used.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


# status lifecycle: not_trained → preparing → ready | failed
ADULT_STUDIO_STATUSES = ("not_trained", "preparing", "ready", "failed")


class AdultStudioIdentity(Base):
    """Per-character 18+ Studio identity preparation state."""

    __tablename__ = "adult_studio_identities"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status = Column(String(20), default="not_trained", nullable=False)
    provider = Column(String, nullable=True)        # e.g. "openai"
    model_ref = Column(String, nullable=True)       # e.g. "gpt-image-1.5" or future LoRA id
    # Manifest/notes JSON: the canon source images collected during prepare,
    # plus any training notes. Never canon truth — a snapshot reference.
    training_notes_json = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    character = relationship("Character")
