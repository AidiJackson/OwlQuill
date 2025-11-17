"""Media asset model for uploaded files."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class MediaKind(str, enum.Enum):
    """Types of media assets."""
    USER_AVATAR = "user_avatar"
    CHARACTER_AVATAR = "character_avatar"
    POST_IMAGE = "post_image"


class MediaAsset(Base):
    """Media asset model for tracking uploaded files."""

    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(SQLEnum(MediaKind), nullable=False)
    filename = Column(String, nullable=False)  # Original filename
    path = Column(String, nullable=False, unique=True)  # Relative path from MEDIA_ROOT
    url = Column(String, nullable=False)  # Full URL for serving
    content_type = Column(String, nullable=False)  # MIME type
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
