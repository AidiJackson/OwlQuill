"""Image-generation async jobs — fire-and-poll for the founder image workflow.

One row per interactive generation intent. Mirrors the proven detached-driver
pattern already used by ``identity_pack_job.py`` / ``editor_job.py``: the
request thread never blocks on provider work, a detached driver runs the
pipeline and writes status/result to this row, and the client polls.

Why the interactive generator needs this
----------------------------------------
The published deployment target is Cloud Run (``.replit`` →
``deploymentTarget = "cloudrun"``), which enforces a request deadline. One
canon generation is a single Google call bounded by ``GOOGLE_IMAGE_TIMEOUT_S``
(180s), but the route may legitimately issue up to four: the first pass, up to
``IDENTITY_FACE_VERIFY_MAX_RETRIES`` (2) escalated face-verification retries,
and one cover-composition retry. The worst case is ~12 minutes of provider time
in a single HTTP request — comfortably past the deadline. Holding that request
open from a tablet on mobile data is exactly the case that fails, and it fails
AFTER the provider has been paid.

Idempotency
-----------
``idempotency_key`` is REQUIRED for this table (the route rejects a submission
without one) and is enforced by the unique index
``ux_image_generation_jobs_idem``. One user generation intent therefore maps to
at most one row, and at most one paid provider submission — a double-tap,
browser retry, proxy retry or reconnect resolves to the SAME job and re-attaches
to it rather than spending again. The uniqueness is scoped to ``user_id`` so two
accounts can never collide on a client-generated key.

``diag_json`` holds internal diagnostics (tracebacks, raw provider errors) and
is NEVER serialised into API responses — only ``error_code`` and the safe
``error_message`` are user-visible, exactly as for identity-pack jobs.
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

IMAGE_GENERATION_JOB_STATES = ("queued", "running", "completed", "failed")
IMAGE_GENERATION_JOB_ACTIVE_STATES = ("queued", "running")


class ImageGenerationJob(Base):
    """One async founder image-generation job."""

    __tablename__ = "image_generation_jobs"

    id = Column(Integer, primary_key=True, index=True)
    # Stable public identifier used in API URLs (never expose the row id).
    public_id = Column(String(32), nullable=False, unique=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Phase 4C: nullable with ``ON DELETE SET NULL``. This row is the record
    #: of WHO REQUESTED a generation, and 4B2 kept requester identity off the
    #: image on the grounds that it lives here. That only holds if this row
    #: outlives the image: under the previous ``CASCADE`` deleting a character
    #: destroyed the job at the same moment 4C starts preserving the image it
    #: produced. ``user_id`` above is untouched and remains the requester.
    character_id = Column(
        Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status = Column(String(16), nullable=False, server_default="queued", index=True)
    stage = Column(String(64), nullable=True)
    progress_message = Column(String(200), nullable=True)
    attempt_count = Column(Integer, nullable=False, server_default="0")
    # Client-supplied intent key. Required by the route; unique per user.
    idempotency_key = Column(String(64), nullable=False, index=True)
    # Sanitised launch inputs (prompt, provider option, reference ids + roles,
    # resolved entitlement flags). Never secrets, tokens or credentials.
    params_json = Column(JSON, nullable=True)
    # The CharacterImage produced on success. The image row is the result; this
    # column is the pointer, so a completed job never duplicates image state.
    image_id = Column(
        Integer, ForeignKey("character_images.id", ondelete="SET NULL"), nullable=True
    )
    # Safe, user-facing summary of what was actually sent to the provider
    # (reference counts, refs_source, anything dropped for budget). Mirrors the
    # image's metadata so the client can warn without reading raw metadata.
    result_json = Column(JSON, nullable=True)
    error_code = Column(String(48), nullable=True)
    # Safe, user-facing failure text. Raw provider errors go to diag_json.
    error_message = Column(String(400), nullable=True)
    diag_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    # Heartbeat: the runner touches this at every stage boundary; the stale-job
    # reconciler treats an old value on a "running" row as a dead driver.
    updated_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # THE paid-spend guarantee. One (user, intent key) → one row → one
        # submission. Unconditional (not partial): a completed or failed job
        # still occupies the key, so a retry after either outcome resolves to
        # the existing row instead of buying a second image.
        Index(
            "ux_image_generation_jobs_idem",
            "user_id",
            "idempotency_key",
            unique=True,
        ),
    )
