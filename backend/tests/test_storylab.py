"""Tests for the StoryLab state + generate endpoints."""
import pytest
from fastapi.testclient import TestClient


# ── helpers ───────────────────────────────────────────────────────────────────

_BASE_GENERATE = {
    "story_id": "test-story-001",
    "text": "The rain fell softly on the quiet street.",
    "controls": {
        "direction": "advance_plot",
        "tone_intensity": "moderate",
        "pacing": "balanced",
        "length": "medium",
        "boundary": "sfw",
    },
}


# ── GET /state ────────────────────────────────────────────────────────────────

def test_get_state_creates_default(client: TestClient):
    """GET /state for unknown story_id creates a default row and returns schema."""
    resp = client.get("/api/storylab/state", params={"story_id": "new-story-abc"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["story_id"] == "new-story-abc"
    assert data["story_summary"] == ""
    assert "state_json" in data
    assert "story_state" in data["state_json"]
    assert "updated_at" in data


def test_get_state_returns_existing(client: TestClient):
    """GET /state is idempotent — calling twice returns same story_id."""
    for _ in range(2):
        resp = client.get("/api/storylab/state", params={"story_id": "idempotent-story"})
        assert resp.status_code == 200
        assert resp.json()["story_id"] == "idempotent-story"


def test_get_state_requires_story_id(client: TestClient):
    """GET /state without story_id returns 422 (missing query param)."""
    resp = client.get("/api/storylab/state")
    assert resp.status_code == 422


def test_get_state_default_state_json_shape(client: TestClient):
    """Default state_json contains expected top-level keys."""
    resp = client.get("/api/storylab/state", params={"story_id": "shape-check-story"})
    assert resp.status_code == 200
    sj = resp.json()["state_json"]
    assert "story_state" in sj
    assert "characters" in sj
    assert "relationships" in sj
    ss = sj["story_state"]
    assert "tension" in ss
    assert "intimacy_level" in ss


# ── POST /generate ────────────────────────────────────────────────────────────

def test_generate_returns_continuation(client: TestClient):
    """POST /generate returns generated text and updates state."""
    resp = client.post("/api/storylab/generate", json=_BASE_GENERATE)
    assert resp.status_code == 200
    data = resp.json()
    assert "request_id" in data
    assert data["generated"]["text"]
    assert "state" in data
    assert "story_summary" in data["state"]
    assert "state_json" in data["state"]
    assert isinstance(data["state"]["deltas"], list)


def test_generate_creates_generation_log(client: TestClient):
    """POST /generate twice for the same story_id both succeed."""
    for i in range(2):
        body = dict(_BASE_GENERATE)
        body["story_id"] = "log-test-story"
        resp = client.post("/api/storylab/generate", json=body)
        assert resp.status_code == 200, f"iteration {i} failed: {resp.text}"


def test_generate_updates_state(client: TestClient):
    """After generate, GET /state reflects the updated state_json."""
    story_id = "update-test-story"
    client.post("/api/storylab/generate", json={**_BASE_GENERATE, "story_id": story_id,
        "controls": {**_BASE_GENERATE["controls"], "direction": "sad_moment"}})
    resp = client.get("/api/storylab/state", params={"story_id": story_id})
    assert resp.status_code == 200
    ss = resp.json()["state_json"]["story_state"]
    # sad_moment increments emotional_weight
    assert float(ss.get("emotional_weight", 0)) > 0.1


def test_generate_empty_text_rejected(client: TestClient):
    """POST /generate with empty text returns 400."""
    resp = client.post("/api/storylab/generate", json={**_BASE_GENERATE, "text": "   "})
    assert resp.status_code == 400


def test_generate_text_too_long_rejected(client: TestClient):
    """POST /generate with text > 50 000 chars returns 400."""
    resp = client.post("/api/storylab/generate", json={**_BASE_GENERATE, "text": "x" * 50_001})
    assert resp.status_code == 400


def test_generate_request_ids_are_unique(client: TestClient):
    """Each generate call returns a distinct request_id."""
    ids = set()
    for _ in range(3):
        resp = client.post("/api/storylab/generate", json=_BASE_GENERATE)
        assert resp.status_code == 200
        ids.add(resp.json()["request_id"])
    assert len(ids) == 3


def test_generate_safety_object(client: TestClient):
    """Safety block in response has expected shape."""
    resp = client.post("/api/storylab/generate", json=_BASE_GENERATE)
    assert resp.status_code == 200
    safety = resp.json()["safety"]
    assert safety["blocked"] is False
    assert safety["policy_flags"] == []
    assert safety["boundary"] == "sfw"


def test_generate_fade_to_black_sensual_allowed(client: TestClient):
    """fade_to_black boundary + sensual_scene direction is allowed."""
    body = {**_BASE_GENERATE, "controls": {
        "direction": "sensual_scene",
        "tone_intensity": "moderate",
        "pacing": "balanced",
        "length": "medium",
        "boundary": "fade_to_black",
    }}
    resp = client.post("/api/storylab/generate", json=body)
    assert resp.status_code == 200
    # Stub should include fade-to-black cue
    text = resp.json()["generated"]["text"]
    assert "curtain" in text.lower() or "dissolv" in text.lower() or "discreet" in text.lower()


# ── boundary conflict ─────────────────────────────────────────────────────────

def test_generate_boundary_conflict_returns_422(client: TestClient):
    """sfw boundary + intimate_scene direction returns 422 BOUNDARY_CONFLICT."""
    body = {**_BASE_GENERATE, "controls": {
        "direction": "intimate_scene",
        "tone_intensity": "moderate",
        "pacing": "balanced",
        "length": "medium",
        "boundary": "sfw",
    }}
    resp = client.post("/api/storylab/generate", json=body)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "BOUNDARY_CONFLICT"


def test_generate_boundary_conflict_sfw_sensual_scene_allowed(client: TestClient):
    """sfw boundary + sensual_scene is NOT blocked (only intimate_scene is)."""
    body = {**_BASE_GENERATE, "controls": {
        "direction": "sensual_scene",
        "tone_intensity": "light",
        "pacing": "slow",
        "length": "short",
        "boundary": "sfw",
    }}
    resp = client.post("/api/storylab/generate", json=body)
    assert resp.status_code == 200


def test_generate_direction_enum_invalid(client: TestClient):
    """Invalid direction enum returns 422 from Pydantic validation."""
    body = {**_BASE_GENERATE, "controls": {**_BASE_GENERATE["controls"], "direction": "explode_everything"}}
    resp = client.post("/api/storylab/generate", json=body)
    assert resp.status_code == 422


# ── provider / OpenRouter tests ───────────────────────────────────────────────

def _make_openrouter_mock(content: str):
    """Return a mock httpx.Client context manager that yields *content*."""
    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(return_value=None)
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post = MagicMock(return_value=mock_resp)
    return mock_client


def test_openrouter_provider_returns_model_text(monkeypatch):
    """With STORYLAB_PROVIDER=openrouter the service returns the model's content."""
    from unittest.mock import patch
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
    monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key-abc")

    model_output = "The door creaked open, revealing a silhouette neither of them expected."
    mock_client = _make_openrouter_mock(model_output)

    with patch.object(gen.httpx, "Client", return_value=mock_client):
        result = gen.generate_storylab_continuation(
            text="She reached for the handle.",
            controls=StoryLabControls(),
            state_json={},
            summary="A mystery unfolds in a quiet village.",
            characters=[],
            story_id="test-or-story",
        )

    assert result == model_output
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert payload["model"] == gen.settings.STORYLAB_MODEL
    assert any(m["role"] == "system" for m in payload["messages"])
    assert any(m["role"] == "user" for m in payload["messages"])


def test_openrouter_fallback_on_http_error(monkeypatch):
    """When OpenRouter returns a non-2xx status the service falls back to stub."""
    from unittest.mock import MagicMock, patch
    import httpx as _httpx
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
    monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key-abc")

    def _bad_post(*args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        raise _httpx.HTTPStatusError("boom", request=MagicMock(), response=mock_resp)

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post = _bad_post

    with patch.object(gen.httpx, "Client", return_value=mock_client):
        result = gen.generate_storylab_continuation(
            text="The fire crackled.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            story_id="fallback-story",
        )

    # Must return a non-empty string (stub output)
    assert isinstance(result, str)
    assert len(result) > 0


def test_openrouter_fallback_on_timeout(monkeypatch):
    """When OpenRouter times out the service falls back to stub."""
    from unittest.mock import MagicMock, patch
    import httpx as _httpx
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
    monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key-abc")

    def _timeout_post(*args, **kwargs):
        raise _httpx.TimeoutException("timed out")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post = _timeout_post

    with patch.object(gen.httpx, "Client", return_value=mock_client):
        result = gen.generate_storylab_continuation(
            text="Rain fell on the cobblestones.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            story_id="timeout-story",
        )

    assert isinstance(result, str)
    assert len(result) > 0


def test_openrouter_missing_key_uses_stub(monkeypatch):
    """When STORYLAB_PROVIDER=openrouter but key is empty, stub is used directly."""
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
    monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "")

    result = gen.generate_storylab_continuation(
        text="The village was quiet at dawn.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
        story_id="no-key-story",
    )

    assert isinstance(result, str)
    assert len(result) > 0


def test_openrouter_via_endpoint(client):
    """POST /generate works end-to-end with openrouter provider (mocked)."""
    from unittest.mock import patch
    import app.services.storylab_generator as gen

    model_output = "The stars above watched, indifferent to what was unfolding below."
    mock_client = _make_openrouter_mock(model_output)

    # Temporarily patch settings on the imported settings object in the service module
    original_provider = gen.settings.STORYLAB_PROVIDER
    original_key = gen.settings.OPENROUTER_API_KEY
    gen.settings.STORYLAB_PROVIDER = "openrouter"
    gen.settings.OPENROUTER_API_KEY = "test-key-endpoint"
    try:
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            resp = client.post("/api/storylab/generate", json=_BASE_GENERATE)
    finally:
        gen.settings.STORYLAB_PROVIDER = original_provider
        gen.settings.OPENROUTER_API_KEY = original_key

    assert resp.status_code == 200
    data = resp.json()
    assert data["generated"]["text"] == model_output
