"""Adult Studio Phase 1 persistence — production identity-model layer.

SEPARATE from Canon Studio. These tables do NOT modify or replace any canon table
(CharacterIdentityCanon, PermanentBodyMark, CharacterImage). Adult Studio READS canon
as source of truth and stores its own model artifacts, training jobs, and per-mark
render plan here.

Four tables (see docs/ADULT_STUDIO_PHASE1_DESIGN.md §4):
  AdultIdentityModel          — one row per character; the authoritative record.
  AdultIdentityModelVersion   — append-only LoRA artifact history.
  AdultIdentityTrainingJob    — training-run tracking (provider job + cost).
  AdultIdentityMarkRender     — per-mark routing plan + cached control assets.

Sprint 1 scope is persistence only: no training, no generation, no route rewiring.
The legacy adult_studio_identities table + its routes are intentionally left intact;
data cutover happens in a later sprint.
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base

# ── Allowed value sets (stored as String, mirrors the as01 pattern) ──────────
# Lifecycle of an identity model (docs §5.1).
ADULT_IDENTITY_STATUSES = (
    "not_trained", "prepared", "training", "ready", "stale", "failed",
)
# State of a single trained version.
ADULT_VERSION_STATES = ("active", "superseded", "failed")
# State of a training job.
ADULT_TRAINING_JOB_STATES = ("queued", "running", "succeeded", "failed", "canceled")
# Render mechanism chosen for a mark (docs §6.1; Sprint 2 routing vocabulary).
ADULT_MARK_ROUTES = (
    "ip_adapter",        # texture/sleeve/pattern marks (IP-Adapter reference)
    "controlnet_canny",  # figural/specific-shape marks (Canny of the crop)
    "inpaint_direct",    # skin marks (scar/birthmark/mole) — plain masked inpaint
    "hybrid",            # reserved: structure + style (not emitted yet)
    "skip",              # region not renderable / no usable reference
)


class AdultIdentityModel(Base):
    """One Adult Studio identity model per character — authoritative record."""

    __tablename__ = "adult_identity_models"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status = Column(String(20), nullable=False, server_default="not_trained")
    trigger_token = Column(String, nullable=True)
    base_model = Column(String, nullable=True)
    # App-enforced pointer to the servable version (no DB FK to avoid a
    # models<->versions cycle; portable across sqlite/postgres). See docs §4.1.
    active_version_id = Column(Integer, nullable=True, index=True)
    canon_fingerprint = Column(String(64), nullable=True)
    prepared_manifest_json = Column(JSON, nullable=True)
    provider = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow,
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        server_default=func.now(), nullable=False)

    character = relationship("Character")
    # ORM-level cascade (works on sqlite tests); Postgres also has DB-level
    # ON DELETE CASCADE on the child FKs as a backstop.
    versions = relationship(
        "AdultIdentityModelVersion", back_populates="identity",
        cascade="all, delete-orphan",
        foreign_keys="AdultIdentityModelVersion.identity_id",
    )
    training_jobs = relationship(
        "AdultIdentityTrainingJob", back_populates="identity",
        cascade="all, delete-orphan",
    )
    mark_renders = relationship(
        "AdultIdentityMarkRender", back_populates="identity",
        cascade="all, delete-orphan",
    )


class AdultIdentityModelVersion(Base):
    """A single trained LoRA artifact — append-only per identity."""

    __tablename__ = "adult_identity_model_versions"
    __table_args__ = (
        UniqueConstraint("identity_id", "version_index",
                         name="uq_adult_version_identity_index"),
    )

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(
        Integer,
        ForeignKey("adult_identity_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_index = Column(Integer, nullable=False)
    lora_weights_uri = Column(String, nullable=True)
    base_model = Column(String, nullable=True)
    training_config_json = Column(JSON, nullable=True)
    source_manifest_json = Column(JSON, nullable=True)
    canon_fingerprint = Column(String(64), nullable=True)
    metrics_json = Column(JSON, nullable=True)
    state = Column(String(20), nullable=False, server_default="active")
    created_at = Column(DateTime, default=datetime.utcnow,
                        server_default=func.now(), nullable=False)

    identity = relationship(
        "AdultIdentityModel", back_populates="versions",
        foreign_keys=[identity_id],
    )


class AdultIdentityTrainingJob(Base):
    """Tracking row for one training run (provider job + cost + logs)."""

    __tablename__ = "adult_identity_training_jobs"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(
        Integer,
        ForeignKey("adult_identity_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        Integer,
        ForeignKey("adult_identity_model_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider = Column(String, nullable=False)
    external_job_id = Column(String, nullable=True, index=True)
    state = Column(String(20), nullable=False, server_default="queued")
    cost_usd = Column(Float, nullable=True)
    logs_uri = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow,
                        server_default=func.now(), nullable=False)

    identity = relationship("AdultIdentityModel", back_populates="training_jobs")
    version = relationship("AdultIdentityModelVersion", foreign_keys=[version_id])


class AdultIdentityMarkRender(Base):
    """Per-mark routing plan + cached control assets (docs §6).

    Keyed to a canon PermanentBodyMark by its string id. mark_fingerprint lets us
    detect when the underlying canon mark changed (staleness).
    """

    __tablename__ = "adult_identity_mark_renders"
    __table_args__ = (
        UniqueConstraint("identity_id", "canon_mark_id",
                         name="uq_adult_mark_render_identity_mark"),
    )

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(
        Integer,
        ForeignKey("adult_identity_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canon_mark_id = Column(String, nullable=False)   # PermanentBodyMark.id, e.g. pbm_xxx
    mark_fingerprint = Column(String(64), nullable=True)
    mark_type = Column(String, nullable=True)
    body_region = Column(String, nullable=True)
    side = Column(String(16), nullable=True)
    route = Column(String(24), nullable=False, server_default="skip")
    reference_uri = Column(String, nullable=True)
    control_asset_uri = Column(String, nullable=True)
    params_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow,
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        server_default=func.now(), nullable=False)

    identity = relationship("AdultIdentityModel", back_populates="mark_renders")
