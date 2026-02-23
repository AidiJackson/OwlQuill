"""Tests for the grammar-check endpoint."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _lt_payload(matches: list | None = None) -> dict:
    """Minimal LanguageTool-shaped response."""
    return {
        "language": {"code": "en-US", "name": "English (US)"},
        "matches": matches or [],
    }


def _make_mock_client(payload: dict) -> MagicMock:
    """Return a patched httpx.AsyncClient whose .post() resolves to *payload*."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)
    return mock_client


# ── validation ────────────────────────────────────────────────────────────────

def test_grammar_check_empty_text(client: TestClient):
    """400 when text is empty or whitespace-only."""
    for bad in ("", "   ", "\n\t"):
        resp = client.post("/api/grammar/check", json={"text": bad})
        assert resp.status_code == 400, f"expected 400 for {bad!r}"


def test_grammar_check_text_too_long(client: TestClient):
    """400 when text exceeds 20 000 characters."""
    resp = client.post("/api/grammar/check", json={"text": "a" * 20_001})
    assert resp.status_code == 400


def test_grammar_check_exactly_at_limit(client: TestClient):
    """Text at exactly 20 000 chars is accepted (calls upstream)."""
    with patch("app.api.routes.grammar.httpx.AsyncClient") as cls:
        cls.return_value = _make_mock_client(_lt_payload())
        resp = client.post("/api/grammar/check", json={"text": "a" * 20_000})
    assert resp.status_code == 200


# ── happy path ────────────────────────────────────────────────────────────────

def test_grammar_check_no_matches(client: TestClient):
    """200 with empty matches list for clean text."""
    with patch("app.api.routes.grammar.httpx.AsyncClient") as cls:
        cls.return_value = _make_mock_client(_lt_payload())
        resp = client.post("/api/grammar/check", json={"text": "Hello world."})

    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "en-US"
    assert data["matches"] == []


def test_grammar_check_with_match(client: TestClient):
    """200 with normalised match structure."""
    raw_match = {
        "offset": 0,
        "length": 6,
        "message": "Use 'an' instead of 'a' before a vowel sound.",
        "shortMessage": "Wrong article",
        "rule": {
            "id": "EN_A_VS_AN",
            "description": "Use of 'a' vs 'an'",
            "issueType": "grammar",
            "category": {"id": "GRAMMAR", "name": "Grammar"},
        },
        "replacements": [{"value": "an hour"}],
    }
    with patch("app.api.routes.grammar.httpx.AsyncClient") as cls:
        cls.return_value = _make_mock_client(_lt_payload(matches=[raw_match]))
        resp = client.post(
            "/api/grammar/check",
            json={"text": "a hour ago today.", "language": "en-US"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["language"] == "en-US"
    assert len(data["matches"]) == 1
    m = data["matches"][0]
    assert m["offset"] == 0
    assert m["length"] == 6
    assert m["message"] == "Use 'an' instead of 'a' before a vowel sound."
    assert m["shortMessage"] == "Wrong article"
    assert m["rule"]["id"] == "EN_A_VS_AN"
    assert m["rule"]["issueType"] == "grammar"
    assert m["rule"]["category"] == "Grammar"
    assert m["replacements"] == [{"value": "an hour"}]


def test_grammar_check_default_language(client: TestClient):
    """Language defaults to en-US when omitted."""
    with patch("app.api.routes.grammar.httpx.AsyncClient") as cls:
        cls.return_value = _make_mock_client(_lt_payload())
        resp = client.post("/api/grammar/check", json={"text": "Some text here."})

    assert resp.status_code == 200


# ── upstream error handling ───────────────────────────────────────────────────

def test_grammar_check_timeout(client: TestClient):
    """504 when LanguageTool times out."""
    import httpx as _httpx

    async def _timeout(*a, **kw):
        raise _httpx.TimeoutException("timed out")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = _timeout

    with patch("app.api.routes.grammar.httpx.AsyncClient") as cls:
        cls.return_value = mock_client
        resp = client.post("/api/grammar/check", json={"text": "Hello."})

    assert resp.status_code == 504


def test_grammar_check_upstream_error(client: TestClient):
    """502 when LanguageTool returns a non-2xx status."""
    import httpx as _httpx

    async def _bad_status(*a, **kw):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        raise _httpx.HTTPStatusError("boom", request=MagicMock(), response=mock_resp)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = _bad_status

    with patch("app.api.routes.grammar.httpx.AsyncClient") as cls:
        cls.return_value = mock_client
        resp = client.post("/api/grammar/check", json={"text": "Hello."})

    assert resp.status_code == 502
