"""Unit tests for GoogleImageProvider timeout, prompt-block and MIME handling."""
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
    s.GOOGLE_IMAGE_MODEL = "gemini-3.1-flash-image"
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


# ── Prompt-level blocks (promptFeedback.blockReason) ──────────────────
#
# Gemini answers a blocked prompt with HTTP 200, a promptFeedback block and NO
# candidates key. That must surface as a parseable marker, not as the opaque
# "response missing expected structure: {json}" string that made every block
# indistinguishable from a genuine sexual refusal.


def _blocked_response(block_reason: str, safety_ratings: list | None = None) -> bytes:
    feedback: dict = {"blockReason": block_reason}
    if safety_ratings is not None:
        feedback["safetyRatings"] = safety_ratings
    return json.dumps({
        "promptFeedback": feedback,
        "modelVersion": "gemini-3.1-flash-image",
    }).encode()


def _call_each_path(provider, png: bytes):
    """The three provider entry points, so a block is asserted on all of them."""
    return (
        ("text_to_image", lambda: provider.generate_text_to_image(prompt="p")),
        ("grounded", lambda: provider.generate_with_reference(
            prompt="p", reference_image_bytes=png)),
        ("multi", lambda: provider.generate_with_multi_reference(
            prompt="p", reference_images=[png])),
    )


class TestGooglePromptBlock:
    @pytest.mark.parametrize("path_name", ["text_to_image", "grounded", "multi"])
    def test_block_other_raises_parseable_marker(self, path_name):
        from app.services.image_providers.google_provider import GoogleImageProvider

        png = _make_png()

        def _fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse(_blocked_response("OTHER"))

        with patch(
            "app.services.image_providers.google_provider.settings", _mock_settings()
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = GoogleImageProvider()
            call = dict(_call_each_path(provider, png))[path_name]
            with pytest.raises(RuntimeError) as exc:
                call()

        message = str(exc.value)
        assert "google_prompt_blocked:OTHER" in message, message
        # The old opaque phrasing must NOT be what a blocked prompt produces.
        assert "missing expected structure" not in message, message

    def test_block_carries_safety_categories(self):
        from app.services.image_providers.google_provider import GoogleImageProvider

        ratings = [{"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "probability": "HIGH"}]

        def _fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse(_blocked_response("SAFETY", ratings))

        with patch(
            "app.services.image_providers.google_provider.settings", _mock_settings()
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = GoogleImageProvider()
            with pytest.raises(RuntimeError) as exc:
                provider.generate_text_to_image(prompt="p")

        assert "HARM_CATEGORY_SEXUALLY_EXPLICIT=HIGH" in str(exc.value)

    def test_unblocked_response_still_returns_image(self):
        """A normal 200 is completely unaffected by the block check."""
        from app.services.image_providers.google_provider import GoogleImageProvider

        png = _make_png()

        def _fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse(_google_response(png))

        with patch(
            "app.services.image_providers.google_provider.settings", _mock_settings()
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            provider = GoogleImageProvider()
            assert provider.generate_text_to_image(prompt="p") == png


class TestParsePromptBlock:
    def test_parses_reason_and_categories(self):
        from app.services.image_providers.google_provider import parse_prompt_block

        reason, cats = parse_prompt_block(
            "google_prompt_blocked:SAFETY:HARM_CATEGORY_SEXUALLY_EXPLICIT=HIGH,X=LOW"
        )
        assert reason == "SAFETY"
        assert cats == ["HARM_CATEGORY_SEXUALLY_EXPLICIT=HIGH", "X=LOW"]

    def test_other_with_no_categories(self):
        from app.services.image_providers.google_provider import parse_prompt_block

        assert parse_prompt_block("google_prompt_blocked:OTHER:") == ("OTHER", [])

    @pytest.mark.parametrize("text", [
        "", "temporary upstream 503", "google_refused_image: IMAGE_RECITATION",
    ])
    def test_non_marker_returns_none(self, text):
        from app.services.image_providers.google_provider import parse_prompt_block

        assert parse_prompt_block(text) == (None, [])


# ── Reference MIME type ───────────────────────────────────────────────
#
# The mime type was hardcoded to image/png for every reference, mislabelling the
# JPEG/WebP cards the admin canon-upload route accepts and stores untranscoded.


def _encode(fmt: str) -> bytes:
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(90, 20, 30)).save(buf, format=fmt)
    return buf.getvalue()


def _captured_payload(sender) -> dict:
    """Run ``sender`` against a stubbed transport and return the request body."""
    captured: dict = {}
    png = _make_png()

    def _fake_urlopen(req, timeout=None):
        captured["payload"] = json.loads(req.data)
        return _FakeHTTPResponse(_google_response(png))

    with patch(
        "app.services.image_providers.google_provider.settings", _mock_settings()
    ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
        from app.services.image_providers.google_provider import GoogleImageProvider
        sender(GoogleImageProvider())
    return captured["payload"]


class TestReferenceMimeType:
    @pytest.mark.parametrize("fmt,expected", [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("WEBP", "image/webp"),
    ])
    def test_grounded_declares_actual_mime(self, fmt, expected):
        ref = _encode(fmt)
        payload = _captured_payload(
            lambda p: p.generate_with_reference(prompt="p", reference_image_bytes=ref)
        )
        parts = payload["contents"][0]["parts"]
        assert parts[0]["inlineData"]["mimeType"] == expected

    @pytest.mark.parametrize("fmt,expected", [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("WEBP", "image/webp"),
    ])
    def test_multi_reference_declares_actual_mime(self, fmt, expected):
        ref = _encode(fmt)
        payload = _captured_payload(
            lambda p: p.generate_with_multi_reference(prompt="p", reference_images=[ref])
        )
        parts = payload["contents"][0]["parts"]
        assert parts[0]["inlineData"]["mimeType"] == expected

    def test_mixed_formats_each_labelled_independently(self):
        refs = [_encode("PNG"), _encode("JPEG"), _encode("WEBP")]
        payload = _captured_payload(
            lambda p: p.generate_with_multi_reference(prompt="p", reference_images=refs)
        )
        parts = payload["contents"][0]["parts"]
        assert [p["inlineData"]["mimeType"] for p in parts[:3]] == [
            "image/png", "image/jpeg", "image/webp",
        ]
        # Text prompt still travels last, after every image part.
        assert parts[-1]["text"] == "p"

    def test_unsniffable_bytes_fall_back_to_png(self):
        """Unrecognised bytes keep the pre-change behaviour exactly."""
        payload = _captured_payload(
            lambda p: p.generate_with_reference(
                prompt="p", reference_image_bytes=b"not-an-image")
        )
        assert payload["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "image/png"

    def test_reference_bytes_round_trip_unchanged(self):
        """References are declared differently but never transcoded."""
        ref = _encode("JPEG")
        payload = _captured_payload(
            lambda p: p.generate_with_reference(prompt="p", reference_image_bytes=ref)
        )
        sent = base64.b64decode(payload["contents"][0]["parts"][0]["inlineData"]["data"])
        assert sent == ref
