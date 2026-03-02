"""Unit and integration tests for the OpenRouter image provider.

Tests are fully offline — all HTTP is mocked via unittest.mock.patch.
"""
from __future__ import annotations

import base64
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ──────────────────────────────────────────────────────────

def _make_png(width: int = 512, height: int = 768) -> bytes:
    """Create a minimal in-memory portrait PNG."""
    from PIL import Image
    import io
    img = Image.new("RGB", (width, height), color=(80, 120, 160))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _openrouter_response(image_bytes: bytes) -> bytes:
    """Build a fake OpenRouter chat completion JSON response body."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "choices": [{
            "message": {
                "images": [{
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded}"
                    }
                }]
            }
        }]
    }
    return json.dumps(body).encode()


class _FakeHTTPResponse:
    """Minimal urllib response stub."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


# ── Unit tests: OpenRouterImageProvider ──────────────────────────────

class TestOpenRouterProviderUnit:
    """Tests exercised directly against OpenRouterImageProvider (no FastAPI)."""

    def _make_provider(self):
        """Return an initialised provider with a fake API key."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"
        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ):
            return OpenRouterImageProvider()

    def test_generate_image_parses_base64_data_url(self):
        """generate_text_to_image returns correct PNG bytes decoded from data URL."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        expected_png = _make_png()
        fake_resp = _FakeHTTPResponse(_openrouter_response(expected_png))

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ), patch(
            "urllib.request.urlopen", return_value=fake_resp
        ):
            provider = OpenRouterImageProvider()
            result = provider.generate_text_to_image(prompt="a serene forest")

        assert result == expected_png

    def test_generate_image_sends_correct_payload(self):
        """generate_text_to_image sends model, modalities, image_config, and text message."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        expected_png = _make_png()
        captured_requests: list = []

        def _fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            return _FakeHTTPResponse(_openrouter_response(expected_png))

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "test-model/image-v1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = OpenRouterImageProvider()
            provider.generate_text_to_image(prompt="portrait", size="1024x1024")

        assert len(captured_requests) == 1
        req = captured_requests[0]
        payload = json.loads(req.data)

        assert payload["model"] == "test-model/image-v1"
        assert payload["modalities"] == ["image", "text"]
        assert payload["image_config"]["size"] == "1024x1024"
        assert payload["messages"][0]["role"] == "user"
        content = payload["messages"][0]["content"]
        assert any(
            part.get("type") == "text" and part.get("text") == "portrait"
            for part in content
        ), f"Text part missing in content: {content}"

    def test_generate_grounded_image_sends_seed_in_messages(self):
        """generate_with_reference embeds the seed image as a data-URL image_url part."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        seed_png = _make_png(512, 512)
        output_png = _make_png(512, 768)
        captured_requests: list = []

        def _fake_urlopen(req, timeout=None):
            captured_requests.append(req)
            return _FakeHTTPResponse(_openrouter_response(output_png))

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = OpenRouterImageProvider()
            result = provider.generate_with_reference(
                prompt="same person, 3/4 view",
                reference_image_bytes=seed_png,
            )

        assert result == output_png
        assert len(captured_requests) == 1
        payload = json.loads(captured_requests[0].data)
        content = payload["messages"][0]["content"]

        # First part must be the seed image as a data URL
        image_part = content[0]
        assert image_part["type"] == "image_url"
        url = image_part["image_url"]["url"]
        assert url.startswith("data:image/png;base64,"), (
            f"Seed image part URL does not start with expected prefix: {url[:60]}"
        )
        # Verify the embedded bytes decode back to the original seed
        _, encoded = url.split(",", 1)
        assert base64.b64decode(encoded) == seed_png

        # Second part must be the text prompt
        text_part = content[1]
        assert text_part["type"] == "text"
        assert text_part["text"] == "same person, 3/4 view"

    def test_generate_grounded_returns_decoded_bytes(self):
        """generate_with_reference returns the base64-decoded image bytes."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        seed = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        expected = _make_png()
        fake_resp = _FakeHTTPResponse(_openrouter_response(expected))

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", return_value=fake_resp):
            provider = OpenRouterImageProvider()
            result = provider.generate_with_reference(
                prompt="angle shot",
                reference_image_bytes=seed,
            )

        assert result == expected

    def test_http_error_raises_runtime_error_without_retrying(self):
        """HTTP 4xx errors raise RuntimeError immediately (no retry)."""
        import urllib.error
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        call_count = 0

        def _fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            err = urllib.error.HTTPError(
                url="https://openrouter.ai/api/v1/chat/completions",
                code=429,
                msg="Too Many Requests",
                hdrs=MagicMock(),
                fp=BytesIO(b'{"error":"rate limited"}'),
            )
            raise err

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = OpenRouterImageProvider()
            with pytest.raises(RuntimeError, match="HTTP 429"):
                provider.generate_text_to_image(prompt="test")

        # Must not retry on HTTP errors
        assert call_count == 1

    def test_transient_error_retries_up_to_max(self):
        """Transient network errors are retried up to _MAX_RETRIES times."""
        import urllib.error
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
            _MAX_RETRIES,
        )

        call_count = 0
        expected_png = _make_png()

        def _fake_urlopen(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count <= _MAX_RETRIES:
                raise urllib.error.URLError("transient connection error")
            return _FakeHTTPResponse(_openrouter_response(expected_png))

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = OpenRouterImageProvider()
            result = provider.generate_text_to_image(prompt="test")

        assert result == expected_png
        assert call_count == _MAX_RETRIES + 1  # succeeded on last allowed attempt

    def test_all_retries_exhausted_raises_runtime_error(self):
        """RuntimeError raised when all retry attempts are transient failures."""
        import urllib.error
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
            _MAX_RETRIES,
        )

        def _always_fail(req, timeout=None):
            raise urllib.error.URLError("connection refused")

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_always_fail):
            provider = OpenRouterImageProvider()
            with pytest.raises(RuntimeError, match="failed after"):
                provider.generate_text_to_image(prompt="test")

    def test_missing_api_key_raises_on_init(self):
        """RuntimeError raised at construction time when API key is absent."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = ""

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ):
            with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
                OpenRouterImageProvider()

    def test_parse_image_bytes_bad_structure_raises(self):
        """_parse_image_bytes raises RuntimeError on unexpected response shape."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        with pytest.raises(RuntimeError, match="missing expected image structure"):
            OpenRouterImageProvider._parse_image_bytes({"choices": []})

    def test_parse_image_bytes_non_data_url_raises(self):
        """_parse_image_bytes raises RuntimeError when URL is not a data URL."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        body = {
            "choices": [{
                "message": {
                    "images": [{"image_url": {"url": "https://example.com/img.png"}}]
                }
            }]
        }
        with pytest.raises(RuntimeError, match="unexpected image URL format"):
            OpenRouterImageProvider._parse_image_bytes(body)

    def test_empty_prompt_raises_value_error(self):
        """generate_text_to_image raises ValueError on empty prompt."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ):
            provider = OpenRouterImageProvider()
            with pytest.raises(ValueError, match="empty"):
                provider.generate_text_to_image(prompt="")

    def test_empty_reference_bytes_raises_value_error(self):
        """generate_with_reference raises ValueError when seed bytes are empty."""
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch(
            "app.services.image_providers.openrouter_provider.settings",
            mock_settings,
        ):
            provider = OpenRouterImageProvider()
            with pytest.raises(ValueError, match="empty"):
                provider.generate_with_reference(
                    prompt="angle shot",
                    reference_image_bytes=b"",
                )


# ── Factory / wiring tests ────────────────────────────────────────────

class TestOpenRouterProviderWiring:

    def test_get_identity_image_provider_returns_openrouter_adapter(self):
        """get_identity_image_provider() returns the OpenRouter adapter when configured."""
        from app.services.image_provider import (
            _OpenRouterImageProviderAdapter,
            get_identity_image_provider,
        )

        mock_settings = MagicMock()
        mock_settings.IDENTITY_IMAGE_PROVIDER = "openrouter"
        mock_settings.IMAGE_PROVIDER = "openai"
        mock_settings.OPENROUTER_API_KEY = "sk-or-test-key"
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch("app.services.image_provider.settings", mock_settings), patch(
            "app.services.image_providers.openrouter_provider.settings", mock_settings
        ):
            provider = get_identity_image_provider()

        assert isinstance(provider, _OpenRouterImageProviderAdapter)
        assert provider.supports_image_guidance is True

    def test_get_identity_image_provider_openrouter_raises_without_key(self):
        """get_identity_image_provider() raises RuntimeError when API key is missing."""
        from app.services.image_provider import get_identity_image_provider

        mock_settings = MagicMock()
        mock_settings.IDENTITY_IMAGE_PROVIDER = "openrouter"
        mock_settings.IMAGE_PROVIDER = "openai"
        mock_settings.OPENROUTER_API_KEY = ""
        mock_settings.OPENROUTER_IMAGE_MODEL = "openai/gpt-image-1"

        with patch("app.services.image_provider.settings", mock_settings), patch(
            "app.services.image_providers.openrouter_provider.settings", mock_settings
        ):
            with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
                get_identity_image_provider()


# ── Integration test: endpoint uses OpenRouter when configured ────────

def _register_and_login_or(client: TestClient) -> str:
    client.post(
        "/auth/register",
        json={
            "email": "ortest@example.com",
            "username": "oruser",
            "password": "testpassword123",
        },
    )
    resp = client.post(
        "/auth/login",
        json={"email": "ortest@example.com", "password": "testpassword123"},
    )
    return resp.json()["access_token"]


def test_identity_pack_uses_openrouter_when_configured(client: TestClient):
    """When IDENTITY_IMAGE_PROVIDER=openrouter, the endpoint uses the OpenRouter adapter."""
    token = _register_and_login_or(client)

    resp = client.post(
        "/characters/",
        json={"name": "Orion Vex", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    cid = resp.json()["id"]

    fake_png = _make_png()
    captured_prompts: list[str] = []

    def _capture(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "openrouter"
    mock_settings.IMAGE_PROVIDER = "openai"

    with patch(
        "app.api.routes.character_visual.get_identity_image_provider",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "brooding mercenary"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    assert data["tier_used"] == "A"

    # Front prompt must include the passport headshot token (B4)
    assert len(captured_prompts) >= 1
    assert "passport-style headshot" in captured_prompts[0].lower(), (
        f"Front prompt missing passport headshot: {captured_prompts[0]!r}"
    )

    # Grounded method called 3× for angle shots
    assert mock_provider.generate_grounded_image.call_count == 3
