"""CharacterIdentityCanon — single source of truth for character identity.

This model replaces the fragmented identity data spread across
identity_spec_json, identity_anchor_json, and body_canon_json on the
Character model. Those fields remain for legacy read compatibility but
are NOT written by the new system.

Structure:
  face_canon_json   → serialised FaceCanonData (face images + description)
  body_canon_json   → serialised BodyCanonData (body images + marks + anatomy)
  accessories_json  → serialised list[RemovableAccessory]

canon status: draft → locked (requires both face AND body to be locked)
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class CharacterIdentityCanon(Base):
    __tablename__ = "character_identity_canon"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status = Column(String(20), default="draft", nullable=False)  # draft | locked

    # Face canon
    face_canon_json = Column(Text, nullable=True)
    face_locked = Column(Boolean, default=False, nullable=False)
    face_locked_at = Column(DateTime, nullable=True)

    # Body canon (anatomy + permanent marks + body images)
    body_canon_json = Column(Text, nullable=True)
    body_locked = Column(Boolean, default=False, nullable=False)
    body_locked_at = Column(DateTime, nullable=True)

    # Removable accessories
    accessories_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    locked_at = Column(DateTime, nullable=True)  # set when both face+body are locked

    character = relationship("Character", back_populates="identity_canon")
