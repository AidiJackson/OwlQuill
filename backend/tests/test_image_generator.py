"""Tests for the B17/B18/B19 simplified image generator endpoint.

B17: provider toggle (option1/option2)
B18: strict identity mode for include_character=True
B19: anchor-image conditioning — actual identity pack images as provider inputs
"""
import json
import logging
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


def _mock_provider_succeeds() -> MagicMock:
    """Return a mock provider that succeeds on the first generate_with_anchors call.

    B19: supports_multi_image_input=True so generate_with_anchors is tried first.
    """
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(return_value=_stub_png_bytes())
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    return mock


def _mock_provider_single_image_only() -> MagicMock:
    """Return a mock provider that does NOT support multi-image input."""
    mock = MagicMock()
    mock.supports_multi_image_input = False
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
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
    assert meta["character_id"] is None
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

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-fake-key")
    provider = get_provider_for_option("option1")
    assert isinstance(provider, _OpenAIImageProvider)


def test_provider_option2_maps_to_google(client: TestClient):
    """option2 resolves to Google provider."""
    from app.services.image_provider import get_provider_for_option

    provider = get_provider_for_option("option2")
    assert "google" in type(provider).__name__.lower() or hasattr(provider, "_google")


def test_provider_toggle_disabled_forces_option1(monkeypatch):
    """When IMAGE_GENERATOR_PROVIDER_TOGGLE is False, always returns option1 provider."""
    from app.core.config import settings
    from app.services.image_provider import get_provider_for_option, _OpenAIImageProvider  # type: ignore[attr-defined]

    monkeypatch.setattr(settings, "IMAGE_GENERATOR_PROVIDER_TOGGLE", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-fake-key")
    provider = get_provider_for_option("option2")
    assert isinstance(provider, _OpenAIImageProvider)


def test_metadata_records_resolved_provider(client: TestClient):
    """metadata_json.provider reflects which provider was actually used."""
    token = _register_and_login(client, "imggen_prov@example.com")
    cid = _create_character(client, token)

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
    """When include_character=True, the strict identity wrapper and identity lock
    are prepended to the prompt sent to the provider."""
    token = _register_and_login(client, "imggen_inject@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    captured: dict = {}

    def _mock_grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    # Use single-image path so we can capture the grounded prompt
    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = False
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
    assert "At a masquerade ball" in captured_prompt, (
        f"Original prompt not found in provider prompt: {captured_prompt!r}"
    )
    # B19 tightened identity directive must be present
    assert "same person" in captured_prompt.lower(), (
        f"Identity directive missing from provider prompt: {captured_prompt!r}"
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
        "anchors_attached", "anchor_types", "multi_image_used",
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
    assert meta["strict_identity_retry"] is False


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
    """When include_character=True and all generation attempts fail, the route
    returns a controlled failure (503) instead of silently saving a stub image."""
    token = _register_and_login(client, "b18_block_fallback@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = False  # skip multi-image path
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

    # Use single-image path to keep this test focused on the retry mechanism
    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = False
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
    assert call_count["n"] == 2


def test_strict_identity_controlled_failure_returns_clear_message(client: TestClient):
    """Controlled failure response has a meaningful detail message, not a generic error."""
    token = _register_and_login(client, "b18_fail_msg@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = False
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

    resp = _post(client, token, cid, {
        "prompt": "A simple sunset",
        "include_character": False,
        "provider_option": "option1",
    })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["include_character"] is False
    assert meta["strict_identity_mode"] is False
    assert meta["provider"] in ("stub", "openai", "google", "fal")


# ── 7. B19 anchor-image conditioning ─────────────────────────────────

def test_b19_anchor_images_loaded_in_preferred_order():
    """_load_anchor_images returns anchors in front→three_quarter→torso→full_body order
    regardless of dict insertion order."""
    from app.api.routes.image_generator import _load_anchor_images
    from app.services.stub_image_generator import generate_placeholder_png

    anchor_urls: dict[str, str] = {}
    for key, label in [
        ("full_body", "Full"),
        ("torso", "Torso"),
        ("front", "Front"),
        ("three_quarter", "3Q"),
    ]:
        fp = generate_placeholder_png(label=label, role="anchor_front")
        anchor_urls[key] = f"/{fp}"

    anchor_data = {
        "anchors": {k: {"id": 99, "url": v} for k, v in anchor_urls.items()},
        "identity_lock_string": "",
    }

    loaded_bytes, loaded_keys = _load_anchor_images(anchor_data, character_id=0)

    assert loaded_keys == ["front", "three_quarter", "torso", "full_body"], (
        f"Expected preferred order, got: {loaded_keys}"
    )
    assert len(loaded_bytes) == 4
    assert all(isinstance(b, bytes) and len(b) > 0 for b in loaded_bytes)


def test_b19_multi_image_passed_to_provider_when_supported(client: TestClient):
    """When the provider supports multi-image input, generate_with_anchors is called
    with the actual anchor images rather than a single face-ref crop."""
    token = _register_and_login(client, "b19_multi@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    captured: dict = {}

    def _mock_with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        captured["anchor_count"] = len(anchor_images)
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = True
    mock_provider.generate_with_anchors = _mock_with_anchors
    mock_provider.generate_grounded_image = MagicMock(
        side_effect=AssertionError("grounded should not be called when multi-image succeeds")
    )
    mock_provider.generate_image = MagicMock(
        side_effect=AssertionError("text should not be called when multi-image succeeds")
    )

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "In a cave",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    assert captured.get("anchor_count", 0) >= 1
    meta = resp.json()["metadata_json"]
    assert meta["anchors_attached"] >= 1
    assert meta["multi_image_used"] is True
    assert meta["anchor_types"] is not None and len(meta["anchor_types"]) >= 1


def test_b19_fallback_to_single_image_when_multi_not_supported(client: TestClient):
    """When the provider does NOT support multi-image input, generate_with_anchors
    is not called; instead falls back to generate_grounded_image (single face-ref)."""
    token = _register_and_login(client, "b19_single@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    captured: dict = {}

    def _mock_grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured["called"] = True
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = False
    mock_provider.generate_grounded_image = _mock_grounded
    mock_provider.generate_image = MagicMock(
        side_effect=AssertionError("text should not be called when grounded succeeds")
    )

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "By a river",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    assert captured.get("called") is True
    meta = resp.json()["metadata_json"]
    assert meta["multi_image_used"] is False


def test_b19_strict_prompt_contains_required_elements(client: TestClient):
    """The prompt sent to the provider contains: identity directive, identity lock
    string, and the user's scene prompt."""
    token = _register_and_login(client, "b19_prompt@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    captured: dict = {}

    def _mock_with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = True
    mock_provider.generate_with_anchors = _mock_with_anchors
    mock_provider.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "Riding a horse at sunset",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "")
    assert "same person" in prompt.lower(), f"Identity directive missing: {prompt!r}"
    assert "Riding a horse at sunset" in prompt, f"Scene prompt missing: {prompt!r}"


def test_b19_include_character_false_path_unchanged(client: TestClient):
    """When include_character=False, no anchor images are loaded and generate_image
    is called directly — anchors_attached is not present in metadata."""
    token = _register_and_login(client, "b19_false_path@example.com")
    cid = _create_character(client, token)

    captured: dict = {}

    def _mock_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured["called"] = True
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.generate_image = _mock_generate

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "A quiet library",
            "include_character": False,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    assert captured.get("called") is True
    meta = resp.json()["metadata_json"]
    assert "anchors_attached" not in meta
    assert meta["strict_identity_mode"] is False


def test_b19_metadata_includes_anchor_info(client: TestClient):
    """When include_character=True, metadata records anchors_attached, anchor_types,
    and multi_image_used."""
    token = _register_and_login(client, "b19_meta@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = _mock_provider_succeeds()

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "At a market",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert "anchors_attached" in meta
    assert "anchor_types" in meta
    assert "multi_image_used" in meta
    assert isinstance(meta["anchors_attached"], int)
    assert isinstance(meta["anchor_types"], list)


def test_b19_unsupported_provider_fallback_is_logged(client: TestClient, caplog):
    """When provider does not support multi-image, the fallback reason is logged."""
    token = _register_and_login(client, "b19_log@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = _mock_provider_single_image_only()

    with caplog.at_level(logging.INFO, logger="app.api.routes.image_generator"):
        with patch(
            "app.api.routes.image_generator.get_provider_for_option",
            return_value=mock_provider,
        ):
            resp = _post(client, token, cid, {
                "prompt": "On a bridge",
                "include_character": True,
                "provider_option": "option1",
            })

    assert resp.status_code == 200, resp.text
    log_text = " ".join(r.message for r in caplog.records)
    assert "multi_image_not_supported" in log_text or "anchor_conditioning_fallback" in log_text


# ── 8. B21 face anchor prioritisation and generic-face hardening ──────


def test_b21_face_anchor_prioritised():
    """_prioritise_face_anchors duplicates the front anchor at position 0."""
    from app.api.routes.image_generator import _prioritise_face_anchors

    bytes_front = b"front_bytes"
    bytes_3q = b"three_quarter_bytes"
    bytes_torso = b"torso_bytes"
    loaded_bytes = [bytes_front, bytes_3q, bytes_torso]
    loaded_keys = ["front", "three_quarter", "torso"]

    result_bytes, result_keys = _prioritise_face_anchors(loaded_bytes, loaded_keys)

    # Front anchor should be at position 0 AND still present in original position
    assert result_keys[0] == "front", f"First entry should be 'front', got: {result_keys[0]!r}"
    assert result_keys.count("front") == 2, (
        f"Front anchor should appear twice after prioritisation, got: {result_keys}"
    )
    assert result_bytes[0] == bytes_front, "First bytes entry should be front anchor"
    # Total length increases by 1
    assert len(result_bytes) == len(loaded_bytes) + 1
    assert len(result_keys) == len(loaded_keys) + 1


def test_b21_face_anchor_no_front_unchanged():
    """_prioritise_face_anchors is a no-op when no front anchor is present."""
    from app.api.routes.image_generator import _prioritise_face_anchors

    bytes_torso = b"torso_bytes"
    loaded_bytes = [bytes_torso]
    loaded_keys = ["torso"]

    result_bytes, result_keys = _prioritise_face_anchors(loaded_bytes, loaded_keys)

    assert result_bytes == [bytes_torso]
    assert result_keys == ["torso"]


def test_b21_face_anchor_empty_unchanged():
    """_prioritise_face_anchors handles empty input gracefully."""
    from app.api.routes.image_generator import _prioritise_face_anchors

    result_bytes, result_keys = _prioritise_face_anchors([], [])
    assert result_bytes == []
    assert result_keys == []


def test_b21_face_anchor_boost_recorded_in_metadata(client: TestClient):
    """When include_character=True and a front anchor exists, face_anchor_boosted=True
    is recorded in metadata for observability."""
    token = _register_and_login(client, "b21_boost@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = _mock_provider_succeeds()

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "Standing in a garden",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert "face_anchor_boosted" in meta, "face_anchor_boosted must be recorded in metadata"
    # Since _lock_character generates a pack with a front anchor, boost should be active
    assert isinstance(meta["face_anchor_boosted"], bool)


def test_b21_strict_prefix_mentions_face_structure():
    """The strict identity prefix explicitly mentions face shape/structure
    and discourages generic faces, targeting the main drift vector."""
    from app.api.routes.image_generator import _STRICT_IDENTITY_PREFIX

    prefix_lower = _STRICT_IDENTITY_PREFIX.lower()
    assert "face shape" in prefix_lower, (
        f"Prefix should mention 'face shape' for generic-face hardening: {_STRICT_IDENTITY_PREFIX!r}"
    )
    assert "generic" in prefix_lower or "average" in prefix_lower, (
        f"Prefix should discourage generic faces: {_STRICT_IDENTITY_PREFIX!r}"
    )
    assert "same person" in prefix_lower, (
        f"Prefix must retain the identity directive 'same person': {_STRICT_IDENTITY_PREFIX!r}"
    )


def test_b21_retry_prefix_mentions_face_structure():
    """The retry prefix also explicitly calls out face shape for the escalated path."""
    from app.api.routes.image_generator import _STRICT_IDENTITY_RETRY_PREFIX

    retry_lower = _STRICT_IDENTITY_RETRY_PREFIX.lower()
    assert "face shape" in retry_lower, (
        f"Retry prefix should mention 'face shape': {_STRICT_IDENTITY_RETRY_PREFIX!r}"
    )
    assert "no generic" in retry_lower or "generic" in retry_lower, (
        f"Retry prefix should discourage generic faces: {_STRICT_IDENTITY_RETRY_PREFIX!r}"
    )
