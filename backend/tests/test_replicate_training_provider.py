"""Phase 3 Sprint 1 tests — ReplicateTrainingProvider (mocked, NO live API).

The provider's HTTP layer is a fake ``session`` that records every request and returns
canned Replicate-shaped responses. There are NO live network calls, NO GPU, NO spend, NO
generation, and NO inference — only the training lifecycle (create / poll / cancel) is
exercised. ``load_image_bytes`` is patched so the canon-read-only ZIP packaging runs
offline.
"""
from unittest.mock import patch

import pytest

from app.models.adult_identity import AdultIdentityModel, AdultIdentityModelVersion
from app.services.adult_identity_provider import (
    FakeTrainingProvider,
    ProviderStatus,
    TrainingProvider,
    get_training_provider,
)
from app.services.adult_identity_training import AdultIdentityTrainingService
from app.services.providers.replicate_training_provider import (
    API_BASE,
    ReplicateTrainingError,
    ReplicateTrainingProvider,
)

_DUMMY_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 1024
FP = "c" * 64

MANIFEST = {
    "character_name": "Test Subject",
    "subject": "adult woman",
    "refs": [
        {"role": "face_front", "url": "https://canon.example/face_front.png"},
        {"role": "body_front", "url": "https://canon.example/body_front.png"},
    ],
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeSession:
    """Routes requests.Session.request() to canned responses; records every call."""

    def __init__(self, *, destination_exists=False, training=None):
        self.calls = []
        self._destination_exists = destination_exists
        self._training = training or {"id": "tr_abc123", "status": "starting"}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/files"):
            return _FakeResponse(200, {"urls": {"get": "https://replicate.example/zip"}})
        if method == "GET" and "/models/" in url and "/versions/" not in url:
            return _FakeResponse(200 if self._destination_exists else 404, {}, "not found")
        if method == "POST" and url.endswith("/models"):
            return _FakeResponse(201, {"url": url})
        if method == "POST" and url.endswith("/trainings"):
            return _FakeResponse(201, self._training)
        if method == "GET" and "/trainings/" in url:
            return _FakeResponse(200, self._training)
        if method == "POST" and url.endswith("/cancel"):
            return _FakeResponse(200, {"id": "tr_abc123", "status": "canceled"})
        raise AssertionError(f"unexpected request {method} {url}")


def _provider(session):
    return ReplicateTrainingProvider(api_token="tok-test", owner="ficowner", session=session)


def _prepared(db, character_id=9001):
    m = AdultIdentityModel(character_id=character_id, status="prepared",
                           canon_fingerprint=FP, base_model="sdxl", trigger_token="fictest")
    m.prepared_manifest_json = MANIFEST
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


# ── protocol / construction ────────────────────────────────────────────────────

def test_provider_conforms_to_protocol():
    p = _provider(_FakeSession())
    assert isinstance(p, TrainingProvider)
    assert p.name == "replicate"


def test_provider_requires_token_and_owner():
    with pytest.raises(ValueError):
        ReplicateTrainingProvider(api_token="", owner="x", session=_FakeSession())
    with pytest.raises(ValueError):
        ReplicateTrainingProvider(api_token="t", owner="", session=_FakeSession())


# ── create_training_job ─────────────────────────────────────────────────────────

def test_create_training_job_issues_expected_calls():
    session = _FakeSession(destination_exists=False)
    p = _provider(session)
    with patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        job = p.create_training_job(
            identity_id=7, trigger_token="fictest", base_model="sdxl",
            training_config=None, source_manifest=MANIFEST,
        )
    assert job.provider_job_id == "tr_abc123"
    assert job.status == ProviderStatus.SUBMITTED  # "starting" → submitted

    methods_urls = [(m, u) for (m, u, _) in session.calls]
    # upload → check destination → create destination → start training, in order.
    assert methods_urls[0] == ("POST", f"{API_BASE}/files")
    assert methods_urls[1][0] == "GET" and "/models/ficowner/ficshon-adult-7" in methods_urls[1][1]
    assert methods_urls[2] == ("POST", f"{API_BASE}/models")
    assert methods_urls[3][0] == "POST" and methods_urls[3][1].endswith("/trainings")
    # every URL is the Replicate API — nothing else is contacted.
    assert all(u.startswith(API_BASE) for _, u in methods_urls)


def test_create_skips_destination_creation_when_it_exists():
    session = _FakeSession(destination_exists=True)
    p = _provider(session)
    with patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        p.create_training_job(identity_id=7, trigger_token="t", base_model="sdxl",
                              training_config=None, source_manifest=MANIFEST)
    assert not any(m == "POST" and u.endswith("/models") for m, u, _ in session.calls)


def test_create_sends_lora_training_input():
    session = _FakeSession()
    p = _provider(session)
    with patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        p.create_training_job(identity_id=7, trigger_token="fictest", base_model="sdxl",
                              training_config={"max_train_steps": 700}, source_manifest=MANIFEST)
    start = next(kw for m, u, kw in session.calls if u.endswith("/trainings"))
    body = start["json"]
    assert body["destination"] == "ficowner/ficshon-adult-7"
    assert body["input"]["is_lora"] is True
    assert body["input"]["token_string"] == "fictest"
    assert body["input"]["max_train_steps"] == 700           # override applied
    assert body["input"]["lora_rank"] == 32                  # default preserved
    assert body["input"]["input_images"] == "https://replicate.example/zip"


def test_create_rejects_empty_manifest():
    p = _provider(_FakeSession())
    with pytest.raises(ReplicateTrainingError):
        p.create_training_job(identity_id=7, trigger_token="t", base_model="sdxl",
                              training_config=None, source_manifest={"refs": []})


# ── poll_training_job ────────────────────────────────────────────────────────────

def test_poll_running():
    session = _FakeSession(training={"id": "tr_abc123", "status": "processing"})
    pj = _provider(session).poll_training_job("tr_abc123")
    assert pj.status == ProviderStatus.RUNNING
    assert pj.model_artifact_uri is None


def test_poll_succeeded_returns_artifact_and_cost():
    session = _FakeSession(training={
        "id": "tr_abc123", "status": "succeeded",
        "output": {"version": "ficowner/ficshon-adult-7:deadbeef", "weights": "https://w.example/lora.tar"},
        "metrics": {"predict_time": 600.0},
    })
    pj = _provider(session).poll_training_job("tr_abc123")
    assert pj.status == ProviderStatus.COMPLETED
    assert pj.model_artifact_uri == "https://w.example/lora.tar"
    assert pj.cost_estimate == round(600.0 * 0.001400, 4)


def test_poll_failed_returns_error():
    session = _FakeSession(training={"id": "tr_abc123", "status": "failed",
                                     "error": "content policy refusal"})
    pj = _provider(session).poll_training_job("tr_abc123")
    assert pj.status == ProviderStatus.FAILED
    assert pj.error == "content policy refusal"


# ── cancel_training_job ──────────────────────────────────────────────────────────

def test_cancel():
    session = _FakeSession()
    pj = _provider(session).cancel_training_job("tr_abc123")
    assert pj.status == ProviderStatus.CANCELED
    assert any(u.endswith("/trainings/tr_abc123/cancel") for _, u, _ in session.calls)


# ── error surfacing ──────────────────────────────────────────────────────────────

def test_non_2xx_raises():
    class _ErrSession(_FakeSession):
        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return _FakeResponse(500, {}, "boom")

    with pytest.raises(ReplicateTrainingError):
        _provider(_ErrSession()).poll_training_job("tr_abc123")


# ── end-to-end through the existing lifecycle ────────────────────────────────────

def test_full_lifecycle_through_training_service(db_session):
    db = db_session
    m = _prepared(db, character_id=9100)
    session = _FakeSession(training={
        "id": "tr_abc123", "status": "succeeded",
        "output": {"version": "ficowner/ficshon-adult-9100:hash", "weights": "https://w.example/l.tar"},
        "metrics": {"predict_time": 500.0},
    })
    provider = _provider(session)
    svc = AdultIdentityTrainingService(db, provider=provider)

    with patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        job = svc.submit(m.id, base_model="sdxl")
    db.refresh(m)
    assert job.provider == "replicate"
    assert job.external_job_id == "tr_abc123"   # provider_job_id persisted
    assert job.state == "running" and m.status == "training"

    job = svc.poll(job.id)
    db.refresh(m)
    assert job.state == "completed" and m.status == "ready"

    versions = db.query(AdultIdentityModelVersion).filter_by(identity_id=m.id).all()
    assert len(versions) == 1
    v = versions[0]
    assert v.lora_weights_uri == "https://w.example/l.tar"   # artifact URI stored
    assert v.base_model == "sdxl"
    assert v.canon_fingerprint == FP
    assert job.cost_usd == round(500.0 * 0.001400, 4)        # cost estimate stored
    assert job.version_id == v.id


# ── gated factory (disabled by default) ──────────────────────────────────────────

class _Settings:
    def __init__(self, **kw):
        self.ADULT_STUDIO_TRAINING_ENABLED = kw.get("enabled", False)
        self.ADULT_STUDIO_PROVIDER = kw.get("provider", "disabled")
        self.REPLICATE_API_TOKEN = kw.get("token", "")
        self.ADULT_STUDIO_REPLICATE_OWNER = kw.get("owner", "")


def test_factory_disabled_by_default():
    # training off → never constructs a provider, even if a real one is selected.
    assert get_training_provider(_Settings(enabled=False, provider="replicate",
                                           token="t", owner="o")) is None
    # training on but provider disabled → still None.
    assert get_training_provider(_Settings(enabled=True, provider="disabled")) is None


def test_factory_builds_replicate_only_when_fully_enabled():
    p = get_training_provider(_Settings(enabled=True, provider="replicate",
                                        token="tok", owner="ficowner"))
    assert isinstance(p, ReplicateTrainingProvider)
    assert p.name == "replicate"


def test_factory_fake_provider():
    p = get_training_provider(_Settings(enabled=True, provider="fake"))
    assert isinstance(p, FakeTrainingProvider)


def test_factory_replicate_requires_credentials():
    with pytest.raises(ValueError):
        get_training_provider(_Settings(enabled=True, provider="replicate", token="", owner=""))


def test_factory_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_training_provider(_Settings(enabled=True, provider="modal"))
