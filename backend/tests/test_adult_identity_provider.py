"""Sprint 5 tests — training-provider abstraction (fake provider only).

No RunPod, no Replicate, no GPU, no spend, no real network. The FakeTrainingProvider is
the only seam exercised; every provider interaction is recorded in `provider.calls`,
proving no real external call is made.
"""
from app.models.adult_identity import AdultIdentityModel, AdultIdentityModelVersion
from app.services.adult_identity_provider import (
    FakeTrainingProvider,
    ProviderJob,
    ProviderStatus,
    TrainingProvider,
)
from app.services.adult_identity_training import AdultIdentityTrainingService

FP = "b" * 64


def _prepared(db, character_id=8001):
    m = AdultIdentityModel(character_id=character_id, status="prepared",
                           canon_fingerprint=FP, base_model="sdxl-base",
                           trigger_token="ficfake")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def test_fake_provider_conforms_to_protocol():
    fake = FakeTrainingProvider()
    assert isinstance(fake, TrainingProvider)
    assert fake.name == "fake"


def test_fake_provider_submits_job(db_session):
    db = db_session
    m = _prepared(db)
    fake = FakeTrainingProvider()
    svc = AdultIdentityTrainingService(db, provider=fake)

    job = svc.submit(m.id)
    db.refresh(m)
    assert job.state == "running"               # local job started
    assert m.status == "training"               # identity advanced
    assert job.external_job_id == "fake-job-1"  # provider id recorded
    assert job.provider == "fake"
    assert job.cost_usd == 0.34
    assert fake.calls == [("create", "fake-job-1")]


def test_fake_provider_completes_job(db_session):
    db = db_session
    m = _prepared(db, character_id=8002)
    fake = FakeTrainingProvider()
    svc = AdultIdentityTrainingService(db, provider=fake)

    job = svc.submit(m.id)
    job = svc.poll(job.id)
    db.refresh(m)
    assert job.state == "completed"
    assert m.status == "ready"
    assert fake.calls == [("create", "fake-job-1"), ("poll", "fake-job-1")]


def test_provider_artifact_creates_version(db_session):
    db = db_session
    m = _prepared(db, character_id=8003)
    fake = FakeTrainingProvider(artifact_uri="r2://fake/v1/lora.safetensors", cost_estimate=0.41)
    svc = AdultIdentityTrainingService(db, provider=fake)

    job = svc.submit(m.id)
    svc.poll(job.id)

    versions = db.query(AdultIdentityModelVersion).filter_by(identity_id=m.id).all()
    assert len(versions) == 1
    v = versions[0]
    assert v.state == "active" and v.version_index == 1
    assert v.lora_weights_uri == "r2://fake/v1/lora.safetensors"
    assert v.canon_fingerprint == FP
    db.refresh(m)
    assert m.active_version_id == v.id and m.status == "ready"
    db.refresh(job)
    assert job.cost_usd == 0.41 and job.version_id == v.id


def test_failed_provider_marks_training_failed(db_session):
    db = db_session
    m = _prepared(db, character_id=8004)
    fake = FakeTrainingProvider(fail=True, fail_reason="content policy refusal")
    svc = AdultIdentityTrainingService(db, provider=fake)

    job = svc.submit(m.id)
    job = svc.poll(job.id)
    db.refresh(m)
    assert job.state == "failed" and job.error == "content policy refusal"
    assert m.status == "failed" and m.last_error == "content policy refusal"
    # no version created on failure
    assert db.query(AdultIdentityModelVersion).filter_by(identity_id=m.id).count() == 0


def test_no_external_calls_made(db_session):
    db = db_session
    # (a) with a provider: every interaction is the recorded fake seam, ids are fake.
    m = _prepared(db, character_id=8005)
    fake = FakeTrainingProvider()
    svc = AdultIdentityTrainingService(db, provider=fake)
    job = svc.submit(m.id)
    svc.poll(job.id)
    assert all(call[0] in {"create", "poll", "cancel"} for call in fake.calls)
    assert all(str(arg).startswith("fake-job-") for _, arg in fake.calls)

    # (b) with NO provider: lifecycle runs locally, zero provider interaction.
    m2 = _prepared(db, character_id=8006)
    svc2 = AdultIdentityTrainingService(db, provider=None)
    job2 = svc2.submit(m2.id)
    db.refresh(m2)
    assert job2.state == "running" and m2.status == "training"
    assert job2.external_job_id is None        # no provider → no external id
    assert svc2.poll(job2.id).state == "running"  # poll is a no-op without a provider


def test_provider_cancel(db_session):
    db = db_session
    m = _prepared(db, character_id=8007)
    fake = FakeTrainingProvider()
    svc = AdultIdentityTrainingService(db, provider=fake)
    job = svc.submit(m.id)
    job = svc.cancel(job.id)
    assert job.state == "canceled"
    assert ("cancel", "fake-job-1") in fake.calls


def test_provider_job_result_shape():
    pj = ProviderJob(provider_job_id="x", status=ProviderStatus.COMPLETED,
                     model_artifact_uri="r2://a", cost_estimate=0.1)
    assert pj.error is None and pj.status == "completed"
    assert ProviderStatus.COMPLETED in ProviderStatus.TERMINAL
