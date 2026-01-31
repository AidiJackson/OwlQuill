"""Scene model for collaborative roleplay threads."""
from datetime import datetime
import enum

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship

from app.core.database import Base


class SceneVisibilityEnum(str, enum.Enum):
    """Scene visibility levels — maps to existing DB enum scenevisibilityenum."""
    PUBLIC = "PUBLIC"
    UNLISTED = "UNLISTED"
    PRIVATE = "PRIVATE"


class Scene(Base):
    """Scene (collaborative RP thread) model."""

    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(Integer, ForeignKey("realms.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    visibility = Column(
        SQLEnum(SceneVisibilityEnum, name="scenevisibilityenum", create_type=False),
        nullable=False,
        default=SceneVisibilityEnum.PUBLIC,
    )
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    realm = relationship("Realm", backref="scenes")
    creator = relationship("User", backref="created_scenes")
    posts = relationship("ScenePost", back_populates="scene", cascade="all, delete-orphan", order_by="ScenePost.created_at")
