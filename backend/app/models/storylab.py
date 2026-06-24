"""StoryLab DB models: story_state + generation_log + story_chapter + story + generation_telemetry."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


class Story(Base):
    """A StoryLab story — the top-level object giving a workspace its identity."""

    __tablename__ = "stories"

    id = Column(String, primary_key=True, index=True)  # UUID string
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(200), nullable=False)
    genre = Column(String(50), nullable=True)
    premise = Column(Text, nullable=True)
    # Soft references — no hard FK so realm/character deletion doesn't cascade
    realm_id = Column(Integer, nullable=True)
    character_ids = Column(JSON, nullable=False, default=list)
    cover_color = Column(String(20), nullable=False, default="#1a1a2e")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class StoryChapter(Base):
    """A generated chapter for a story workspace."""

    __tablename__ = "story_chapter"

    id = Column(Integer, primary_key=True, index=True)
    story_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=True, default="")
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


class GenerationTelemetry(Base):
    """Per-request token + cost telemetry for StoryLab generation paths (S24AZ).

    One row per (request, kind). Sub-calls of the same kind within a request
    (e.g. a chapter's up-to-3 retries) are aggregated into a single row, with
    ``calls`` recording how many OpenRouter calls were summed.

    Token counts are read from the OpenRouter ``usage`` object (actual). ``cost_usd``
    is derived from those actual counts using approximate per-token list rates and
    is NULL when the model's rate is unknown (e.g. stub provider). Used both for
    cost visibility and for the continuation / RP-reply daily quota counters.
    """

    __tablename__ = "generation_telemetry"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    story_id = Column(String, index=True, nullable=True)
    request_id = Column(String, index=True, nullable=True)
    kind = Column(String, index=True, nullable=False)  # continuation|chapter|summary|rp_reply|canon_extract
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    calls = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
