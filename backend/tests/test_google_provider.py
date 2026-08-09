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


# ── Bounded retry policy ──────────────────────────────────────────────
#
# Three failure classes, three strategies. Every retry re-sends the COMPLETE
# reference set in the SAME order — availability is never bought by weakening
# identity evidence.

def _http_error(code: int):
    import urllib.error
    return urllib.error.HTTPError(
        url="https://generativelanguage.googleapis.com/x",
        code=code, msg="err", hdrs=None, fp=None,
    )


def _recitation_response() -> bytes:
    return json.dumps({"candidates": [{"finishReason": "IMAGE_RECITATION"}]}).encode()


def _block_response(reason: str = "OTHER", categories: list | None = None) -> bytes:
    return json.dumps({
        "promptFeedback": {"blockReason": reason, "safetyRatings": categories or []}
    }).encode()


def _provider():
    from app.services.image_providers.google_provider import GoogleImageProvider
    with patch("app.services.image_providers.google_provider.settings", _mock_settings()):
        return GoogleImageProvider()


def _sent_payloads(mock_urlopen) -> list[dict]:
    """Decode the JSON body of every request that was actually sent."""
    return [json.loads(c.args[0].data.decode()) for c in mock_urlopen.call_args_list]


class TestTransientRetry:
    """HTTP 408/429/5xx — the only class Google documents as retryable."""

    @pytest.mark.parametrize("code", [503, 500, 502, 504, 429, 408])
    def test_transient_retries_once_with_identical_payload(self, code):
        png = _make_png()
        provider = _provider()
        refs = [_make_png(), _make_png(), _make_png()]

        with patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
             patch("app.services.image_providers.google_provider.time.sleep") as sleep, \
             patch("urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [_http_error(code),
                                   _FakeHTTPResponse(_google_response(png))]
            out = provider.generate_with_multi_reference(
                prompt="Angelo in his office", reference_images=refs,
            )

        assert out == png
        assert urlopen.call_count == 2, "expected exactly one retry"
        sent = _sent_payloads(urlopen)
        assert sent[0] == sent[1], "retry must re-send the IDENTICAL payload"
        # And the complete reference set survived the retry.
        parts = sent[1]["contents"][0]["parts"]
        assert sum(1 for p in parts if "inlineData" in p) == 3
        assert "generationConfig" not in sent[1]
        sleep.assert_called_once()
        assert 0 < sleep.call_args.args[0] <= 1.25, "backoff must be short and jittered"

    def test_second_transient_failure_stops_no_loop(self):
        provider = _provider()
        with patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
             patch("app.services.image_providers.google_provider.time.sleep"), \
             patch("urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [_http_error(503), _http_error(503), _http_error(503)]
            with pytest.raises(RuntimeError) as exc:
                provider.generate_with_multi_reference(
                    prompt="p", reference_images=[_make_png()],
                )

        assert urlopen.call_count == 2, "must stop after one retry, never loop"
        assert "503" in str(exc.value)

    def test_non_transient_http_is_never_retried(self):
        """400/403 are client errors — retrying them is documented as wrong."""
        provider = _provider()
        for code in (400, 403):
            with patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
                 patch("urllib.request.urlopen") as urlopen:
                urlopen.side_effect = [_http_error(code), _http_error(code)]
                with pytest.raises(RuntimeError):
                    provider.generate_with_multi_reference(
                        prompt="p", reference_images=[_make_png()],
                    )
                assert urlopen.call_count == 1, f"HTTP {code} must not retry"


class TestRecitationRetry:
    """IMAGE_RECITATION is output-side and stochastic — one resample is valid."""

    def test_recitation_retries_once_with_temperature_only(self):
        png = _make_png()
        provider = _provider()
        refs = [_make_png(), _make_png(), _make_png(), _make_png()]

        with patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
             patch("urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [_FakeHTTPResponse(_recitation_response()),
                                   _FakeHTTPResponse(_google_response(png))]
            out = provider.generate_with_multi_reference(
                prompt="Angelo in his office", reference_images=refs,
            )

        assert out == png
        assert urlopen.call_count == 2
        first, second = _sent_payloads(urlopen)
        # Only generationConfig differs — same refs, same order, same prompt.
        assert "generationConfig" not in first
        assert second["generationConfig"]["temperature"] == 1.3
        assert first["contents"] == second["contents"], (
            "recitation retry must not alter references, order or prompt"
        )
        assert sum(1 for p in second["contents"][0]["parts"] if "inlineData" in p) == 4

    def test_repeated_recitation_stops_with_neutral_marker(self):
        provider = _provider()
        with patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
             patch("urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [_FakeHTTPResponse(_recitation_response()),
                                   _FakeHTTPResponse(_recitation_response()),
                                   _FakeHTTPResponse(_recitation_response())]
            with pytest.raises(RuntimeError) as exc:
                provider.generate_with_multi_reference(
                    prompt="p", reference_images=[_make_png()],
                )

        assert urlopen.call_count == 2, "one retry only — never a loop"
        msg = str(exc.value)
        assert "google_refused_image" in msg and "IMAGE_RECITATION" in msg
        for word in ("sexual", "adult", "explicit"):
            assert word not in msg.lower()


class TestPromptBlockNeverRetried:
    """blockReason is input-side and deterministic — a retry cannot help."""

    @pytest.mark.parametrize("reason", ["OTHER", "SAFETY", "PROHIBITED_CONTENT"])
    def test_block_performs_zero_retries(self, reason):
        provider = _provider()
        with patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
             patch("app.services.image_providers.google_provider.time.sleep") as sleep, \
             patch("urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [_FakeHTTPResponse(_block_response(reason)),
                                   _FakeHTTPResponse(_google_response(_make_png()))]
            with pytest.raises(RuntimeError) as exc:
                provider.generate_with_multi_reference(
                    prompt="p", reference_images=[_make_png(), _make_png()],
                )

        assert urlopen.call_count == 1, "a prompt block must never be retried"
        sleep.assert_not_called()
        assert f"google_prompt_blocked:{reason}" in str(exc.value)


class TestPayloadDiagnostic:
    """The permanent payload-size log line must stay, and stay leak-safe."""

    def test_payload_size_logged_without_sensitive_data(self, caplog):
        import logging
        provider = _provider()
        secret_prompt = "Angelo in his office with a SECRETPHRASE"
        refs = [_make_png(), _make_png()]

        with caplog.at_level(logging.INFO, logger="app.services.image_providers.google_provider"), \
             patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
             patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeHTTPResponse(_google_response(_make_png()))
            provider.generate_with_multi_reference(
                prompt=secret_prompt, reference_images=refs,
            )

        lines = [r.getMessage() for r in caplog.records
                 if "GOOGLE_MULTI_REF_PAYLOAD" in r.getMessage()]
        assert len(lines) == 1
        assert "refs=2" in lines[0]
        assert "payload_bytes=" in lines[0]
        assert "model=gemini-3.1-flash-image" in lines[0]
        # No prompt text, no credential, no base64 image data.
        assert "SECRETPHRASE" not in lines[0]
        assert "fake-key" not in lines[0]
        assert base64.b64encode(refs[0])[:24].decode() not in lines[0]

    def test_payload_size_logged_once_per_attempt(self):
        """Each retry is a real request and must be individually observable."""
        import logging
        provider = _provider()
        with patch("app.services.image_providers.google_provider.settings", _mock_settings()), \
             patch("app.services.image_providers.google_provider.time.sleep"), \
             patch("urllib.request.urlopen") as urlopen, \
             patch("app.services.image_providers.google_provider.logger") as log:
            urlopen.side_effect = [_http_error(503),
                                   _FakeHTTPResponse(_google_response(_make_png()))]
            provider.generate_with_multi_reference(prompt="p", reference_images=[_make_png()])

        payload_logs = [c for c in log.info.call_args_list
                        if "GOOGLE_MULTI_REF_PAYLOAD" in str(c.args[0])]
        assert len(payload_logs) == 2
