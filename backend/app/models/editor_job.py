"""Editor Studio async jobs (Sprint E5) — fire-and-poll for the self_hosted provider.

One row per self-hosted editor transform. Mirrors the Founder Async Lite pattern
(adult_founder_job.py): the backend never blocks on GPU work — a detached driver
process runs the RunPod transform, writes a run_id-scoped report file, and the
service reconciles this row from that file on poll. At most one job may be
active per character (enforced in the service layer).

ADDITIVE: no existing table changes. gpt-image/grok keep the sync /editor/generate
path; only self_hosted goes through jobs.
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

EDITOR_JOB_STATES = ("queued", "running", "completed", "failed")
EDITOR_JOB_ACTIVE_STATES = ("queued", "running")

# Quality gate verdicts (Sprint E5 Part B). "needs_review" still saves the image
# but the UI must not present it as a clean success.
EDITOR_QUALITY_STATUSES = ("pass", "needs_review", "failed")


class EditorJob(Base):
    """One async self-hosted editor transform job."""

    __tablename__ = "editor_jobs"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt = Column(Text, nullable=False)
    provider = Column(String(32), nullable=False, server_default="self_hosted")
    state = Column(String(16), nullable=False, server_default="queued", index=True)
    # Links this row to the run_id-scoped report the detached driver writes.
    run_id = Column(String, nullable=False, unique=True, index=True)
    pod_id = Column(String, nullable=True)
    # Launch inputs the driver needs (source_file_path, source_image_ids, strength).
    params_json = Column(JSON, nullable=True)
    quality_status = Column(String(16), nullable=True)
    final_image_url = Column(String, nullable=True)
    # Library row created by the driver on success.
    image_id = Column(Integer, nullable=True)
    # Driver report payload (stage images, spend, quality metrics, reasons).
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
