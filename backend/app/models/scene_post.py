"""ScenePost model for individual turns within a scene."""
from datetime import datetime

from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class ScenePost(Base):
    """Individual turn/post within a scene."""

    __tablename__ = "scene_posts"

    id = Column(Integer, primary_key=True, index=True)
    scene_id = Column(Integer, ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)
    reply_to_id = Column(Integer, ForeignKey("scene_posts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    scene = relationship("Scene", back_populates="posts")
    author = relationship("User", backref="scene_posts")
    character = relationship("Character", backref="scene_posts")
    reply_to = relationship("ScenePost", remote_side=[id], backref="replies")
