"""User Image model — stores generated profile images (covers, etc.)."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserImage(Base):
    """An image associated with a user (profile cover, etc.)."""

    __tablename__ = "user_images"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind = Column(String, nullable=False)  # e.g. "profile_cover"
    status = Column(String, default="active", nullable=False)
    provider = Column(String, nullable=True)  # e.g. "openai"
    prompt_summary = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    file_path = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="images")
