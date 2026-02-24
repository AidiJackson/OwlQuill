"""Tests for the StoryLab state + generate endpoints."""
import pytest
from fastapi.testclient import TestClient

# ── prompt builder unit tests ─────────────────────────────────────────────────

def _make_controls(**overrides):
    from app.schemas.storylab import StoryLabControls
    return StoryLabControls(**overrides)


def test_build_prompt_contains_direction_instructions():
    """Prompt user block includes direction-specific guidance text."""
    from app.services.storylab_generator import build_storylab_prompt, direction_instructions
    from app.schemas.storylab import StoryLabControls, Direction

    controls = StoryLabControls(direction=Direction.sad_moment)
    messages = build_storylab_prompt(
        text="She stood at the window, watching the rain.",
        controls=controls,
        state_json={},
        summary="A quiet afternoon turns painful.",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    # Direction label present
    assert "sad_moment" in user_content
    # Direction-specific craft instruction present
    assert "grief" in user_content.lower() or "loss" in user_content.lower() or "body" in user_content.lower()
    # The instruction function itself is non-empty and direction-specific
    sad_instr = direction_instructions(Direction.sad_moment)
    assert len(sad_instr) > 30
    # Different directions produce different guidance
    assert sad_instr != direction_instructions(Direction.argument_begins)
    assert sad_instr != direction_instructions(Direction.twist_event)


def test_build_prompt_contains_boundary_instructions():
    """Prompt includes boundary guidance for each boundary value."""
    from app.services.storylab_generator import build_storylab_prompt, boundary_instructions
    from app.schemas.storylab import StoryLabControls, Boundary

    for boundary in (Boundary.sfw, Boundary.fade_to_black, Boundary.sensual):
        controls = StoryLabControls(boundary=boundary)
        messages = build_storylab_prompt(
            text="The candle burned low.",
            controls=controls,
            state_json={},
            summary="",
            characters=[],
        )
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert boundary in user_content
        instr = boundary_instructions(boundary)
        assert len(instr) > 20
        # Instructions are distinct across boundaries
    assert boundary_instructions(Boundary.sfw) != boundary_instructions(Boundary.sensual)
    assert boundary_instructions(Boundary.fade_to_black) != boundary_instructions(Boundary.sfw)


def test_build_prompt_contains_pacing_instructions():
    """Prompt includes pacing guidance and instructions differ across values."""
    from app.services.storylab_generator import build_storylab_prompt, pacing_instructions
    from app.schemas.storylab import StoryLabControls, Pacing

    for pacing in (Pacing.slow, Pacing.balanced, Pacing.fast):
        controls = StoryLabControls(pacing=pacing)
        messages = build_storylab_prompt(
            text="He waited.",
            controls=controls,
            state_json={},
            summary="",
            characters=[],
        )
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert pacing in user_content

    assert pacing_instructions(Pacing.slow) != pacing_instructions(Pacing.fast)
    assert pacing_instructions(Pacing.balanced) != pacing_instructions(Pacing.slow)


def test_build_prompt_contains_tone_instructions():
    """Prompt includes tone guidance and instructions differ across values."""
    from app.services.storylab_generator import build_storylab_prompt, tone_instructions
    from app.schemas.storylab import StoryLabControls, ToneIntensity

    for tone in (ToneIntensity.light, ToneIntensity.moderate, ToneIntensity.intense):
        controls = StoryLabControls(tone_intensity=tone)
        messages = build_storylab_prompt(
            text="The letter arrived unopened.",
            controls=controls,
            state_json={},
            summary="",
            characters=[],
        )
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert tone in user_content

    assert tone_instructions(ToneIntensity.light) != tone_instructions(ToneIntensity.intense)


def test_build_prompt_scene_text_included():
    """The scene text (or a tail of it) is present in the user message."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    scene = "Mara turned away from the fire. The smoke tasted of pine and something older."
    messages = build_storylab_prompt(
        text=scene,
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "Mara" in user_content
    assert "pine" in user_content


def test_build_prompt_continuation_requirement_present():
    """User message contains a continuation instruction."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    messages = build_storylab_prompt(
        text="The crowd fell silent.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "Continue" in user_content or "continuation" in user_content.lower()


def test_build_prompt_returns_system_and_user_messages():
    """build_storylab_prompt returns exactly two messages: system + user."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    messages = build_storylab_prompt(
        text="It began with a letter.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    assert len(messages) == 2
    roles = {m["role"] for m in messages}
    assert roles == {"system", "user"}
    assert all(isinstance(m["content"], str) and m["content"] for m in messages)


def test_build_prompt_includes_output_contract():
    """System message contains the <STORY> output contract."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    messages = build_storylab_prompt(
        text="The old bridge creaked underfoot.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    system_content = next(m["content"] for m in messages if m["role"] == "system")
    assert "<STORY>" in system_content
    assert "<DELTA_SIGNALS>" in system_content


def test_parse_model_output_extracts_story_tag():
    """_parse_model_output extracts text inside <STORY> tags."""
    from app.services.storylab_generator import _parse_model_output

    raw = (
        "<STORY>\nThe door opened slowly.\n</STORY>\n"
        '<DELTA_SIGNALS>\n{"tension_delta":0.1}\n</DELTA_SIGNALS>'
    )
    result = _parse_model_output(raw)
    assert result == "The door opened slowly."


def test_parse_model_output_falls_back_to_raw():
    """_parse_model_output returns raw text when tags are absent."""
    from app.services.storylab_generator import _parse_model_output

    raw = "She stepped back into the shadow of the doorway."
    assert _parse_model_output(raw) == raw


def test_parse_delta_signals_valid_json():
    """_parse_delta_signals extracts and parses the JSON block correctly."""
    from app.services.storylab_generator import _parse_delta_signals

    raw = (
        "<STORY>Some prose.</STORY>\n"
        '<DELTA_SIGNALS>\n{"tension_delta":0.05,"emotional_weight_delta":0.1,'
        '"intimacy_delta":0.0,"stakes_delta":0.0,"scene_type":"sad_moment"}\n</DELTA_SIGNALS>'
    )
    result = _parse_delta_signals(raw)
    assert result is not None
    assert result["tension_delta"] == pytest.approx(0.05)
    assert result["scene_type"] == "sad_moment"


def test_parse_delta_signals_returns_none_on_missing():
    """_parse_delta_signals returns None when the block is absent."""
    from app.services.storylab_generator import _parse_delta_signals

    assert _parse_delta_signals("Just some prose, no tags.") is None


def test_parse_delta_signals_returns_none_on_bad_json():
    """_parse_delta_signals returns None when the JSON is malformed."""
    from app.services.storylab_generator import _parse_delta_signals

    raw = "<DELTA_SIGNALS>{broken json here}</DELTA_SIGNALS>"
    assert _parse_delta_signals(raw) is None


def test_direction_instructions_all_directions_covered():
    """direction_instructions returns non-empty, distinct text for all Direction values."""
    from app.services.storylab_generator import direction_instructions
    from app.schemas.storylab import Direction

    results = {d: direction_instructions(d) for d in Direction}
    assert all(len(v) > 20 for v in results.values()), "Some direction instructions are too short"
    # All 10 directions have unique instructions
    assert len(set(results.values())) == len(Direction), "Direction instructions are not all unique"


def test_state_json_included_in_prompt():
    """State json fields (tension, intimacy_level) appear in the user message."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    state_json = {
        "story_state": {
            "tone": "neutral",
            "pacing": "balanced",
            "stakes": 0.4,
            "tension": 0.65,
            "emotional_weight": 0.3,
            "intimacy_level": 2,
        }
    }
    messages = build_storylab_prompt(
        text="The meeting had not gone well.",
        controls=StoryLabControls(),
        state_json=state_json,
        summary="",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "tension" in user_content
    assert "0.65" in user_content


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
        text, _delta = gen.generate_storylab_continuation(
            text="She reached for the handle.",
            controls=StoryLabControls(),
            state_json={},
            summary="A mystery unfolds in a quiet village.",
            characters=[],
            story_id="test-or-story",
        )

    assert text == model_output
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
        text, delta = gen.generate_storylab_continuation(
            text="The fire crackled.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            story_id="fallback-story",
        )

    # Must return a non-empty string (stub output) with no delta signals
    assert isinstance(text, str)
    assert len(text) > 0
    assert delta is None


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
        text, delta = gen.generate_storylab_continuation(
            text="Rain fell on the cobblestones.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            story_id="timeout-story",
        )

    assert isinstance(text, str)
    assert len(text) > 0
    assert delta is None


def test_openrouter_missing_key_uses_stub(monkeypatch):
    """When STORYLAB_PROVIDER=openrouter but key is empty, stub is used directly."""
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
    monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "")

    text, delta = gen.generate_storylab_continuation(
        text="The village was quiet at dawn.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
        story_id="no-key-story",
    )

    assert isinstance(text, str)
    assert len(text) > 0
    assert delta is None


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


# ── apply_model_deltas unit tests ─────────────────────────────────────────────

def test_apply_model_deltas_applies_values():
    """apply_model_deltas merges model signals into story_state correctly."""
    from app.api.routes.storylab import apply_model_deltas
    from app.schemas.storylab import Boundary

    state = {
        "story_state": {"tension": 0.2, "emotional_weight": 0.1, "stakes": 0.3, "intimacy_level": 0},
        "characters": [],
    }
    model_deltas = {
        "tension_delta": 0.1,
        "emotional_weight_delta": 0.05,
        "stakes_delta": 0.0,
        "intimacy_delta": 0.0,
    }
    result = apply_model_deltas(state, model_deltas, Boundary.sfw)
    ss = result["story_state"]
    assert ss["tension"] == pytest.approx(0.3, abs=1e-3)
    assert ss["emotional_weight"] == pytest.approx(0.15, abs=1e-3)
    assert ss["stakes"] == pytest.approx(0.3, abs=1e-3)  # unchanged


def test_apply_model_deltas_clamps_extreme_values():
    """Values outside ±0.2 are clamped before being applied."""
    from app.api.routes.storylab import apply_model_deltas
    from app.schemas.storylab import Boundary

    state = {"story_state": {"tension": 0.5, "emotional_weight": 0.5}, "characters": []}
    # Supply deltas well beyond the ±0.2 cap
    model_deltas = {"tension_delta": 0.9, "emotional_weight_delta": -0.9}
    result = apply_model_deltas(state, model_deltas, Boundary.sfw)
    ss = result["story_state"]
    # 0.5 + 0.2 (clamped) = 0.7
    assert ss["tension"] == pytest.approx(0.7, abs=1e-3)
    # 0.5 + (-0.2) (clamped) = 0.3
    assert ss["emotional_weight"] == pytest.approx(0.3, abs=1e-3)


def test_apply_model_deltas_ignores_unknown_keys():
    """Keys not in the allowed set are silently ignored."""
    from app.api.routes.storylab import apply_model_deltas
    from app.schemas.storylab import Boundary

    state = {"story_state": {"tension": 0.3, "tone": "neutral"}, "characters": []}
    model_deltas = {
        "tension_delta": 0.05,
        "unknown_field_delta": 999.9,   # must be ignored
        "scene_type": "revelation",      # must be ignored
    }
    result = apply_model_deltas(state, model_deltas, Boundary.sfw)
    ss = result["story_state"]
    assert ss["tension"] == pytest.approx(0.35, abs=1e-3)
    assert "unknown_field_delta" not in ss
    # tone should be untouched
    assert ss.get("tone") == "neutral"


def test_apply_model_deltas_respects_intimacy_cap():
    """intimacy_delta is capped at the boundary's intimacy ceiling."""
    from app.api.routes.storylab import apply_model_deltas
    from app.schemas.storylab import Boundary

    state = {"story_state": {"intimacy_level": 1.8}, "characters": []}
    # sfw cap = 2; delta 0.2 would bring it to 2.0 exactly
    result_sfw = apply_model_deltas(state, {"intimacy_delta": 0.2}, Boundary.sfw)
    assert result_sfw["story_state"]["intimacy_level"] == pytest.approx(2.0, abs=1e-3)

    # sensual cap = 8; same delta should bring it to 2.0
    result_sensual = apply_model_deltas(state, {"intimacy_delta": 0.2}, Boundary.sensual)
    assert result_sensual["story_state"]["intimacy_level"] == pytest.approx(2.0, abs=1e-3)

    # Attempting to push past sfw cap (2) should be clamped to 2
    state_at_cap = {"story_state": {"intimacy_level": 2.0}, "characters": []}
    result_capped = apply_model_deltas(state_at_cap, {"intimacy_delta": 0.2}, Boundary.sfw)
    assert result_capped["story_state"]["intimacy_level"] == pytest.approx(2.0, abs=1e-3)


def test_generate_stub_returns_none_delta():
    """Stub path returns (str, None) — no delta signals from deterministic output."""
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    text, delta = gen.generate_storylab_continuation(
        text="The lantern swayed in the breeze.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
        story_id="stub-delta-test",
    )
    assert isinstance(text, str) and len(text) > 0
    assert delta is None


def test_openrouter_with_delta_signals_updates_state(client):
    """When OpenRouter returns DELTA_SIGNALS, they are merged into the state."""
    from unittest.mock import patch
    import app.services.storylab_generator as gen

    # Model output includes both STORY and DELTA_SIGNALS tags
    model_output = (
        "<STORY>The tension in the room was unmistakable.</STORY>\n"
        '<DELTA_SIGNALS>{"tension_delta":0.15,"emotional_weight_delta":0.1,'
        '"intimacy_delta":0.0,"stakes_delta":0.0,"scene_type":"confrontation"}'
        "</DELTA_SIGNALS>"
    )
    mock_client = _make_openrouter_mock(model_output)

    original_provider = gen.settings.STORYLAB_PROVIDER
    original_key = gen.settings.OPENROUTER_API_KEY
    gen.settings.STORYLAB_PROVIDER = "openrouter"
    gen.settings.OPENROUTER_API_KEY = "test-key-delta"
    try:
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            resp = client.post(
                "/api/storylab/generate",
                json={**_BASE_GENERATE, "story_id": "delta-signal-story",
                      "controls": {**_BASE_GENERATE["controls"], "direction": "argument_begins"}},
            )
    finally:
        gen.settings.STORYLAB_PROVIDER = original_provider
        gen.settings.OPENROUTER_API_KEY = original_key

    assert resp.status_code == 200
    data = resp.json()
    # The story text should be the extracted <STORY> content
    assert data["generated"]["text"] == "The tension in the room was unmistakable."
    # State should reflect both deterministic deltas AND model signals
    ss = data["state"]["state_json"]["story_state"]
    # argument_begins deterministically nudges tension by 0.15; model adds another 0.15 (clamped to 0.2)
    # Starting tension = 0.2; after deterministic = 0.35; after model clamp = 0.35 + 0.15 = 0.50
    assert float(ss["tension"]) > 0.3


# ── quality guardrails unit tests ─────────────────────────────────────────────

def test_build_prompt_includes_word_target_and_cap():
    """User message contains the target word count and hard cap for the selected length."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls, Length

    for length, (target, cap) in [
        (Length.short, (350, 500)),
        (Length.medium, (1000, 1300)),
        (Length.long, (2000, 2400)),
    ]:
        controls = StoryLabControls(length=length)
        messages = build_storylab_prompt(
            text="The lantern flickered once, then steadied.",
            controls=controls,
            state_json={},
            summary="",
            characters=[],
        )
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert str(target) in user_content, f"target {target} missing for length={length}"
        assert str(cap) in user_content, f"cap {cap} missing for length={length}"


def test_build_prompt_includes_recent_endings():
    """When recent_endings is provided the user message contains an avoidance block."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    endings = [
        "She turned and did not look back.",
        "The question hung unanswered in the air.",
    ]
    messages = build_storylab_prompt(
        text="The door stood open.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
        recent_endings=endings,
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "Endings to avoid" in user_content
    assert endings[0] in user_content
    assert endings[1] in user_content


def test_build_prompt_no_endings_block_when_empty():
    """When recent_endings is empty or None the avoidance block is absent."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    for endings_arg in (None, []):
        messages = build_storylab_prompt(
            text="The fog rolled in from the harbour.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            recent_endings=endings_arg,
        )
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "Endings to avoid" not in user_content


def test_trim_to_cap_no_op_under_cap():
    """_trim_to_cap returns the original text unchanged when under the cap."""
    from app.services.storylab_generator import _trim_to_cap

    short_text = "The wind carried the scent of pine. It was cold but clear."
    wc = len(short_text.split())
    result = _trim_to_cap(short_text, wc + 50)
    assert result == short_text


def test_trim_to_cap_paragraph_boundary():
    """_trim_to_cap cuts at a paragraph boundary and stays within cap."""
    from app.services.storylab_generator import _trim_to_cap

    # Three paragraphs of 200 words each = 600 words total
    para = " ".join(["word"] * 200)
    text = f"{para}\n\n{para}\n\n{para}"
    cap = 450  # fits exactly two paragraphs (400 words) but not three

    result = _trim_to_cap(text, cap)
    assert len(result.split()) <= cap
    # Result should be at least one full paragraph
    assert len(result.split()) >= 100
    # No mid-word or mid-paragraph cut should leave partial paragraphs
    assert "\n\nword word" not in result or result.count("\n\n") <= 1


def test_trim_to_cap_sentence_boundary():
    """_trim_to_cap falls back to sentence-level cutting for a single long paragraph."""
    from app.services.storylab_generator import _trim_to_cap

    # Single paragraph: 10 sentences of ~60 words = ~600 words
    sentence = "The river bent sharply here and the banks were steep, overgrown with reeds that caught the current and held it before releasing it downstream with a soft persistent sound. "
    text = sentence * 10  # ~600 words, no paragraph breaks
    cap = 350

    result = _trim_to_cap(text, cap)
    assert len(result.split()) <= cap
    assert len(result) > 0
    # Result should end on sentence-ending punctuation
    assert result.rstrip()[-1] in ".!?\""


def test_extract_ending_phrase_single_line():
    """extract_ending_phrase returns the last non-empty line for short text."""
    from app.services.storylab_generator import extract_ending_phrase

    text = "First sentence here.\nSecond sentence here.\nShe closed the door."
    assert extract_ending_phrase(text) == "She closed the door."


def test_extract_ending_phrase_multiline():
    """extract_ending_phrase returns last non-empty line ignoring trailing whitespace."""
    from app.services.storylab_generator import extract_ending_phrase

    text = "Para one ends here.\n\nPara two ends with a question?"
    assert extract_ending_phrase(text) == "Para two ends with a question?"


def test_generate_passes_recent_endings_after_first_call(client):
    """After a first generation, the second call includes recent endings in the prompt."""
    from unittest.mock import patch
    import app.services.storylab_generator as gen

    story_id = "anti-rep-integration-story"
    base = {**_BASE_GENERATE, "story_id": story_id}

    # First call — creates a generation log entry for this story_id
    resp1 = client.post("/api/storylab/generate", json=base)
    assert resp1.status_code == 200

    # Second call — spy on generate_storylab_continuation via the route's own import binding
    captured: dict = {}
    orig = gen.generate_storylab_continuation

    def spy(text, controls, state_json, summary, characters, story_id="", recent_endings=None):
        captured["recent_endings"] = recent_endings
        return orig(text, controls, state_json, summary, characters, story_id, recent_endings)

    with patch("app.api.routes.storylab.generate_storylab_continuation", side_effect=spy):
        resp2 = client.post("/api/storylab/generate", json=base)

    assert resp2.status_code == 200
    assert captured.get("recent_endings") is not None, "recent_endings was not passed"
    assert len(captured["recent_endings"]) >= 1, "recent_endings should be non-empty after first call"
