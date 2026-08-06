"""Composition sessions — shared editor infrastructure.

A composition session is the server's record that *an editing session happened*:
who was writing, on which surface, for how long, and what it eventually
produced. Provenance is the first consumer, not the purpose.

Reuse
-----
The session is deliberately not provenance-shaped. It carries identity
(``user_id``, ``surface``), lifecycle (``status``, timestamps), a commit
linkage (``committed_kind``/``committed_id``) and two open JSON slots:

* ``metrics_json`` — counters about the editing session. Provenance reads
  ``typed_chars``/``inserted_chars`` today; writing analytics and achievements
  want word counts, session durations and streaks from the same place.
* ``state_json`` — reserved, namespaced by feature. Autosaved draft bodies,
  revision-history pointers and collaborative presence all fit here without a
  migration. Nothing writes it yet.

Sessions are single-use *for commitment* — one session commits one content row,
which is what makes them unusable for replay — but long-lived before that, so a
draft can be edited, heartbeated and autosaved across a whole writing sitting.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.types import JSON

from app.core.database import Base


class SessionStatus:
    """Lifecycle states. Plain strings for the same reason as ``Provenance``."""

    OPEN = "open"
    COMMITTED = "committed"
    ABANDONED = "abandoned"


class CompositionSession(Base):
    """One editing session on one surface."""

    __tablename__ = "composition_sessions"

    #: Opaque UUID4. Client-visible, so never a guessable integer.
    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Where the writing happened: 'commons_composer', 'realm_composer',
    #: 'workspace', 'story_space', 'comment', 'scene'. Free-form so a new
    #: editor surface needs no migration.
    surface = Column(String(32), nullable=False)
    #: What the session is expected to produce ('post', 'comment', …) and the
    #: container it targets (realm id, channel id). Both advisory — used for
    #: analytics and for catching a session redeemed on the wrong surface.
    target_kind = Column(String(32), nullable=True)
    target_ref = Column(String(64), nullable=True)

    #: Set when this session continues another — WriteSpace copy → Commons
    #: composer paste. Carries no content, only the linkage that lets the server
    #: recognise an insertion as internal rather than foreign.
    parent_session_id = Column(
        String(36), ForeignKey("composition_sessions.id", ondelete="SET NULL"), nullable=True
    )

    status = Column(String(16), nullable=False, default=SessionStatus.OPEN)
    metrics_json = Column(JSON, nullable=False, default=dict)
    #: Reserved for autosave / revisions / collaboration. Unused in this sprint.
    state_json = Column(JSON, nullable=False, default=dict)

    committed_kind = Column(String(32), nullable=True)
    committed_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_active_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    committed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_composition_session_user_status", "user_id", "status"),
        # Supports the age-based sweep of abandoned sessions.
        Index("ix_composition_session_created", "created_at"),
    )
