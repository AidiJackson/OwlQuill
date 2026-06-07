"""Sprint 1 persistence-layer tests — Adult Studio Phase 1.

Pure persistence: no training, no generation, no RunPod, no routing logic. Validates
that the four adult_identity_* tables create, persist, relate, enforce their unique
constraints, and cascade-delete from the parent model.

FK to characters is not enforced under the sqlite test engine (no PRAGMA), so arbitrary
character_ids are used — these tests target the adult_* tables, not the characters FK.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.adult_identity import (
    ADULT_IDENTITY_STATUSES,
    ADULT_MARK_ROUTES,
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
    AdultIdentityTrainingJob,
)


def _model(db, character_id=9001, **kw):
    m = AdultIdentityModel(character_id=character_id, status="prepared",
                           trigger_token="fictest", base_model="sdxl-base", **kw)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def test_create_and_relationships(db_session):
    db = db_session
    m = _model(db)

    v = AdultIdentityModelVersion(
        identity_id=m.id, version_index=1, lora_weights_uri="r2://adult/9001/v1/lora.safetensors",
        base_model="sdxl-base", state="active", canon_fingerprint="a" * 64,
        training_config_json={"steps": 700, "rank": 32})
    j = AdultIdentityTrainingJob(
        identity_id=m.id, provider="replicate", external_job_id="job_abc", state="succeeded",
        cost_usd=0.34)
    r = AdultIdentityMarkRender(
        identity_id=m.id, canon_mark_id="pbm_8cff990d", mark_type="tattoo",
        body_region="right_upper_arm", side="right", route="ip_adapter",
        reference_uri="r2://crop.png", params_json={"ip_adapter_scale": 0.7})
    db.add_all([v, j, r])
    db.commit()

    db.refresh(m)
    assert len(m.versions) == 1 and m.versions[0].version_index == 1
    assert len(m.training_jobs) == 1 and m.training_jobs[0].external_job_id == "job_abc"
    assert len(m.mark_renders) == 1 and m.mark_renders[0].route == "ip_adapter"
    # back-references
    assert m.versions[0].identity.id == m.id
    assert m.mark_renders[0].body_region == "right_upper_arm"
    # app-enforced active version pointer
    m.active_version_id = v.id
    db.commit()
    assert db.get(AdultIdentityModel, m.id).active_version_id == v.id


def test_unique_one_model_per_character(db_session):
    db = db_session
    _model(db, character_id=4242)
    db.add(AdultIdentityModel(character_id=4242, status="not_trained"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_version_index_per_identity(db_session):
    db = db_session
    m = _model(db, character_id=4243)
    db.add(AdultIdentityModelVersion(identity_id=m.id, version_index=1))
    db.commit()
    db.add(AdultIdentityModelVersion(identity_id=m.id, version_index=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_mark_render_per_identity_mark(db_session):
    db = db_session
    m = _model(db, character_id=4244)
    db.add(AdultIdentityMarkRender(identity_id=m.id, canon_mark_id="pbm_x", route="skip"))
    db.commit()
    db.add(AdultIdentityMarkRender(identity_id=m.id, canon_mark_id="pbm_x", route="ip_adapter"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cascade_delete_children(db_session):
    db = db_session
    m = _model(db, character_id=4245)
    db.add_all([
        AdultIdentityModelVersion(identity_id=m.id, version_index=1),
        AdultIdentityTrainingJob(identity_id=m.id, provider="replicate"),
        AdultIdentityMarkRender(identity_id=m.id, canon_mark_id="pbm_y", route="controlnet_canny"),
    ])
    db.commit()
    db.delete(m)
    db.commit()
    assert db.query(AdultIdentityModelVersion).filter_by(identity_id=m.id).count() == 0
    assert db.query(AdultIdentityTrainingJob).filter_by(identity_id=m.id).count() == 0
    assert db.query(AdultIdentityMarkRender).filter_by(identity_id=m.id).count() == 0


def test_defaults_and_value_sets(db_session):
    db = db_session
    m = AdultIdentityModel(character_id=4246)
    db.add(m)
    db.commit()
    db.refresh(m)
    assert m.status == "not_trained"          # server_default
    assert m.created_at is not None and m.updated_at is not None
    # documented value sets are coherent
    assert "ready" in ADULT_IDENTITY_STATUSES and "stale" in ADULT_IDENTITY_STATUSES
    assert set(ADULT_MARK_ROUTES) == {"ip_adapter", "controlnet_canny", "hybrid", "skip"}
