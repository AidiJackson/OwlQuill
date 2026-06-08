"""Phase 3 Sprint 2 — admin-triggered Adult Studio training workflow (gated).

POST /admin/adult-studio/characters/{id}/train
POST /admin/adult-studio/training-jobs/{job_id}/poll

The REAL workflow lives behind feature flags. With the defaults
(ADULT_STUDIO_TRAINING_ENABLED=false, ADULT_STUDIO_PROVIDER=disabled) the endpoints
return 409 BEFORE any provider is constructed — the disabled path cannot reach a provider
or spend money. All "enabled" tests use the in-memory FakeTrainingProvider (or a patched
factory) — NO live Replicate calls, no GPU, no generation, no inference.
"""
from fastapi.testclient import TestClient

from app.core import config as cfg_module
from app.models.adult_identity import AdultIdentityModel, AdultIdentityModelVersion
from app.services.adult_identity_preparation import prepare_adult_identity
from app.services.adult_identity_provider import FakeTrainingProvider
from tests.canon_test_utils import setup_canon

_ADMIN_EMAIL = "as-train-admin@ficshon.com"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str, username: str, password="pass12345") -> str:
    client.post("/auth/register", json={"email": email, "username": username, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")


def _admin_token(client) -> str:
    return _register_and_login(client, _ADMIN_EMAIL, "astrainadmin")


def _create_character(client, token, name="Summer") -> int:
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _train_url(cid: int) -> str:
    return f"/admin/adult-studio/characters/{cid}/train"


def _poll_url(job_id: int) -> str:
    return f"/admin/adult-studio/training-jobs/{job_id}/poll"


def _summer_marks() -> list[dict]:
    return [
        {
            "label": "Butterfly floral sleeve", "type": "tattoo",
            "body_region": "right_upper_arm", "side": "right",
            "description": "Right upper arm butterfly and floral sleeve tattoo",
            "reference_image_url": "static/generated/mark_right.png",
        },
        {
            "label": "Black-and-white ballerina tattoo", "type": "tattoo",
            "body_region": "left_forearm", "side": "left",
            "description": "Left forearm black-and-white ballerina tattoo",
            "reference_image_url": "static/generated/mark_left.png",
        },
    ]


def _ready_summer(client, db, monkeypatch):
    """A fully training-ready character (locked canon + prepared identity)."""
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    setup_canon(db, cid, marks=_summer_marks(), lock=True, with_images=True)
    prepare_adult_identity(cid, db)
    return token, cid


def _enable_training(monkeypatch, provider="fake"):
    monkeypatch.setattr(cfg_module.settings, "ADULT_STUDIO_TRAINING_ENABLED", True)
    monkeypatch.setattr(cfg_module.settings, "ADULT_STUDIO_PROVIDER", provider)


# ── Access control ─────────────────────────────────────────────────────────────


def test_train_requires_authentication(client):
    resp = client.post(_train_url(1))
    assert resp.status_code in (401, 403)


def test_train_non_admin_forbidden(client, db_session):
    token = _register_and_login(client, "plain-train@test.com", "plaintrain")
    cid = _create_character(client, token)
    resp = client.post(_train_url(cid), headers=_headers(token))
    assert resp.status_code == 403


def test_poll_non_admin_forbidden(client, db_session):
    token = _register_and_login(client, "plain-poll@test.com", "plainpoll")
    resp = client.post(_poll_url(1), headers=_headers(token))
    assert resp.status_code == 403


# ── Disabled-by-default gating (no provider, no spend) ──────────────────────────


def test_train_disabled_by_default_returns_409(client, db_session, monkeypatch):
    # A fully-ready character, but training disabled (default) → 409.
    token, cid = _ready_summer(client, db_session, monkeypatch)
    resp = client.post(_train_url(cid), headers=_headers(token))
    assert resp.status_code == 409
    assert "disabled" in resp.json()["detail"].lower()


def test_train_provider_disabled_returns_409(client, db_session, monkeypatch):
    # Training enabled but provider still "disabled" → 409, no provider constructed.
    token, cid = _ready_summer(client, db_session, monkeypatch)
    monkeypatch.setattr(cfg_module.settings, "ADULT_STUDIO_TRAINING_ENABLED", True)
    monkeypatch.setattr(cfg_module.settings, "ADULT_STUDIO_PROVIDER", "disabled")
    resp = client.post(_train_url(cid), headers=_headers(token))
    assert resp.status_code == 409
    assert "provider" in resp.json()["detail"].lower()


def test_train_provider_not_constructed_when_disabled(client, db_session, monkeypatch):
    """The disabled path must short-circuit BEFORE the provider factory is called."""
    token, cid = _ready_summer(client, db_session, monkeypatch)

    def _boom(*a, **k):  # pragma: no cover - must never run on the disabled path
        raise AssertionError("provider factory must not be called when disabled")

    monkeypatch.setattr("app.api.routes.adult_studio_admin.get_training_provider", _boom)
    # defaults: training disabled → 409 without ever constructing a provider.
    resp = client.post(_train_url(cid), headers=_headers(token))
    assert resp.status_code == 409


# ── Readiness gate ──────────────────────────────────────────────────────────────


def test_train_not_ready_rejected(client, db_session, monkeypatch):
    # Canon locked & prepared, then break readiness (unlock body) → 409, even with flags on.
    token, cid = _ready_summer(client, db_session, monkeypatch)
    _enable_training(monkeypatch)
    from app.models.character_identity_canon import CharacterIdentityCanon
    canon = (
        db_session.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == cid)
        .first()
    )
    canon.body_locked = False
    db_session.commit()

    resp = client.post(_train_url(cid), headers=_headers(token))
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "not_ready_to_train"
    assert detail["blocking_reasons"]


def test_train_character_not_found(client, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    _enable_training(monkeypatch)
    resp = client.post(_train_url(999999), headers=_headers(token))
    assert resp.status_code == 404


# ── Happy path with the fake provider ───────────────────────────────────────────


def test_train_fake_provider_creates_job(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    _enable_training(monkeypatch, provider="fake")

    resp = client.post(_train_url(cid), headers=_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider"] == "fake"
    assert data["state"] == "running"             # local job started
    assert data["identity_status"] == "training"  # identity advanced
    assert data["external_job_id"] == "fake-job-1"
    assert data["cost_usd"] == 0.34

    model = (
        db_session.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == cid)
        .first()
    )
    assert model.status == "training"


def test_train_then_poll_completes_and_creates_version(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    _enable_training(monkeypatch, provider="fake")

    job = client.post(_train_url(cid), headers=_headers(token)).json()
    resp = client.post(_poll_url(job["job_id"]), headers=_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["state"] == "completed"
    assert data["identity_status"] == "ready"
    assert data["version_id"] is not None

    versions = (
        db_session.query(AdultIdentityModelVersion)
        .filter(AdultIdentityModelVersion.id == data["version_id"])
        .all()
    )
    assert len(versions) == 1
    assert versions[0].state == "active"
    assert versions[0].lora_weights_uri == "r2://fake/adult/lora.safetensors"


def test_poll_provider_failure_marks_failed(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    _enable_training(monkeypatch, provider="fake")

    # Submit with a normal fake, then poll through a FAILING fake (no live calls).
    job = client.post(_train_url(cid), headers=_headers(token)).json()

    failing = FakeTrainingProvider(fail=True, fail_reason="provider content refusal")
    monkeypatch.setattr(
        "app.api.routes.adult_studio_admin.get_training_provider",
        lambda *a, **k: failing,
    )
    resp = client.post(_poll_url(job["job_id"]), headers=_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["state"] == "failed"
    assert data["identity_status"] == "failed"
    assert data["error"] == "provider content refusal"

    # No version created on failure.
    model = (
        db_session.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == cid)
        .first()
    )
    assert (
        db_session.query(AdultIdentityModelVersion)
        .filter(AdultIdentityModelVersion.identity_id == model.id)
        .count()
        == 0
    )


def test_poll_disabled_returns_409(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    _enable_training(monkeypatch, provider="fake")
    job = client.post(_train_url(cid), headers=_headers(token)).json()

    # Turn training off; polling must 409 (and not construct a provider).
    monkeypatch.setattr(cfg_module.settings, "ADULT_STUDIO_TRAINING_ENABLED", False)
    resp = client.post(_poll_url(job["job_id"]), headers=_headers(token))
    assert resp.status_code == 409


def test_poll_job_not_found(client, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    _enable_training(monkeypatch)
    resp = client.post(_poll_url(999999), headers=_headers(token))
    assert resp.status_code == 404
