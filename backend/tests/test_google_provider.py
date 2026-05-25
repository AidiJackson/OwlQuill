"""Unit tests for GoogleImageProvider timeout configuration."""
from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest


class _FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _google_response(image_bytes: bytes) -> bytes:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "candidates": [{
            "content": {
                "parts": [{"inlineData": {"mimeType": "image/png", "data": encoded}}]
            }
        }]
    }
    return json.dumps(body).encode()


def _make_png() -> bytes:
    from PIL import Image
    import io
    img = Image.new("RGB", (64, 64), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mock_settings(timeout: int = 180) -> MagicMock:
    s = MagicMock()
    s.GOOGLE_AI_API_KEY = "fake-key"
    s.GOOGLE_IMAGE_MODEL = "imagen-3.0-generate-001"
    s.GOOGLE_IMAGE_TIMEOUT_S = timeout
    return s


class TestGoogleProviderTimeout:
    def test_default_timeout_is_180(self):
        from app.core.config import Settings
        assert Settings.__fields__["GOOGLE_IMAGE_TIMEOUT_S"].default == 180

    def test_urlopen_uses_configured_timeout(self):
        from app.services.image_providers.google_provider import GoogleImageProvider

        png = _make_png()
        captured: list[int] = []

        def _fake_urlopen(req, timeout=None):
            captured.append(timeout)
            return _FakeHTTPResponse(_google_response(png))

        mock_settings = _mock_settings(timeout=240)
        with patch(
            "app.services.image_providers.google_provider.settings", mock_settings
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = GoogleImageProvider()
            provider.generate_text_to_image(prompt="test portrait")

        assert captured == [240], f"Expected timeout=240, got {captured}"

    def test_timeout_error_logs_provider_and_seconds(self, caplog):
        import logging
        from app.services.image_providers.google_provider import GoogleImageProvider

        mock_settings = _mock_settings(timeout=180)

        def _raise_timeout(req, timeout=None):
            raise TimeoutError("timed out")

        with patch(
            "app.services.image_providers.google_provider.settings", mock_settings
        ), patch("urllib.request.urlopen", side_effect=_raise_timeout), caplog.at_level(
            logging.WARNING, logger="app.services.image_providers.google_provider"
        ):
            provider = GoogleImageProvider()
            with pytest.raises(RuntimeError, match="Google Gemini request failed"):
                provider.generate_text_to_image(prompt="test")

        assert any(
            "provider=google" in r.message and "timeout_seconds=180" in r.message
            for r in caplog.records
        ), f"Expected timeout log with provider and seconds, got: {[r.message for r in caplog.records]}"
