"""Unit tests for the face signature extractor (B12)."""
from unittest.mock import MagicMock, patch


# ── No API key → ok=False, no exception ──────────────────────────────

def test_no_api_key_returns_ok_false(monkeypatch):
    """When OPENAI_API_KEY is absent, ok=False and no exception raised."""
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", None)
    from app.services.face_signature import build_face_signature_from_png
    result = build_face_signature_from_png(b"\x89PNG\r\n")
    assert result["ok"] is False
    assert result["signature"] == ""
    assert result["skip_reason"] == "no_api_key"


def test_no_api_key_empty_string_returns_ok_false(monkeypatch):
    """Empty string API key is also treated as absent."""
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "")
    from app.services.face_signature import build_face_signature_from_png
    result = build_face_signature_from_png(b"\x89PNG\r\n")
    assert result["ok"] is False


# ── Successful API response ───────────────────────────────────────────

def _mock_openai_response(signature: str, confidence: float = 0.9):
    """Build a minimal mock OpenAI chat completion response."""
    import json as _json
    msg = MagicMock()
    msg.content = _json.dumps({"signature": signature, "confidence": confidence})
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def test_successful_response_returns_ok_true(monkeypatch):
    """Valid API response produces ok=True and populates signature."""
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.core.config.settings.OPENAI_VISION_MODEL", "gpt-4o-mini")

    sig_text = "FACE_SIG: square jaw, high cheekbones, almond eyes"
    mock_resp = _mock_openai_response(sig_text)

    with patch("openai.OpenAI") as MockClient:
        MockClient.return_value.chat.completions.create.return_value = mock_resp
        from app.services import face_signature as fs_mod
        # Force reimport so monkeypatched settings take effect
        import importlib
        importlib.reload(fs_mod)
        result = fs_mod.build_face_signature_from_png(b"\x89PNG\r\n")

    assert result["ok"] is True
    assert result["signature"] == sig_text
    assert result["confidence"] == 0.9
    assert result["skip_reason"] == ""


def test_signature_trimmed_to_220_chars(monkeypatch):
    """Signatures longer than 220 chars are hard-trimmed."""
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.core.config.settings.OPENAI_VISION_MODEL", "gpt-4o-mini")

    long_sig = "FACE_SIG: " + "x" * 300  # 310 chars
    mock_resp = _mock_openai_response(long_sig, confidence=0.8)

    with patch("openai.OpenAI") as MockClient:
        MockClient.return_value.chat.completions.create.return_value = mock_resp
        from app.services import face_signature as fs_mod
        import importlib
        importlib.reload(fs_mod)
        result = fs_mod.build_face_signature_from_png(b"\x89PNG\r\n")

    assert result["ok"] is True
    assert len(result["signature"]) == 220


def test_empty_signature_returns_ok_false(monkeypatch):
    """If the model returns an empty string, ok=False is returned."""
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.core.config.settings.OPENAI_VISION_MODEL", "gpt-4o-mini")

    mock_resp = _mock_openai_response("", confidence=0.1)

    with patch("openai.OpenAI") as MockClient:
        MockClient.return_value.chat.completions.create.return_value = mock_resp
        from app.services import face_signature as fs_mod
        import importlib
        importlib.reload(fs_mod)
        result = fs_mod.build_face_signature_from_png(b"\x89PNG\r\n")

    assert result["ok"] is False
    assert result["skip_reason"] == "empty_signature"


def test_malformed_json_returns_ok_false(monkeypatch):
    """Non-JSON response returns ok=False without raising."""
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.core.config.settings.OPENAI_VISION_MODEL", "gpt-4o-mini")

    msg = MagicMock()
    msg.content = "This is not JSON at all"
    choice = MagicMock()
    choice.message = msg
    bad_resp = MagicMock()
    bad_resp.choices = [choice]

    with patch("openai.OpenAI") as MockClient:
        MockClient.return_value.chat.completions.create.return_value = bad_resp
        from app.services import face_signature as fs_mod
        import importlib
        importlib.reload(fs_mod)
        result = fs_mod.build_face_signature_from_png(b"\x89PNG\r\n")

    assert result["ok"] is False
    assert result["skip_reason"] == "parse_error"


def test_api_exception_returns_ok_false(monkeypatch):
    """If OpenAI raises an exception, ok=False is returned without propagating."""
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.core.config.settings.OPENAI_VISION_MODEL", "gpt-4o-mini")

    with patch("openai.OpenAI") as MockClient:
        MockClient.return_value.chat.completions.create.side_effect = RuntimeError("network error")
        from app.services import face_signature as fs_mod
        import importlib
        importlib.reload(fs_mod)
        result = fs_mod.build_face_signature_from_png(b"\x89PNG\r\n")

    assert result["ok"] is False
    assert result["skip_reason"] == "api_error"


def test_markdown_fence_stripped(monkeypatch):
    """Model response wrapped in ```json fences is parsed correctly."""
    import json as _json
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("app.core.config.settings.OPENAI_VISION_MODEL", "gpt-4o-mini")

    payload = _json.dumps({"signature": "FACE_SIG: oval face, soft brows", "confidence": 0.85})
    msg = MagicMock()
    msg.content = f"```json\n{payload}\n```"
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]

    with patch("openai.OpenAI") as MockClient:
        MockClient.return_value.chat.completions.create.return_value = resp
        from app.services import face_signature as fs_mod
        import importlib
        importlib.reload(fs_mod)
        result = fs_mod.build_face_signature_from_png(b"\x89PNG\r\n")

    assert result["ok"] is True
    assert "oval face" in result["signature"]
