"""Character DNA model — stores the canonical visual identity specification."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class CharacterDNA(Base):
    """1:1 visual identity specification for a character.

    Captures the traits needed to generate consistent character images
    (the Canonical Visual Anchor / Identity Pack).
    """

    __tablename__ = "character_dna"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Core identity fields (name lives on Character — not duplicated here)
    species = Column(String, nullable=True)
    gender_presentation = Column(String, nullable=True)

    # JSON trait blocks
    visual_traits_json = Column(JSON, nullable=True)          # eye_color, hair_color, skin_tone, distinguishing_features[]
    structural_profile_json = Column(JSON, nullable=True)     # face_shape_category, body_type_category, age_band
    style_permissions_json = Column(JSON, nullable=True)      # { realistic: true, illustrated: false }

    # Anchor versioning
    anchor_version = Column(Integer, default=1, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    character = relationship("Character", back_populates="dna")
