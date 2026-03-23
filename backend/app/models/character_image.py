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
    ANCHOR_FULL_BODY = "anchor_full_body"
    GENERATED = "generated"
    COVER = "cover"                           # character cover/banner image
    IDENTITY_FACE_REF = "identity_face_ref"  # tight face crop used as reference seed
    IDENTITY_SKETCH = "identity_sketch"       # pre-pack pencil/charcoal/dossier sketch anchor


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
    # user_id tracks which user generated this image (used for weekly quota).
    # Nullable for legacy images created before quota enforcement.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # values_callable ensures SQLAlchemy stores the enum VALUE (e.g. "identity_sketch")
    # not the member NAME (e.g. "IDENTITY_SKETCH").  The PostgreSQL enum type is
    # recreated by migration b14_2 to use the same lowercase value strings.
    kind = Column(
        SQLEnum(ImageKindEnum, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    status = Column(
        SQLEnum(ImageStatusEnum, values_callable=lambda obj: [e.value for e in obj]),
        default=ImageStatusEnum.ACTIVE,
        nullable=False,
    )
    visibility = Column(
        SQLEnum(ImageVisibilityEnum, values_callable=lambda obj: [e.value for e in obj]),
        default=ImageVisibilityEnum.PRIVATE,
        nullable=False,
    )

    provider = Column(String, nullable=True)       # e.g. "stub", "dall-e-3"
    prompt_summary = Column(String, nullable=True)  # short human-readable description
    seed = Column(String, nullable=True)            # reproducibility seed
    metadata_json = Column(JSON, nullable=True)     # arbitrary provider metadata
    file_path = Column(String, nullable=False)      # local path for MVP

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    character = relationship("Character", back_populates="images")
