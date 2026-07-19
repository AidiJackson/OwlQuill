"""Adult Studio FOUNDER ASYNC LITE — job persistence (Phase 3, Sprint 13).

A single tiny table backing the founder-only fire-and-poll Generate path. One row per
founder generation; at most one row may be active (queued/running) at a time — the
singleton is enforced in the service layer. The backend NEVER writes the GPU work here:
the detached RunPod driver writes a run_id-scoped report file, and the service reconciles
this row from that file on poll.

SEPARATE from Canon Studio and from the normal image generator. Does NOT modify any
existing table. Summer-only by construction (character_id is always 60).
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)

from app.core.database import Base

# Founder job lifecycle (the four states required by the sprint).
ADULT_FOUNDER_JOB_STATES = ("queued", "running", "completed", "failed")
# A founder job is "active" (blocks a new launch) in these states.
ADULT_FOUNDER_ACTIVE_STATES = ("queued", "running")


class AdultFounderJob(Base):
    """One founder async generation job. Singleton-active, Summer-only."""

    __tablename__ = "adult_founder_jobs"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt = Column(Text, nullable=False)
    state = Column(String(16), nullable=False, server_default="queued", index=True)
    # Links this row to the run_id-scoped report the detached driver writes.
    run_id = Column(String, nullable=False, unique=True, index=True)
    pod_id = Column(String, nullable=True)
    final_image_url = Column(String, nullable=True)
    # The founder-generate response payload (intermediate_artifact_urls, routes_executed,
    # cost, runtime, manual_review_required, orphaned_workers, blocking_reasons).
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
