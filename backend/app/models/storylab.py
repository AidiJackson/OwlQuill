"""StoryLab DB models: story_state + generation_log + story_chapter."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON

from app.core.database import Base


class StoryState(Base):
    """Persisted narrative state for a story workspace."""

    __tablename__ = "story_state"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(String, unique=True, index=True, nullable=False)
    story_summary = Column(Text, nullable=True)
    state_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class GenerationLog(Base):
    """Audit log of every stub-generation call."""

    __tablename__ = "generation_log"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(String, index=True, nullable=False)
    request_id = Column(String, index=True, nullable=False)
    controls_json = Column(JSON, nullable=False)
    prompt_snapshot = Column(Text, nullable=True)
    response_text = Column(Text, nullable=False)
    word_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class StoryChapter(Base):
    """A generated chapter for a story workspace."""

    __tablename__ = "story_chapter"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(String, index=True, nullable=False)
    # user_id tracks which user generated this chapter (used for daily quota).
    # Nullable for legacy chapters created before quota enforcement.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chapter_number = Column(Integer, nullable=False)
    title = Column(Text, nullable=True)
    prompt_text = Column(Text, nullable=True)
    mode = Column(String, nullable=False, default="roleplay")
    controls_json = Column(JSON, nullable=False, default=dict)
    generated_text = Column(Text, nullable=False)
    word_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("story_id", "chapter_number", name="uq_story_chapter"),
    )
