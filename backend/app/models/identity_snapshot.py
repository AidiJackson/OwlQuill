"""Identity snapshot model — preserves prior identity state before evolution."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class IdentitySnapshot(Base):
    """
    Point-in-time snapshot of a character's full identity state.

    Created automatically before any evolution attempt (reason="pre_evolution")
    and can be created manually for safekeeping (reason="manual_backup").
    Supports rollback to any prior canon state without data loss.
    """
    __tablename__ = "identity_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Copied from character.identity_spec_version at snapshot time
    snapshot_version = Column(Integer, nullable=False, default=0)
    # Copied from character.dna.anchor_version at snapshot time
    anchor_version = Column(Integer, nullable=False, default=1)
    # Full copy of identity_anchor_json (anchors, accessories, face_signature, lock string)
    identity_anchor_json = Column(Text, nullable=True)
    # Full copy of identity_spec_json (CharacterIdentitySpec structure)
    identity_spec_json = Column(Text, nullable=True)
    # Full copy of body_canon_json (tattoos, scars, burns, birthmarks)
    body_canon_json = Column(Text, nullable=True)
    # Why this snapshot was taken
    reason = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    character = relationship("Character", foreign_keys=[character_id])
