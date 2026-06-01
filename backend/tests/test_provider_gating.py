"""Beta provider gating — OpenAI is admin-only; Google is the Canon default.

Closed beta: Google (option2) is the primary Canon image provider for every
user. OpenAI (option1) is gated to admins for internal testing; a non-admin
OpenAI request safely falls back to Google with audit metadata rather than
being hard-rejected.

Covers:
  * unit: resolve_canon_provider_option gating matrix
  * endpoint: non-admin default → Google, no fallback metadata
  * endpoint: non-admin OpenAI request → Google + fallback audit metadata
  * endpoint: admin OpenAI request → allowed, no fallback
  * existing Google path unaffected
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.image_provider import (
    CANON_DEFAULT_PROVIDER_OPTION,
    resolve_canon_provider_option,
)


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


# ── Helpers ───────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "testpassword123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Leonardo Baptiste", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


def _make_admin(db_session, email: str) -> None:
    from app.models.user import User as UserModel
    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == email).first()
    assert user is not None, f"User {email!r} not found"
    user.is_admin = True
    db_session.commit()


def _stub_png_bytes() -> bytes:
    from app.services.stub_image_generator import generate_placeholder_png
    fp = generate_placeholder_png(label="test", sublabel="stub")
    return (Path(__file__).resolve().parent.parent / fp).read_bytes()


def _capturing_provider(captured: dict) -> MagicMock:
    """A provider mock that always succeeds via text generation."""
    mock = MagicMock()
    mock.supports_multi_image_input = False
    mock.generate_image = lambda *, prompt, **_: (
        captured.__setitem__("prompt", prompt) or _stub_png_bytes()
    )
    mock.generate_grounded_image = MagicMock(side_effect=NotImplementedError())
    return mock


def _post(client, token, cid, body):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


# ── Unit: gating matrix ───────────────────────────────────────────────


class TestResolveCanonProviderOption:

    def test_non_admin_openai_falls_back_to_google(self):
        opt, meta = resolve_canon_provider_option("option1", is_admin=False)
        assert opt == "option2"  # google
        assert meta == {
            "original_requested_provider": "openai",
            "provider_fallback_reason": "openai_admin_only_beta",
        }

    def test_admin_openai_allowed(self):
        opt, meta = resolve_canon_provider_option("option1", is_admin=True)
        assert opt == "option1"  # openai
        assert meta == {}

    def test_non_admin_google_allowed(self):
        opt, meta = resolve_canon_provider_option("option2", is_admin=False)
        assert opt == "option2"
        assert meta == {}

    def test_admin_google_allowed(self):
        opt, meta = resolve_canon_provider_option("option2", is_admin=True)
        assert opt == "option2"
        assert meta == {}

    def test_default_option_is_google(self):
        assert CANON_DEFAULT_PROVIDER_OPTION == "option2"

    def test_unknown_option_collapses_to_google(self):
        opt, meta = resolve_canon_provider_option("optionX", is_admin=False)
        assert opt == "option2"
        assert meta == {}


# ── Endpoint: non-admin behaviour ─────────────────────────────────────


def test_non_admin_default_provider_is_google(client: TestClient):
    """No provider_option supplied → defaults to Google, no fallback metadata."""
    token = _register_and_login(client, "gate_default@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "A quiet harbour at dawn",
        "include_character": False,
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option2"
    assert "provider_fallback_reason" not in meta
    assert "original_requested_provider" not in meta


def test_non_admin_openai_request_falls_back_to_google(client: TestClient):
    """A non-admin explicitly requesting OpenAI is silently routed to Google
    with an audit trail — not hard-rejected."""
    token = _register_and_login(client, "gate_fallback@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "A red kite over a field",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option2"  # forced to Google
    assert meta["original_requested_provider"] == "openai"
    assert meta["provider_fallback_reason"] == "openai_admin_only_beta"


# ── Endpoint: admin behaviour ─────────────────────────────────────────


def test_admin_can_request_openai(client: TestClient, db_session):
    """An admin requesting OpenAI keeps option1 and gets no fallback metadata."""
    email = "gate_admin@example.com"
    token = _register_and_login(client, email)
    cid = _create_character(client, token)
    _make_admin(db_session, email)

    captured: dict = {}
    with patch(
        "app.api.routes.image_generator.get_provider_for_option",
        return_value=_capturing_provider(captured),
    ):
        resp = _post(client, token, cid, {
            "prompt": "A lighthouse in a storm",
            "include_character": False,
            "provider_option": "option1",
        })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option1"  # admin keeps OpenAI
    assert "provider_fallback_reason" not in meta


def test_existing_google_path_unaffected(client: TestClient):
    """A non-admin explicitly choosing Google works exactly as before."""
    token = _register_and_login(client, "gate_google@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "A field of sunflowers",
        "include_character": False,
        "provider_option": "option2",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option2"
    assert "provider_fallback_reason" not in meta
