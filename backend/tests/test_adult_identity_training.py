"""Sprint 4 tests — training lifecycle + orchestration state machine.

No GPU, no external APIs, no providers, no RunPod. Pure state-machine + DB orchestration.
Identity models are created directly in the 'prepared' state (Sprint 3 already covers
how a model reaches 'prepared').
"""
import pytest

from app.models.adult_identity import AdultIdentityModel, AdultIdentityModelVersion
from app.services import adult_identity_training as T

FP = "a" * 64


def _prepared_model(db, character_id=7001):
    m = AdultIdentityModel(character_id=character_id, status="prepared",
                           canon_fingerprint=FP, base_model="sdxl-base")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _to_ready(db, character_id=7001):
    """Drive a model through the full happy path to 'ready'."""
    m = _prepared_model(db, character_id)
    job = T.create_training_job(m.id, db, provider="stub")
    T.start_training_job(job.id, db)
    T.complete_training_job(job.id, db, lora_weights_uri="r2://lora.safetensors")
    db.refresh(m)
    return m, job


# ── job creation ──────────────────────────────────────────────────────────────

def test_create_training_job(db_session):
    db = db_session
    m = _prepared_model(db)
    job = T.create_training_job(m.id, db, provider="stub")
    assert job.id is not None and job.state == "queued"
    assert job.identity_id == m.id and job.provider == "stub"
    # creating a job does not move the identity yet
    db.refresh(m)
    assert m.status == "prepared"


def test_create_job_requires_prepared(db_session):
    db = db_session
    m = _prepared_model(db, character_id=7010)
    m.status = "ready"
    db.commit()
    with pytest.raises(T.InvalidTransitionError):
        T.create_training_job(m.id, db)


# ── valid transitions (happy path) ─────────────────────────────────────────────

def test_valid_full_lifecycle(db_session):
    db = db_session
    m = _prepared_model(db)
    job = T.create_training_job(m.id, db)
    assert job.state == "queued"

    T.start_training_job(job.id, db)
    db.refresh(job); db.refresh(m)
    assert job.state == "running" and job.started_at is not None
    assert m.status == "training"

    T.complete_training_job(job.id, db, lora_weights_uri="r2://lora.safetensors")
    db.refresh(job); db.refresh(m)
    assert job.state == "completed" and job.finished_at is not None
    assert m.status == "ready"


# ── version creation on completion ─────────────────────────────────────────────

def test_completion_creates_active_version(db_session):
    db = db_session
    m, job = _to_ready(db)
    versions = db.query(AdultIdentityModelVersion).filter_by(identity_id=m.id).all()
    assert len(versions) == 1
    v = versions[0]
    assert v.version_index == 1 and v.state == "active"
    assert v.canon_fingerprint == FP                     # trained-against fingerprint
    assert v.lora_weights_uri == "r2://lora.safetensors"
    assert m.active_version_id == v.id
    assert job.version_id == v.id


def test_second_training_supersedes_prior_version(db_session):
    db = db_session
    m, _ = _to_ready(db, character_id=7002)
    # retrain cycle: ready -> stale -> prepared -> train -> ready
    T.mark_identity_stale(m.id, db)
    T.recover_stale_identity(m.id, db)
    job2 = T.create_training_job(m.id, db)
    T.start_training_job(job2.id, db)
    T.complete_training_job(job2.id, db, lora_weights_uri="r2://lora2.safetensors")

    versions = db.query(AdultIdentityModelVersion).filter_by(identity_id=m.id).order_by(
        AdultIdentityModelVersion.version_index).all()
    assert [v.version_index for v in versions] == [1, 2]
    assert versions[0].state == "superseded" and versions[1].state == "active"
    db.refresh(m)
    assert m.active_version_id == versions[1].id and m.status == "ready"


# ── failure path ───────────────────────────────────────────────────────────────

def test_failure_path(db_session):
    db = db_session
    m = _prepared_model(db, character_id=7003)
    job = T.create_training_job(m.id, db)
    T.start_training_job(job.id, db)
    T.fail_training_job(job.id, "provider refused", db)
    db.refresh(job); db.refresh(m)
    assert job.state == "failed" and job.error == "provider refused"
    assert m.status == "failed" and m.last_error == "provider refused"


# ── stale model recovery ───────────────────────────────────────────────────────

def test_stale_model_recovery(db_session):
    db = db_session
    m, _ = _to_ready(db, character_id=7004)
    assert m.status == "ready"
    T.mark_identity_stale(m.id, db)
    db.refresh(m)
    assert m.status == "stale"
    T.recover_stale_identity(m.id, db)
    db.refresh(m)
    assert m.status == "prepared"


# ── invalid transitions rejected ───────────────────────────────────────────────

def test_cannot_complete_unstarted_job(db_session):
    db = db_session
    m = _prepared_model(db, character_id=7005)
    job = T.create_training_job(m.id, db)  # queued, never started
    with pytest.raises(T.InvalidTransitionError):
        T.complete_training_job(job.id, db)


def test_cannot_start_when_identity_not_prepared(db_session):
    db = db_session
    m = _prepared_model(db, character_id=7006)
    job = T.create_training_job(m.id, db)        # queued, while prepared
    m.status = "ready"                            # identity drifts out of 'prepared'
    db.commit()
    with pytest.raises(T.InvalidTransitionError):
        # job queued->running is legal, but identity ready->training is not
        T.start_training_job(job.id, db)


def test_cannot_restart_running_job(db_session):
    db = db_session
    m = _prepared_model(db, character_id=7008)
    job = T.create_training_job(m.id, db)
    T.start_training_job(job.id, db)             # running
    with pytest.raises(T.InvalidTransitionError):
        T.start_training_job(job.id, db)         # running -> running is illegal


def test_cannot_mark_prepared_model_stale(db_session):
    db = db_session
    m = _prepared_model(db, character_id=7007)   # prepared, not ready
    with pytest.raises(T.InvalidTransitionError):
        T.mark_identity_stale(m.id, db)


def test_can_transition_helpers(db_session):
    assert T.can_transition_identity("prepared", "training") is True
    assert T.can_transition_identity("ready", "training") is False
    assert T.can_transition_identity("stale", "prepared") is True
    assert T.can_transition_job("queued", "running") is True
    assert T.can_transition_job("queued", "completed") is False
    assert T.can_transition_job("running", "failed") is True
