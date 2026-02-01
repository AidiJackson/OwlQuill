"""Character Image model — stores anchor and generated images."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class ImageKindEnum(str, enum.Enum):
    """Allowed image kinds."""
    ANCHOR_FRONT = "anchor_front"
    ANCHOR_THREE_QUARTER = "anchor_three_quarter"
    ANCHOR_TORSO = "anchor_torso"
    GENERATED = "generated"


class ImageStatusEnum(str, enum.Enum):
    """Image lifecycle status."""
    ACTIVE = "active"
    ARCHIVED = "archived"


class ImageVisibilityEnum(str, enum.Enum):
    """Image visibility."""
    PRIVATE = "private"
    PUBLIC = "public"


class CharacterImage(Base):
    """An image associated with a character (anchor or generated)."""

    __tablename__ = "character_images"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind = Column(SQLEnum(ImageKindEnum), nullable=False)
    status = Column(SQLEnum(ImageStatusEnum), default=ImageStatusEnum.ACTIVE, nullable=False)
    visibility = Column(SQLEnum(ImageVisibilityEnum), default=ImageVisibilityEnum.PRIVATE, nullable=False)

    provider = Column(String, nullable=True)       # e.g. "stub", "dall-e-3"
    prompt_summary = Column(String, nullable=True)  # short human-readable description
    seed = Column(String, nullable=True)            # reproducibility seed
    metadata_json = Column(JSON, nullable=True)     # arbitrary provider metadata
    file_path = Column(String, nullable=False)      # local path for MVP

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    character = relationship("Character", back_populates="images")
