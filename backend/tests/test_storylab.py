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
