"""Sprint 6 — Adult Studio end-to-end orchestration validation.

Proves the WHOLE Phase 1 lifecycle through the FakeTrainingProvider, with no external
services, no real provider, no GPU, no image generation, no canon writes beyond the
test fixture's own canon edits.

Flow:  prepare -> submit(fake) -> poll-until-complete -> version -> ready
       + stale workflow (ready -> stale -> prepared -> new version)
       + failure workflow (training -> failed, no version)

Uses Summer (character_id 60) built via the shared setup_canon helper.
"""
from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
)
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services import canon_service as cs
from app.services.adult_identity_preparation import prepare_adult_identity
from app.services.adult_identity_provider import FakeTrainingProvider
from app.services.adult_identity_training import (
    AdultIdentityTrainingService,
    recover_stale_identity,
)
from tests.canon_test_utils import setup_canon

CID = 60
R2 = "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated"

SUMMER_MARKS = [
    {
        "label": "Butterfly floral sleeve", "type": "tattoo",
        "body_region": "Right upper arm", "side": "right",
        "description": "Right upper arm butterfly and floral sleeve tattoo",
        "reference_image_url": f"{R2}/49a155d1a8834e71885105519cfaab3e.png",
    },
    {
        "label": "Black-and-white ballerina tattoo", "type": "tattoo",
        "body_region": "Left forearm", "side": "left",
        "description": "Left forearm black-and-white ballerina tattoo",
        "reference_image_url": f"{R2}/efd8bd5522af4be2a8f155647b43b64c.png",
    },
]


def _model(db):
    return db.query(AdultIdentityModel).filter_by(character_id=CID).first()


def _routes_by_region(db, model_id):
    return {
        r.body_region: r.route
        for r in db.query(AdultIdentityMarkRender).filter_by(identity_id=model_id).all()
    }


def _versions(db, model_id):
    return (
        db.query(AdultIdentityModelVersion)
        .filter_by(identity_id=model_id)
        .order_by(AdultIdentityModelVersion.version_index)
        .all()
    )


def _poll_until_terminal(svc, job_id, max_polls=5):
    job = None
    for _ in range(max_polls):
        job = svc.poll(job_id)
        if job.state in ("completed", "failed", "canceled"):
            break
    return job


def _edit_ballerina_description(db, new_desc):
    canon = db.query(CharacterIdentityCanon).filter_by(character_id=CID).first()
    body = cs.load_body_canon(canon)
    body.permanent_body_marks[1].description = new_desc
    cs._save_body(canon, body)
    db.commit()


# ── 1. Happy path: prepare -> train(fake) -> version -> ready ──────────────────

def test_e2e_happy_path(db_session):
    db = db_session
    setup_canon(db, CID, marks=SUMMER_MARKS, lock=True, with_images=True)

    # prepare
    res = prepare_adult_identity(CID, db)
    assert res.model_status == "prepared"
    assert res.mark_count == 2
    assert len(res.fingerprint) == 64

    model = _model(db)
    assert model.canon_fingerprint == res.fingerprint          # fingerprint stored
    routes = _routes_by_region(db, model.id)                   # mark renders stored
    assert routes["Right upper arm"] == "ip_adapter"           # butterfly route
    assert routes["Left forearm"] == "controlnet_canny"        # ballerina route

    # train through the fake provider
    fake = FakeTrainingProvider(artifact_uri="r2://e2e/lora.safetensors", cost_estimate=0.40)
    svc = AdultIdentityTrainingService(db, provider=fake)

    job = svc.submit(model.id)                                 # create + submit + start
    db.refresh(model)
    assert job.state == "running" and model.status == "training"
    assert job.external_job_id == "fake-job-1"

    job = _poll_until_terminal(svc, job.id)                    # poll until complete
    assert job.state == "completed"                            # training job completed

    db.refresh(model)
    versions = _versions(db, model.id)
    assert len(versions) == 1 and versions[0].state == "active"   # version created
    assert versions[0].lora_weights_uri == "r2://e2e/lora.safetensors"
    assert versions[0].canon_fingerprint == res.fingerprint
    assert model.active_version_id == versions[0].id           # active_version_id populated
    assert model.status == "ready"                             # identity ready
    assert job.cost_usd == 0.40


# ── 2. Stale workflow: ready -> stale -> prepared -> new version ───────────────

def test_e2e_stale_then_retrain(db_session):
    db = db_session
    setup_canon(db, CID, marks=SUMMER_MARKS, lock=True, with_images=True)

    res1 = prepare_adult_identity(CID, db)
    model = _model(db)
    fake = FakeTrainingProvider(artifact_uri="r2://e2e/lora-v1.safetensors")
    svc = AdultIdentityTrainingService(db, provider=fake)
    job1 = svc.submit(model.id)
    _poll_until_terminal(svc, job1.id)
    db.refresh(model)
    assert model.status == "ready"
    v1 = _versions(db, model.id)[0]

    # canon metadata changes -> re-prepare flags stale
    _edit_ballerina_description(db, "Left forearm colour ballerina tattoo")
    res2 = prepare_adult_identity(CID, db)
    assert res2.fingerprint != res1.fingerprint
    db.refresh(model)
    assert res2.model_status == "stale" and model.status == "stale"

    # recover stale -> prepared, then retrain -> new active version
    recover_stale_identity(model.id, db)
    db.refresh(model)
    assert model.status == "prepared"

    fake2 = FakeTrainingProvider(artifact_uri="r2://e2e/lora-v2.safetensors")
    svc2 = AdultIdentityTrainingService(db, provider=fake2)
    job2 = svc2.submit(model.id)
    _poll_until_terminal(svc2, job2.id)

    db.refresh(model)
    versions = _versions(db, model.id)
    assert [v.version_index for v in versions] == [1, 2]
    assert versions[0].state == "superseded" and versions[1].state == "active"
    assert versions[1].lora_weights_uri == "r2://e2e/lora-v2.safetensors"
    assert versions[1].canon_fingerprint == res2.fingerprint     # trained against new canon
    assert model.active_version_id == versions[1].id
    assert model.status == "ready"
    # mark renders stayed in sync (no duplication across the cycle)
    assert db.query(AdultIdentityMarkRender).filter_by(identity_id=model.id).count() == 2
    assert v1.id != versions[1].id


# ── 3. Failure workflow: training -> failed, no version ───────────────────────

def test_e2e_failure_no_version(db_session):
    db = db_session
    setup_canon(db, CID, marks=SUMMER_MARKS, lock=True, with_images=True)
    prepare_adult_identity(CID, db)
    model = _model(db)

    fake = FakeTrainingProvider(fail=True, fail_reason="provider declined")
    svc = AdultIdentityTrainingService(db, provider=fake)

    job = svc.submit(model.id)
    db.refresh(model)
    assert model.status == "training"

    job = _poll_until_terminal(svc, job.id)
    db.refresh(model)
    assert job.state == "failed" and job.error == "provider declined"
    assert model.status == "failed" and model.last_error == "provider declined"
    assert db.query(AdultIdentityModelVersion).filter_by(identity_id=model.id).count() == 0
    assert model.active_version_id is None
