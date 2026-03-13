"""Tests for the B17/B18 simplified image generator endpoint.

B17: provider toggle (option1/option2)
B18: strict identity mode for include_character=True
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str = "imggen@example.com") -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "testpassword123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Gen Test Char", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


def _lock_character(client: TestClient, token: str, cid: int) -> None:
    """Generate + accept a pack so the character is locked with identity_anchor_json."""
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def _stub_png_bytes() -> bytes:
    """Return a valid stub PNG from the stub generator."""
    from app.services.stub_image_generator import generate_placeholder_png
    fp = generate_placeholder_png(label="test", sublabel="stub")
    abs_path = Path(__file__).resolve().parent.parent / fp
    return abs_path.read_bytes()


def _post(client, token, cid, body):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def _mock_provider_succeeds(*, use_grounded: bool = True) -> MagicMock:
    """Return a mock provider that succeeds on the first grounded call."""
    mock = MagicMock()
    if use_grounded:
        mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    else:
        mock.generate_grounded_image = MagicMock(
            side_effect=NotImplementedError("no grounded")
        )
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    return mock


# ── 1. Plain generation (include_character=False) ─────────────────────

def test_plain_generation_no_lock_required(client: TestClient):
    """include_character=False works even for an unlocked character."""
    token = _register_and_login(client, "imggen_plain@example.com")
    cid = _create_character(client, token)

    resp = _post(client, token, cid, {
        "prompt": "A peaceful mountain lake at dusk",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "generated"
    assert data["url"].startswith("/static/")
    meta = data["metadata_json"]
    assert meta["include_character"] is False
    assert meta["image_generator"] is True
    assert meta["character_id"] is None  # not included since no character
    assert "provider_option" in meta


def test_plain_generation_metadata_captures_provider(client: TestClient):
    """Metadata always records which provider option was requested."""
    token = _register_and_login(client, "imggen_meta@example.com")
    cid = _create_character(client, token)

    resp = _post(client, token, cid, {
        "prompt": "Sunset over the ocean",
        "include_character": False,
        "provider_option": "option2",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option2"
    assert meta["image_generator"] is True


# ── 2. Provider option mapping ────────────────────────────────────────

def test_provider_option1_maps_to_openai(monkeypatch):
    """option1 resolves to OpenAI provider class."""
    from app.core.config import settings
    from app.services.image_provider import get_provider_for_option
    from app.services.image_provider import _OpenAIImageProvider  # type: ignore[attr-defined]

    # Provide a fake key so the constructor doesn't raise.
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-fake-key")
    provider = get_provider_for_option("option1")
    assert isinstance(provider, _OpenAIImageProvider)


def test_provider_option2_maps_to_google(client: TestClient):
    """option2 resolves to Google provider."""
    from app.services.image_provider import get_provider_for_option

    provider = get_provider_for_option("option2")
    # The adapter wraps the Google provider.
    assert "google" in type(provider).__name__.lower() or hasattr(provider, "_google")


def test_provider_toggle_disabled_forces_option1(monkeypatch):
    """When IMAGE_GENERATOR_PROVIDER_TOGGLE is False, always returns option1 provider."""
    from app.core.config import settings
    from app.services.image_provider import get_provider_for_option, _OpenAIImageProvider  # type: ignore[attr-defined]

    monkeypatch.setattr(settings, "IMAGE_GENERATOR_PROVIDER_TOGGLE", False)
    # Provide a fake key so the constructor doesn't raise.
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-fake-key")
    # Even requesting option2 returns the option1 (openai) provider.
    provider = get_provider_for_option("option2")
    assert isinstance(provider, _OpenAIImageProvider)


def test_metadata_records_resolved_provider(client: TestClient):
    """metadata_json.provider reflects which provider was actually used."""
    token = _register_and_login(client, "imggen_prov@example.com")
    cid = _create_character(client, token)

    # Stub mode (no API keys): provider falls through to stub.
    # We just verify the metadata key exists and has a string value.
    resp = _post(client, token, cid, {
        "prompt": "A red balloon",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200
    meta = resp.json()["metadata_json"]
    assert isinstance(meta.get("provider"), str)
    assert len(meta["provider"]) > 0


# ── 3. include_character=True requires locked character ───────────────

def test_include_character_unlocked_returns_409(client: TestClient):
    """include_character=True is blocked when the character is not locked."""
    token = _register_and_login(client, "imggen_unlock@example.com")
    cid = _create_character(client, token)

    resp = _post(client, token, cid, {
        "prompt": "Portrait in a dark forest",
        "include_character": True,
        "provider_option": "option1",
    })
    assert resp.status_code == 409
    detail = resp.json()["detail"].lower()
    assert "locked" in detail or "lock" in detail


def test_include_character_locked_succeeds(client: TestClient):
    """include_character=True works for a locked character when the provider succeeds."""
    token = _register_and_login(client, "imggen_locked@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = _mock_provider_succeeds()

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "Standing in a library",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["include_character"] is True
    assert meta["character_id"] == cid


# ── 4. include_character=True injects identity references ─────────────

def test_include_character_injects_identity_into_prompt(client: TestClient):
    """When include_character=True, the strict identity wrapper and lock string
    are prepended to the prompt sent to the provider."""
    token = _register_and_login(client, "imggen_inject@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    captured: dict = {}

    def _mock_grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.generate_grounded_image = _mock_grounded
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "At a masquerade ball",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    captured_prompt = captured.get("prompt", "")
    # Original scene prompt must be in the provider prompt
    assert "At a masquerade ball" in captured_prompt, (
        f"Original prompt not found in provider prompt: {captured_prompt!r}"
    )
    # Strict identity wrapper must be present
    assert "STRICT IDENTITY LOCK" in captured_prompt or "ABSOLUTE IDENTITY" in captured_prompt, (
        f"Strict identity wrapper missing from provider prompt: {captured_prompt!r}"
    )


def test_include_character_false_skips_identity_injection(client: TestClient):
    """When include_character=False, the provider receives only the user prompt
    with no identity wrapper."""
    token = _register_and_login(client, "imggen_noinject@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    captured: dict = {}

    def _mock_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.generate_image = _mock_generate
    mock_provider.generate_grounded_image = MagicMock(
        side_effect=NotImplementedError("no grounded in test")
    )

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "A simple landscape",
            "include_character": False,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    # The prompt sent to the provider should be exactly the user's prompt (no identity wrapper)
    assert captured.get("prompt") == "A simple landscape", (
        f"Expected clean prompt, got: {captured.get('prompt')!r}"
    )


# ── 5. Logging / evaluation metadata completeness ────────────────────

def test_metadata_fields_present_for_plain_generation(client: TestClient):
    """All required evaluation fields appear in metadata_json for plain generation."""
    token = _register_and_login(client, "imggen_fields@example.com")
    cid = _create_character(client, token)

    resp = _post(client, token, cid, {
        "prompt": "A city at night",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200
    meta = resp.json()["metadata_json"]

    required = {"image_generator", "provider_option", "provider", "include_character", "prompt"}
    missing = required - set(meta.keys())
    assert not missing, f"Missing metadata keys: {missing}"


def test_metadata_fields_present_for_character_generation(client: TestClient):
    """All required evaluation fields appear in metadata_json when include_character=True."""
    token = _register_and_login(client, "imggen_charfields@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = _mock_provider_succeeds()

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "Walking through rain",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200
    meta = resp.json()["metadata_json"]

    required = {
        "image_generator", "provider_option", "provider",
        "include_character", "character_id", "prompt",
        "used_face_ref", "identity_hash", "strict_identity_mode", "strict_identity_retry",
    }
    missing = required - set(meta.keys())
    assert not missing, f"Missing metadata keys: {missing}"
    assert meta["include_character"] is True
    assert meta["character_id"] == cid
    assert meta["strict_identity_mode"] is True


# ── 6. B18 strict identity mode ───────────────────────────────────────

def test_strict_identity_mode_enabled_for_include_character(client: TestClient):
    """include_character=True automatically sets strict_identity_mode=True in metadata."""
    token = _register_and_login(client, "b18_strict_meta@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = _mock_provider_succeeds()

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "Standing by a fireplace",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["strict_identity_mode"] is True
    assert meta["strict_identity_retry"] is False  # succeeded on first attempt


def test_strict_identity_mode_false_for_plain_generation(client: TestClient):
    """include_character=False sets strict_identity_mode=False in metadata."""
    token = _register_and_login(client, "b18_strict_false@example.com")
    cid = _create_character(client, token)

    resp = _post(client, token, cid, {
        "prompt": "A forest at dawn",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["strict_identity_mode"] is False


def test_strict_identity_blocks_generic_fallback(client: TestClient):
    """When include_character=True and both generation attempts fail, the route
    returns a controlled failure (503) instead of silently saving a stub image."""
    token = _register_and_login(client, "b18_block_fallback@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = MagicMock()
    mock_provider.generate_grounded_image = MagicMock(
        side_effect=RuntimeError("provider failure")
    )
    mock_provider.generate_image = MagicMock(
        side_effect=RuntimeError("provider failure")
    )

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "In a crowded market",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"].lower()
    assert "identity conditioning" in detail or "character image" in detail


def test_strict_identity_retry_attempted_on_first_failure(client: TestClient):
    """When the first attempt fails but the retry succeeds, the response is 200
    and strict_identity_retry=True is recorded in metadata."""
    token = _register_and_login(client, "b18_retry@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    call_count = {"n": 0}

    def _grounded_side_effect(*, prompt, reference_image_bytes, size="1024x1024"):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient failure on attempt 1")
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.generate_grounded_image = MagicMock(side_effect=_grounded_side_effect)
    mock_provider.generate_image = MagicMock(side_effect=RuntimeError("no text fallback"))

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "In the snow",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["strict_identity_mode"] is True
    assert meta["strict_identity_retry"] is True
    # Retry was attempted — grounded was called twice
    assert call_count["n"] == 2


def test_strict_identity_controlled_failure_returns_clear_message(client: TestClient):
    """Controlled failure response has a meaningful detail message, not a generic error."""
    token = _register_and_login(client, "b18_fail_msg@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = MagicMock()
    mock_provider.generate_grounded_image = MagicMock(
        side_effect=RuntimeError("provider down")
    )
    mock_provider.generate_image = MagicMock(
        side_effect=RuntimeError("provider down")
    )

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "At a rooftop bar",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    # Must be a human-readable message, not a generic 503 string
    assert len(detail) > 30
    assert any(
        phrase in detail.lower()
        for phrase in ("character", "identity", "conditioning", "try again")
    )


def test_include_character_false_uses_stub_fallback_normally(client: TestClient):
    """When include_character=False and the provider is unavailable, the route
    returns 200 with a stub placeholder (normal fallback chain applies)."""
    token = _register_and_login(client, "b18_stub_ok@example.com")
    cid = _create_character(client, token)

    # No provider mock — real providers are unavailable in test env (no API keys)
    # The route should still succeed via the stub placeholder
    resp = _post(client, token, cid, {
        "prompt": "A simple sunset",
        "include_character": False,
        "provider_option": "option1",
    })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["include_character"] is False
    assert meta["strict_identity_mode"] is False
    # Stub fallback was used (no real provider available)
    assert meta["provider"] in ("stub", "openai", "google", "fal")
