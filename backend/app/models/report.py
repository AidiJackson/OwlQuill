"""Content report model for safety controls."""
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship

from app.core.database import Base


class ReportReasonEnum(str, PyEnum):
    """Report reason options."""
    HARASSMENT = "harassment"
    NSFW = "nsfw"
    SPAM = "spam"
    OTHER = "other"


class ReportStatusEnum(str, PyEnum):
    """Report status options."""
    OPEN = "open"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


class ContentReport(Base):
    """ContentReport model - represents a report of problematic content."""
    __tablename__ = "content_reports"

    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_type = Column(String(50), nullable=False)  # "post", "scene_post", etc.
    target_id = Column(Integer, nullable=False)
    reason = Column(
        Enum(ReportReasonEnum),
        default=ReportReasonEnum.OTHER,
        nullable=False
    )
    details = Column(Text, nullable=True)
    status = Column(
        Enum(ReportStatusEnum),
        default=ReportStatusEnum.OPEN,
        nullable=False
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    reporter = relationship("User", back_populates="reports_filed")
