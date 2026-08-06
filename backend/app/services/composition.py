"""Composition session service — open, heartbeat, claim, commit.

Shared editor infrastructure. Provenance is this sprint's consumer; autosave,
revision history, collaboration and writing analytics are expected to reuse the
same session rows (see ``app.models.composition``).
"""
from datetime import datetime, timedelta
from typing import Any, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.composition import CompositionSession, SessionStatus

#: A session older than this cannot be redeemed. Long enough for a real writing
#: sitting including interruptions; short enough that a leaked id is not a
#: durable forgery tool.
MAX_SESSION_AGE = timedelta(hours=24)

#: Surfaces the client may open a session on. Closed set so a typo becomes a
#: 422 rather than an un-analysable row; extend freely as editors are added.
KNOWN_SURFACES = frozenset(
    {
        "commons_composer",
        "realm_composer",
        "workspace",
        "story_space",
        "comment",
        "scene",
    }
)

#: Counters the client may report. Anything else is dropped rather than stored,
#: so an updated client cannot quietly start sending new categories of data.
#: Every one is an integer count — no text, ever.
ALLOWED_METRICS = frozenset(
    {
        "typed_chars",
        "inserted_chars",
        "internal_insert_chars",
        "largest_insertion",
        "insertion_count",
        "edit_duration_ms",
    }
)


def open_session(
    db: Session,
    *,
    user_id: int,
    surface: str,
    target_kind: Optional[str] = None,
    target_ref: Optional[str] = None,
    parent_session_id: Optional[str] = None,
) -> CompositionSession:
    """Create an open session for ``user_id``.

    ``parent_session_id`` is honoured only when it names a session belonging to
    the same user; a foreign or unknown parent is silently dropped rather than
    rejected, since it can only ever *reduce* what the child is credited with.
    """
    parent: Optional[CompositionSession] = None
    if parent_session_id:
        parent = (
            db.query(CompositionSession)
            .filter(
                CompositionSession.id == parent_session_id,
                CompositionSession.user_id == user_id,
            )
            .first()
        )

    now = datetime.utcnow()
    session = CompositionSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        surface=surface,
        target_kind=target_kind,
        target_ref=target_ref,
        parent_session_id=parent.id if parent else None,
        status=SessionStatus.OPEN,
        metrics_json={},
        state_json={},
        created_at=now,
        updated_at=now,
        last_active_at=now,
    )
    db.add(session)
    db.flush()
    return session


def sanitise_metrics(raw: dict[str, Any] | None) -> dict[str, int]:
    """Keep only known integer counters, clamped non-negative.

    Defensive rather than trusting: these values are client-reported and are
    treated throughout as a claim to be corroborated, never as fact.
    """
    if not raw:
        return {}
    clean: dict[str, int] = {}
    for key, value in raw.items():
        if key not in ALLOWED_METRICS:
            continue
        try:
            clean[key] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    return clean


def update_metrics(
    db: Session, session: CompositionSession, metrics: dict[str, Any] | None
) -> CompositionSession:
    """Merge reported counters into the session and mark it active."""
    merged = dict(session.metrics_json or {})
    merged.update(sanitise_metrics(metrics))
    session.metrics_json = merged
    session.last_active_at = datetime.utcnow()
    db.flush()
    return session


def get_owned_session(
    db: Session, *, user_id: int, session_id: str
) -> Optional[CompositionSession]:
    """Fetch a session belonging to ``user_id``, or ``None``."""
    if not session_id:
        return None
    return (
        db.query(CompositionSession)
        .filter(
            CompositionSession.id == session_id,
            CompositionSession.user_id == user_id,
        )
        .first()
    )


def claim_session(
    db: Session, *, user_id: int, session_id: str
) -> Optional[CompositionSession]:
    """Redeem a session, marking it committed. Returns ``None`` if unusable.

    Single-use: the status flip happens inside the caller's transaction,
    alongside the content ``INSERT``, so a replayed id cannot produce a second
    piece of evidenced content, and a rolled-back post does not burn its session.
    """
    session = get_owned_session(db, user_id=user_id, session_id=session_id)
    if session is None:
        return None
    if session.status != SessionStatus.OPEN:
        return None
    if datetime.utcnow() - session.created_at > MAX_SESSION_AGE:
        return None

    session.status = SessionStatus.COMMITTED
    session.committed_at = datetime.utcnow()
    db.flush()
    return session


def link_commit(
    db: Session, session: Optional[CompositionSession], *, kind: str, obj_id: int
) -> None:
    """Record which row a claimed session produced.

    Feeds revision history and writing analytics later; today it makes an
    orphaned session distinguishable from one that really shipped something.
    """
    if session is None:
        return
    session.committed_kind = kind
    session.committed_id = obj_id
    db.flush()


def credited_internal_chars(
    db: Session, session: CompositionSession, claimed: int
) -> int:
    """How much of a claimed internal transfer the parent session supports.

    WriteSpace copy → Commons paste is genuine Ficshon writing arriving via the
    clipboard. The client may claim those characters as internal, but the claim
    is only honoured up to what the *parent* session was independently observed
    to have typed. No content moves between the two sessions — only this bound.
    """
    if claimed <= 0 or not session.parent_session_id:
        return 0
    parent = (
        db.query(CompositionSession)
        .filter(
            CompositionSession.id == session.parent_session_id,
            CompositionSession.user_id == session.user_id,
        )
        .first()
    )
    if parent is None:
        return 0
    parent_typed = int((parent.metrics_json or {}).get("typed_chars", 0) or 0)
    return min(claimed, parent_typed)
