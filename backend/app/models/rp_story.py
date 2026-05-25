"""RP Story Thread models — threaded collaborative RP session storage."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON

from app.core.database import Base


class RPStoryThread(Base):
    """A collaborative RP story thread between the user's character and a writing partner."""

    __tablename__ = "rp_story_threads"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Soft reference — no FK so character deletion doesn't cascade to threads
    selected_character_id = Column(Integer, nullable=True)
    title = Column(String(200), nullable=False)
    partner_label = Column(String(100), nullable=True)
    partner_pov = Column(String(20), nullable=False, default="unknown")  # first | third | unknown
    status = Column(String(20), nullable=False, default="active")  # active | archived
    summary_memory = Column(Text, nullable=True)
    style_memory = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RPStoryTurn(Base):
    """A single turn in an RP Story Thread."""

    __tablename__ = "rp_story_turns"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("rp_story_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_index = Column(Integer, nullable=False)  # 1-based, monotonically increasing
    author_type = Column(String(20), nullable=False)  # partner | selected_character
    content = Column(Text, nullable=False)
    generated = Column(Boolean, nullable=False, default=False)
    godmod_detected = Column(Boolean, nullable=True)
    godmod_severity = Column(String(10), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("thread_id", "turn_index", name="uq_rp_story_turn"),
    )
