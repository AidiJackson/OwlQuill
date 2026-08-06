"""Fingerprints of text Ficshon's own AI tools produced.

This is the link that was missing between StoryLab and the public badge. Every
generation registers hashes of its output here; every post checks its content
against them. A user who generates in StoryLab, copies, and pastes into the
Commons composer is recognised by the server as posting its own output —
without the client cooperating and without reading the clipboard.

Only hashes are stored. The generated text itself already lives in
``generation_log.response_text`` / ``story_chapter.generated_text``; this table
adds no new category of retained data, just an index into it.
"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String

from app.core.database import Base


class AIOutputFingerprint(Base):
    """One shingle hash of one AI generation, scoped to the user who ran it."""

    __tablename__ = "ai_output_fingerprints"

    id = Column(Integer, primary_key=True, index=True)
    #: Matching is author-scoped: a post is only ever compared against
    #: generations run by its own author. No cross-account text comparison.
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    shingle_hash = Column(BigInteger, nullable=False)
    #: 'storylab_continuation' | 'storylab_chapter' | 'rp_reply' — free-form so a
    #: new generator needs no migration.
    source_kind = Column(String(32), nullable=False)
    source_ref = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        # The only query shape used: "any of these hashes, for this author".
        Index("ix_ai_fingerprint_user_hash", "user_id", "shingle_hash"),
        # Supports retention pruning.
        Index("ix_ai_fingerprint_created", "created_at"),
    )
