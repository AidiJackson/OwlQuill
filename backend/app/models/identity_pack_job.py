"""Identity Pack async jobs (Sprint 35) — fire-and-poll for the v2 canon pack.

One row per self-serve v2 canon-pack generation. Mirrors the proven detached
driver pattern (editor_job.py / adult_founder_job.py): the backend never blocks
on provider work — a detached driver process runs build_v2_pack and writes
status/stage/result directly to this row; the frontend polls.

Race safety lives at the DB level: the partial unique index
``ux_identity_pack_jobs_one_active`` allows at most ONE queued/running job per
character, so two concurrent submits cannot both insert an active row.

``diag_json`` holds internal diagnostics (tracebacks, raw provider errors) and
is NEVER serialised into API responses — only ``error_code`` and the safe
``error_message`` are user-visible.
"""
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
)

from app.core.database import Base

IDENTITY_PACK_JOB_STATES = ("queued", "running", "completed", "failed")
IDENTITY_PACK_JOB_ACTIVE_STATES = ("queued", "running")


class IdentityPackJob(Base):
    """One async v2 canon-pack generation job."""

    __tablename__ = "identity_pack_jobs"

    id = Column(Integer, primary_key=True, index=True)
    # Stable public identifier used in API URLs (never expose the row id).
    public_id = Column(String(32), nullable=False, unique=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id = Column(
        Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(String(16), nullable=False, server_default="queued", index=True)
    # Truthful pipeline stage key (e.g. "queued", "preparing", "card:face_front",
    # "mark_details", "finalising") + a human-readable progress line.
    stage = Column(String(64), nullable=True)
    progress_message = Column(String(200), nullable=True)
    progress_percent = Column(Integer, nullable=True)
    attempt_count = Column(Integer, nullable=False, server_default="0")
    # Client-supplied key: an identical resubmission returns the same job.
    idempotency_key = Column(String(64), nullable=True, index=True)
    # Sanitised launch inputs (provider_option, max_spend, admin flags).
    # Never secrets, tokens, or credentials.
    params_json = Column(JSON, nullable=True)
    # Completed pack report — the same payload the sync v2 endpoint returns.
    result_json = Column(JSON, nullable=True)
    error_code = Column(String(48), nullable=True)
    # Safe, user-facing failure text. Raw provider errors go to diag_json.
    error_message = Column(String(300), nullable=True)
    # Internal diagnostics — excluded from every API response.
    diag_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    # Heartbeat: the runner touches this on every stage boundary; the stale-job
    # reconciler treats an old value on a "running" row as a dead driver.
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # DB-level duplicate protection: at most one active job per character.
        Index(
            "ux_identity_pack_jobs_one_active",
            "character_id",
            unique=True,
            postgresql_where=(Column("status").in_(IDENTITY_PACK_JOB_ACTIVE_STATES)),
            sqlite_where=(Column("status").in_(IDENTITY_PACK_JOB_ACTIVE_STATES)),
        ),
    )
