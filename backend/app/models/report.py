"""Report model — user-submitted content/user reports."""
import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class ReportTargetTypeEnum(str, enum.Enum):
    USER = "user"
    POST = "post"
    COMMENT = "comment"
    MESSAGE = "message"
    IMAGE = "image"
    REALM = "realm"
    SCENE = "scene"
    THREAD = "thread"


class ReportStatusEnum(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class Report(Base):
    """A report submitted by a user about a piece of content or another user."""

    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type = Column(SQLEnum(ReportTargetTypeEnum), nullable=False)
    target_id = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    status = Column(
        SQLEnum(ReportStatusEnum),
        default=ReportStatusEnum.OPEN,
        nullable=False,
        index=True,
    )
    resolved_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    reporter = relationship("User", foreign_keys=[reporter_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])
