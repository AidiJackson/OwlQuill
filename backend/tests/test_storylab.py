"""Tests for the StoryLab state + generate endpoints.

All StoryLab endpoints require authentication (launch security hardening —
enforced and covered by test_storylab_security.py). The autouse fixture below
gives every request in this module an authenticated baseline user; tests that
need a specific user (admin gating, per-user quotas) pass their own explicit
Authorization header, which always takes precedence.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _storylab_default_auth(request):
    """Authenticate this module's TestClient requests by default.

    The endpoint tests here predate mandatory auth; they exercise state,
    generation, chapters and quotas — not authentication itself. Requests that
    already carry an Authorization header are left untouched.
    """
    if "client" not in request.fixturenames:
        yield
        return
    client = request.getfixturevalue("client")
    default_hdrs = _sl_auth_headers(client)
    original_request = client.request

    def request_with_default_auth(method, url, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        for key, value in default_hdrs.items():
            headers.setdefault(key, value)
        return original_request(method, url, headers=headers, **kwargs)

    client.request = request_with_default_auth
    yield
    client.request = original_request

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
    """State json fields are translated into actionable prose hints in the user message.

    The prompt engine converts raw float values into craft-guidance prose
    (e.g. tension: 0.65 → "High tension — active threat…"). We test for the
    prose hint content, not the raw float, since that detail is intentionally
    abstracted away.
    """
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
    # Tension hint is present (prose form, not raw float)
    assert "tension" in user_content.lower()
    # Scene state section is present
    assert "Scene state" in user_content or "tension" in user_content.lower()


# ── cinematic prose layer tests ──────────────────────────────────────────────

def test_cinematic_layer_present_in_chapter_prompt():
    """CINEMATIC PROSE LAYER block appears in build_chapter_prompt user message."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls

    messages = build_chapter_prompt(
        prompt="The party has just started.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "CINEMATIC PROSE LAYER" in user_content


def test_cinematic_layer_ordering_in_chapter_prompt():
    """In chapter prompt: canon block precedes cinematic layer, cinematic layer precedes task."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls

    canon_memory = {
        "canon": {"hard_truths": ["Carter is alive."], "world_rules": [], "forbidden_contradictions": []},
        "characters": {},
        "relationships": [],
        "open_threads": [],
        "recent_events": [],
    }
    messages = build_chapter_prompt(
        prompt="Continue the scene.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
        canon_memory=canon_memory,
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    canon_pos = user_content.find("STORY CANON")
    cinematic_pos = user_content.find("CINEMATIC PROSE LAYER")
    task_pos = user_content.find("## Task")

    assert canon_pos != -1, "Canon block missing from chapter prompt"
    assert cinematic_pos != -1, "Cinematic layer missing from chapter prompt"
    assert task_pos != -1, "Task instruction missing from chapter prompt"
    assert canon_pos < cinematic_pos, "Canon block must precede cinematic layer"
    assert cinematic_pos < task_pos, "Cinematic layer must precede task instruction"


def test_cinematic_layer_present_in_storylab_prompt():
    """CINEMATIC PROSE LAYER block appears in build_storylab_prompt user message."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    messages = build_storylab_prompt(
        text="The rain fell outside.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "CINEMATIC PROSE LAYER" in user_content


def test_cinematic_layer_before_direction_in_storylab_prompt():
    """Cinematic layer appears before the direction instruction in build_storylab_prompt."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls, Direction

    messages = build_storylab_prompt(
        text="She waited by the window.",
        controls=StoryLabControls(direction=Direction.sad_moment),
        state_json={},
        summary="",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    cinematic_pos = user_content.find("CINEMATIC PROSE LAYER")
    direction_pos = user_content.find("## Direction:")

    assert cinematic_pos != -1, "Cinematic layer missing from storylab prompt"
    assert direction_pos != -1, "Direction section missing from storylab prompt"
    assert cinematic_pos < direction_pos, "Cinematic layer must precede direction instruction"


def test_canon_functions_unchanged():
    """Canon memory extraction and injection remain functional after cinematic layer addition."""
    from app.services.story_memory import build_canon_injection_block, extract_and_merge_memory

    assert callable(extract_and_merge_memory)

    memory = {
        "canon": {
            "hard_truths": ["The manor burned down in chapter 2."],
            "world_rules": [],
            "forbidden_contradictions": [],
        },
        "characters": {},
        "relationships": [],
        "open_threads": [],
        "recent_events": [],
    }
    block = build_canon_injection_block(memory)
    assert "STORY CANON" in block
    assert "manor burned down" in block


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
    """fade_to_black boundary + sensual_scene direction is allowed (for admins).

    Non-SFW boundaries are admin-only during launch (S24D FIX 3) — the gate
    itself is covered by test_generate_non_sfw_boundary_is_admin_only. This
    test promotes the baseline user so the boundary/direction combination and
    the stub's fade-to-black cue remain covered.
    """
    from tests.conftest import make_admin

    make_admin("sl-test@ficshon.com")
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


# ── S24D FIX 3: explicit text is admin-only ────────────────────────────────────

def test_generate_non_sfw_boundary_is_admin_only(client: TestClient):
    """Non-SFW boundaries (sensual/fade_to_black) are rejected for non-admins on
    /generate, while SFW still works. Admins are allowed. The gate runs before any
    generation, so the deny cases are provider-independent."""
    from tests.conftest import make_admin

    headers = _sl_auth_headers(client, email="fix3-user@ficshon.com", username="fix3user")
    sensual = {**_BASE_GENERATE, "story_id": "fix3-scratch", "controls": {
        "direction": "advance_plot", "tone_intensity": "moderate",
        "pacing": "balanced", "length": "medium", "boundary": "sensual",
    }}
    # non-admin + non-SFW → 403 explicit_admin_only
    resp = client.post("/api/storylab/generate", json=sensual, headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "explicit_admin_only"
    # non-admin + fade_to_black → also 403
    fade = {**sensual, "controls": {**sensual["controls"], "boundary": "fade_to_black"}}
    assert client.post("/api/storylab/generate", json=fade, headers=headers).status_code == 403
    # non-admin + SFW → still works (200)
    sfw = {**sensual, "controls": {**sensual["controls"], "boundary": "sfw"}}
    assert client.post("/api/storylab/generate", json=sfw, headers=headers).status_code == 200
    # admin + non-SFW → allowed (gate passes)
    admin_headers = _sl_auth_headers(client, email="fix3-admin@ficshon.com", username="fix3admin")
    make_admin("fix3-admin@ficshon.com")
    assert client.post("/api/storylab/generate", json=sensual, headers=admin_headers).status_code == 200


def test_rp_reply_inferno_heat_is_admin_only(client: TestClient):
    """Inferno RP-reply heat is admin-only; the gate runs before generation, so the
    deny case is provider-independent."""
    from tests.conftest import make_admin

    headers = _sl_auth_headers(client, email="fix3rp@ficshon.com", username="fix3rp")
    inferno = {"partner_reply": "She stepped closer.", "heat_level": "inferno"}
    # non-admin + inferno → 403 explicit_admin_only (before any generation)
    resp = client.post("/api/storylab/rp-reply/generate", json=inferno, headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "explicit_admin_only"
    # admin + inferno → gate passes (not 403)
    admin_headers = _sl_auth_headers(client, email="fix3rpadmin@ficshon.com", username="fix3rpadmin")
    make_admin("fix3rpadmin@ficshon.com")
    resp_admin = client.post("/api/storylab/rp-reply/generate", json=inferno, headers=admin_headers)
    assert resp_admin.status_code != 403, resp_admin.text


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
    # Suppress the word-count retry so this test stays focused on routing/payload shape
    monkeypatch.setattr(gen, "_minimum_words", lambda _length: 0)

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
    # Story path routes via the independent story-path model (S24B), not the
    # RP-reply default. _EFFECTIVE_STORY_MODEL is what the continuation must send.
    assert payload["model"] == gen._EFFECTIVE_STORY_MODEL
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
        (Length.short, (500, 600)),
        (Length.medium, (900, 1100)),
        (Length.long, (1500, 2000)),
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
    assert "Repetition dampening" in user_content  # section renamed from "Endings to avoid"
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
        # No recent endings → the endings sub-block must not appear
        assert "Do NOT end with the same opening" not in user_content


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

    # Non-legacy story ids now require an owned StoryModel row for the recent-
    # endings lookup (ownership isolation); the legacy "storylab:" prefix keeps
    # this test exercising the endings hand-off without registering a story.
    story_id = "storylab:anti-rep-integration-story"
    base = {**_BASE_GENERATE, "story_id": story_id}

    # First call — creates a generation log entry for this story_id
    resp1 = client.post("/api/storylab/generate", json=base)
    assert resp1.status_code == 200

    # Second call — spy on generate_storylab_continuation via the route's own import binding
    captured: dict = {}
    orig = gen.generate_storylab_continuation

    def spy(text, controls, state_json, summary, characters, story_id="", recent_endings=None, variant="default", **kwargs):
        captured["recent_endings"] = recent_endings
        return orig(text, controls, state_json, summary, characters, story_id, recent_endings, variant, **kwargs)

    with patch("app.api.routes.storylab.generate_storylab_continuation", side_effect=spy):
        resp2 = client.post("/api/storylab/generate", json=base)

    assert resp2.status_code == 200
    assert captured.get("recent_endings") is not None, "recent_endings was not passed"
    assert len(captured["recent_endings"]) >= 1, "recent_endings should be non-empty after first call"


# ── character voice + scene momentum tests ────────────────────────────────────

def test_build_prompt_contains_momentum_instruction():
    """User message always includes the scene momentum requirement block."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    for direction in ("advance_plot", "quiet_reflection", "add_dialogue"):
        controls = StoryLabControls(direction=direction)
        messages = build_storylab_prompt(
            text="The candle guttered in the draught.",
            controls=controls,
            state_json={},
            summary="",
            characters=[],
        )
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "momentum" in user_content.lower(), f"momentum block missing for direction={direction}"
        # Must name at least one of the required triggers
        triggers = ("emotional shift", "tension", "decision", "new information")
        assert any(t in user_content.lower() for t in triggers), (
            f"no momentum trigger found for direction={direction}"
        )


def test_build_prompt_contains_character_voice_block():
    """User message includes character voice guidance when characters have trait data."""
    from app.services.storylab_generator import build_storylab_prompt, build_character_voice_block
    from app.schemas.storylab import StoryLabControls

    characters = [
        {"name": "Alice", "personality": "analytical, guarded"},
        {"name": "Ben", "speech_style": "terse, blunt"},
        {"name": "Clara"},  # no trait data — still listed by name
    ]
    messages = build_storylab_prompt(
        text="They faced each other across the table.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=characters,
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "Alice" in user_content
    assert "Ben" in user_content
    assert "Clara" in user_content
    assert "analytical" in user_content or "Character voices" in user_content
    assert "terse" in user_content or "blunt" in user_content

    # build_character_voice_block returns empty string for empty/None input
    assert build_character_voice_block([]) == ""
    assert build_character_voice_block(None) == ""  # type: ignore[arg-type]

    # Voice block absent when no characters provided
    messages_no_chars = build_storylab_prompt(
        text="The room was silent.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    user_no_chars = next(m["content"] for m in messages_no_chars if m["role"] == "user")
    assert "Character voices" not in user_no_chars


# ── variant="alt" tests ───────────────────────────────────────────────────────

def test_generate_accepts_variant_alt(client: TestClient):
    """POST /generate with variant='alt' returns 200 and generated text."""
    resp = client.post("/api/storylab/generate", json={**_BASE_GENERATE, "variant": "alt"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["generated"]["text"]


def test_generate_default_variant_unchanged(client: TestClient):
    """POST /generate without variant field (default) still returns 200."""
    resp = client.post("/api/storylab/generate", json=_BASE_GENERATE)
    assert resp.status_code == 200


def test_build_prompt_variant_alt_includes_alternative_instruction():
    """build_storylab_prompt with variant='alt' adds distinct-take instruction to Task section."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    messages_alt = build_storylab_prompt(
        text="The door stood open.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
        variant="alt",
    )
    messages_default = build_storylab_prompt(
        text="The door stood open.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
        variant="default",
    )
    user_alt = next(m["content"] for m in messages_alt if m["role"] == "user")
    user_default = next(m["content"] for m in messages_default if m["role"] == "user")

    assert "alternative" in user_alt.lower() or "distinct" in user_alt.lower()
    # Default prompt must NOT contain the alt clause
    assert "alternative take" not in user_default.lower()
    # The two prompts differ
    assert user_alt != user_default


def test_openrouter_variant_alt_bumps_temperature(monkeypatch):
    """variant='alt' sends temperature=1.0 (0.85+0.15) to OpenRouter."""
    from unittest.mock import patch
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
    monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key-alt")

    model_output = "A different path unfolded through the mist."
    mock_client = _make_openrouter_mock(model_output)

    with patch.object(gen.httpx, "Client", return_value=mock_client):
        gen.generate_storylab_continuation(
            text="She reached for the handle.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            story_id="alt-temp-story",
            variant="alt",
        )

    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1]
    assert payload["temperature"] == pytest.approx(1.0, abs=1e-6)


def test_openrouter_default_variant_uses_base_temperature(monkeypatch):
    """variant='default' sends temperature=0.85 to OpenRouter."""
    from unittest.mock import patch
    import app.services.storylab_generator as gen
    from app.schemas.storylab import StoryLabControls

    monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
    monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key-default")

    mock_client = _make_openrouter_mock("The story continued as expected.")

    with patch.object(gen.httpx, "Client", return_value=mock_client):
        gen.generate_storylab_continuation(
            text="The candle burned low.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            story_id="default-temp-story",
            variant="default",
        )

    payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1]
    assert payload["temperature"] == pytest.approx(0.85, abs=1e-6)


# ── User Material Handling / beat-rendering prompt tests ──────────────────────

def test_prompt_contains_user_material_handling_section():
    """Prompt includes the User Material Handling section regardless of manuscript content."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    controls = StoryLabControls()
    messages = build_storylab_prompt(
        text="She looked out the window.",
        controls=controls,
        state_json={},
        summary="A quiet scene.",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    assert "User Material Handling" in user_content
    assert "canonical" in user_content.lower()
    assert "append" in user_content.lower() or "continuation" in user_content.lower()


def test_prompt_instructs_beat_rendering_for_bullet_manuscript():
    """When the manuscript contains bullet points, the prompt instructs the model
    to render them as polished prose and NOT repeat them verbatim."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    bullet_manuscript = (
        "The argument had been building for days.\n"
        "- Marcus slams the door and refuses to look at Elena\n"
        "- Elena tells him she knows about the letter\n"
        "* The silence stretches until Marcus finally speaks\n"
    )

    controls = StoryLabControls()
    messages = build_storylab_prompt(
        text=bullet_manuscript,
        controls=controls,
        state_json={},
        summary="Long-running tension between Marcus and Elena.",
        characters=[{"name": "Marcus"}, {"name": "Elena"}],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    # The section header is present
    assert "User Material Handling" in user_content

    # The prompt says beats must be rendered into prose
    assert "polished" in user_content.lower() or "prose" in user_content.lower()

    # The prompt explicitly forbids echoing bullets verbatim
    assert "verbatim" in user_content.lower()

    # The prompt explains what counts as a beat marker
    assert '"-"' in user_content or "bullet" in user_content.lower() or "beat" in user_content.lower()


def test_prompt_instructs_no_rewrite_of_existing_prose():
    """Prompt forbids rewriting or paraphrasing the user's existing text."""
    from app.services.storylab_generator import build_storylab_prompt
    from app.schemas.storylab import StoryLabControls

    controls = StoryLabControls()
    messages = build_storylab_prompt(
        text="The rain began at midnight and did not stop.",
        controls=controls,
        state_json={},
        summary="",
        characters=[],
    )
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    # Must not rewrite / paraphrase
    assert "rewrite" in user_content.lower() or "paraphrase" in user_content.lower()
    # Manuscript is described as canonical
    assert "canonical" in user_content.lower()


# ── chapter endpoint tests ────────────────────────────────────────────────────
# All tests use STORYLAB_PROVIDER=stub (set in conftest) so no live API calls.

_STORY_ID_CH = "ch-test-story-001"

_CH_GENERATE_BODY = {
    "prompt": "She finally confronts Marcus about the letter.",
    "mode": "roleplay",
    "controls": {
        "direction": "argument_begins",
        "tone_intensity": "moderate",
        "pacing": "balanced",
        "length": "medium",
        "boundary": "sfw",
    },
}


def _sl_auth_headers(client, email: str = "sl-test@ficshon.com", username: str = "sltestuser") -> dict:
    """Register a test user (if needed) and return Bearer auth headers.

    The account is given a character, because StoryLab is a creator workspace:
    ``require_creator`` derives the entitlement from character ownership, so a
    bare account gets a correct 403 and never reaches the behaviour these tests
    are about. No test in this module asserts the Wanderer 403 — the 403
    assertions here are all about the admin-only boundary and heat gates, which
    sit *behind* the creator gate and were previously unreachable.
    """
    from tests.conftest import ensure_character

    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass123"},
    )
    resp = client.post(
        "/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    token = resp.json()["access_token"]
    ensure_character(client, token)
    return {"Authorization": f"Bearer {token}"}


def test_chapter_list_empty(client):
    """GET /chapters returns empty list for a story with no chapters."""
    resp = client.get(f"/api/storylab/chapters?story_id={_STORY_ID_CH}_empty")
    assert resp.status_code == 200
    assert resp.json() == []


def test_chapter_generate_returns_200(client):
    """POST /chapters/generate returns 200 with required fields."""
    headers = _sl_auth_headers(client)
    resp = client.post(
        f"/api/storylab/chapters/generate?story_id={_STORY_ID_CH}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "chapter_number" in data
    assert data["chapter_number"] == 1
    assert isinstance(data["generated_text"], str) and len(data["generated_text"]) > 0
    assert isinstance(data["suggestions"], list) and len(data["suggestions"]) >= 1
    assert "prompt_text" in data
    assert "meta" in data


def test_chapter_generate_increments_number(client):
    """Second generation creates chapter 2."""
    headers = _sl_auth_headers(client)
    story_id = f"{_STORY_ID_CH}_increment"
    resp1 = client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    assert resp1.status_code == 200
    assert resp1.json()["chapter_number"] == 1

    resp2 = client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["chapter_number"] == 2


def test_chapter_list_shows_generated(client):
    """GET /chapters lists stored chapters after generation."""
    headers = _sl_auth_headers(client)
    story_id = f"{_STORY_ID_CH}_list"
    client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    resp = client.get(f"/api/storylab/chapters?story_id={story_id}")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    ch = items[0]
    assert ch["chapter_number"] == 1
    assert ch["words"] > 0
    assert ch["mode"] == "roleplay"
    assert ch["boundary"] == "sfw"


def test_chapter_get_returns_detail(client):
    """GET /chapters/{n} returns chapter detail with prompt_text and suggestions."""
    headers = _sl_auth_headers(client)
    story_id = f"{_STORY_ID_CH}_get"
    gen_resp = client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    assert gen_resp.status_code == 200

    resp = client.get(f"/api/storylab/chapters/1?story_id={story_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chapter_number"] == 1
    assert isinstance(data["generated_text"], str) and len(data["generated_text"]) > 0
    assert data["prompt_text"] == _CH_GENERATE_BODY["prompt"]
    assert isinstance(data["suggestions"], list)


def test_chapter_get_404_on_missing(client):
    """GET /chapters/{n} returns 404 when chapter does not exist."""
    resp = client.get(f"/api/storylab/chapters/99?story_id={_STORY_ID_CH}_missing")
    assert resp.status_code == 404


def test_chapter_delete_removes_from_list(client):
    """DELETE /chapters/{n} removes the chapter and returns 204."""
    headers = _sl_auth_headers(client)
    story_id = f"{_STORY_ID_CH}_delete"
    client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    del_resp = client.delete(f"/api/storylab/chapters/1?story_id={story_id}")
    assert del_resp.status_code == 204

    list_resp = client.get(f"/api/storylab/chapters?story_id={story_id}")
    assert list_resp.json() == []


def test_chapter_delete_404_on_missing(client):
    """DELETE /chapters/{n} returns 404 when chapter does not exist."""
    resp = client.delete(f"/api/storylab/chapters/42?story_id={_STORY_ID_CH}_nomatch")
    assert resp.status_code == 404


def test_chapter_regenerate_overwrites_text(client):
    """POST /chapters/{n}/regenerate replaces the chapter text in-place."""
    headers = _sl_auth_headers(client)
    story_id = f"{_STORY_ID_CH}_regen"
    gen_resp = client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    original_text = gen_resp.json()["generated_text"]

    regen_body = {**_CH_GENERATE_BODY, "prompt": "A revised opening beat."}
    regen_resp = client.post(
        f"/api/storylab/chapters/1/regenerate?story_id={story_id}",
        json=regen_body,
        headers=headers,
    )
    assert regen_resp.status_code == 200
    data = regen_resp.json()
    assert data["chapter_number"] == 1
    assert isinstance(data["generated_text"], str)

    # Chapter list still has exactly 1 chapter (not 2)
    list_resp = client.get(f"/api/storylab/chapters?story_id={story_id}")
    assert len(list_resp.json()) == 1


def test_chapter_build_prompt_structure(client):
    """build_chapter_prompt returns [system, user] messages with required blocks."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls

    controls = StoryLabControls()
    messages = build_chapter_prompt(
        prompt="She opens the letter.",
        controls=controls,
        state_json={},
        summary="A slow-burn mystery.",
        characters=[],
    )
    assert len(messages) == 2
    system = messages[0]["content"]
    user = messages[1]["content"]

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    # System prompt contains chapter output contract markers
    assert "<STORY>" in system
    assert "<SUGGESTIONS>" in system
    assert "<DELTA_SIGNALS>" in system

    # User message contains key blocks
    # Note: the character-first redesign replaced ## Story context with
    # ## Story so far + protagonist anchor blocks. Check the summary section.
    assert "Story so far" in user or "STORY CONTEXT" in user
    assert "User guidance for this chapter" in user
    assert "She opens the letter." in user
    assert "Character Fidelity" in user


def test_chapter_generate_stub_returns_suggestions(client):
    """Stub provider generates valid text and at least 1 suggestion."""
    headers = _sl_auth_headers(client)
    story_id = f"{_STORY_ID_CH}_stub_sugg"
    resp = client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json=_CH_GENERATE_BODY,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["suggestions"], list)
    assert len(data["suggestions"]) >= 1
    assert all(isinstance(s, str) and len(s) > 0 for s in data["suggestions"])


def test_fallback_suggestions_returns_list():
    """_fallback_suggestions always returns a non-empty list."""
    from app.services.storylab_generator import _fallback_suggestions

    # Default empty state
    result = _fallback_suggestions({})
    assert isinstance(result, list) and len(result) >= 1

    # High tension state
    result = _fallback_suggestions({"story_state": {"tension": 0.8, "emotional_weight": 0.7, "stakes": 0.8}})
    assert len(result) >= 1


def test_parse_suggestions_valid():
    """_parse_suggestions extracts JSON array from <SUGGESTIONS> block."""
    from app.services.storylab_generator import _parse_suggestions

    raw = '<SUGGESTIONS>["First suggestion.", "Second suggestion.", "Third."]</SUGGESTIONS>'
    result = _parse_suggestions(raw)
    assert result == ["First suggestion.", "Second suggestion.", "Third."]


def test_parse_suggestions_missing_returns_none():
    """_parse_suggestions returns None when block is absent."""
    from app.services.storylab_generator import _parse_suggestions
    assert _parse_suggestions("no suggestions here") is None


def test_parse_suggestions_bad_json_returns_none():
    """_parse_suggestions returns None on malformed JSON."""
    from app.services.storylab_generator import _parse_suggestions
    assert _parse_suggestions("<SUGGESTIONS>not json[</SUGGESTIONS>") is None


# ── story memory window tests ──────────────────────────────────────────────────
# These tests verify STORY SO FAR + LAST CHAPTER injection in build_chapter_prompt
# and the generate_story_summary pipeline.

def _make_chapter_messages(summary="", prev_text=None):
    """Helper: build chapter prompt messages with given summary and previous chapter."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls
    return build_chapter_prompt(
        prompt="She opens the letter.",
        controls=StoryLabControls(),
        state_json={},
        summary=summary,
        characters=[],
        previous_chapter_text=prev_text,
    )


def test_chapter_prompt_story_so_far_present_when_summary_set():
    """STORY SO FAR block is injected when a non-empty summary is provided."""
    summary = "Marcus and Elena have a fraught history rooted in a shared loss."
    msgs = _make_chapter_messages(summary=summary)
    user = msgs[1]["content"]
    assert "## Story so far" in user
    assert summary in user


def test_chapter_prompt_story_so_far_absent_when_empty():
    """STORY SO FAR block is absent when summary is empty or None."""
    for s in ("", None, "   "):
        msgs = _make_chapter_messages(summary=s or "")
        user = msgs[1]["content"]
        assert "## Story so far" not in user, f"Expected STORY SO FAR to be absent for summary={s!r}"


def test_chapter_prompt_last_chapter_present_when_provided():
    """LAST CHAPTER block is injected when previous chapter text is provided."""
    prev = "The rain began at midnight and did not stop."
    msgs = _make_chapter_messages(prev_text=prev)
    user = msgs[1]["content"]
    assert "## Last chapter" in user
    assert prev in user


def test_chapter_prompt_last_chapter_absent_when_none():
    """LAST CHAPTER block is absent when no previous chapter text is given."""
    msgs = _make_chapter_messages(prev_text=None)
    user = msgs[1]["content"]
    assert "## Last chapter" not in user

    # Also check empty string
    msgs2 = _make_chapter_messages(prev_text="")
    assert "## Last chapter" not in msgs2[1]["content"]


def test_chapter_prompt_last_chapter_full_text_not_truncated():
    """Full previous-chapter text is included verbatim (no 2 000-char truncation)."""
    long_text = "word " * 600  # ~3 000 chars, well above former 2 000-char limit
    msgs = _make_chapter_messages(prev_text=long_text)
    user = msgs[1]["content"]
    assert long_text.strip() in user


def test_chapter_prompt_both_blocks_correct_order():
    """STORY SO FAR appears before LAST CHAPTER in the user message."""
    summary = "A brewing conflict between old friends."
    prev = "She slammed the door. The silence after was worse."
    msgs = _make_chapter_messages(summary=summary, prev_text=prev)
    user = msgs[1]["content"]
    pos_summary = user.find("## Story so far")
    pos_last = user.find("## Last chapter")
    assert pos_summary != -1 and pos_last != -1
    assert pos_summary < pos_last


def test_build_story_summary_prompt_structure():
    """build_story_summary_prompt returns [system, user] with chapter text in user block."""
    from app.services.storylab_generator import build_story_summary_prompt

    msgs = build_story_summary_prompt(
        existing_summary="She has been hiding something for years.",
        new_chapter_text="Marcus finally saw the letter she had concealed.",
        chapter_number=3,
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "Marcus finally saw the letter" in user
    assert "## Chapter 3" in user
    assert "She has been hiding something" in user


def test_build_story_summary_prompt_first_chapter_no_prior():
    """When existing_summary is empty, user message notes no prior summary exists."""
    from app.services.storylab_generator import build_story_summary_prompt

    msgs = build_story_summary_prompt(
        existing_summary="",
        new_chapter_text="The story begins here.",
        chapter_number=1,
    )
    user = msgs[1]["content"]
    assert "first chapter" in user.lower() or "no prior summary" in user.lower()


def test_generate_story_summary_stub_returns_nonempty_string():
    """generate_story_summary (stub path) returns a non-empty string."""
    from app.services.storylab_generator import generate_story_summary

    result = generate_story_summary(
        existing_summary="",
        chapter_text="She opened the letter at last.",
        chapter_number=1,
        story_id="summary-stub-test",
    )
    assert isinstance(result, str) and len(result) > 50


def test_generate_story_summary_stub_includes_chapter_number():
    """Stub summary references the chapter number."""
    from app.services.storylab_generator import generate_story_summary

    result = generate_story_summary(
        existing_summary="Some prior context.",
        chapter_text="The confrontation arrived.",
        chapter_number=4,
        story_id="summary-chapter-num-test",
    )
    assert "4" in result


def test_chapter_generate_persists_story_summary(client, db_session):
    """After generating a chapter, the StoryState row has a non-empty story_summary."""
    from app.models.storylab import StoryState

    headers = _sl_auth_headers(client)
    story_id = "summary-persist-test-001"
    resp = client.post(
        f"/api/storylab/chapters/generate?story_id={story_id}",
        json={
            "prompt": "The letter changes everything.",
            "mode": "roleplay",
            "controls": {
                "direction": "twist_event",
                "tone_intensity": "intense",
                "pacing": "fast",
                "length": "short",
                "boundary": "sfw",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200

    # Verify the state row now has a story_summary (use the test db_session fixture)
    db_session.expire_all()  # refresh cached objects
    state_row = db_session.query(StoryState).filter(StoryState.story_id == story_id).first()
    assert state_row is not None
    assert state_row.story_summary is not None
    assert len(state_row.story_summary) > 20


def test_chapter_generate_summary_used_in_next_prompt():
    """When story_summary is set on state_row, the second chapter's prompt includes it."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls

    summary = "Elena discovered Marcus was involved in the incident three years ago."
    prev_text = "She walked away without looking back."

    msgs = build_chapter_prompt(
        prompt="The confrontation the story has been building toward.",
        controls=StoryLabControls(),
        state_json={},
        summary=summary,
        characters=[],
        previous_chapter_text=prev_text,
    )
    user = msgs[1]["content"]

    # Both memory blocks present
    assert "## Story so far" in user
    assert summary in user
    assert "## Last chapter" in user
    assert prev_text in user


# ── character behaviour anchors ───────────────────────────────────────────────

def test_chapter_prompt_includes_behaviour_anchors_when_characters_present():
    """build_chapter_prompt injects ## Character behaviour anchors when characters carry anchor data."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls

    characters = [
        {
            "name": "Lord Ashford",
            "role": "lord",
            "status": "noble",
            "power_style": "cold authority",
            "emotional_pacing": "slow burn",
            "never": "beg or show weakness",
        },
        {
            "name": "Mira",
            "role": "maid",
            "pursuit_style": "quiet observation",
            "boundaries": "will not betray her mistress",
        },
    ]

    msgs = build_chapter_prompt(
        prompt="A tense confrontation in the library.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=characters,
    )
    user = msgs[1]["content"]

    # Lord Ashford is protagonist — routed through build_protagonist_anchor.
    # power_style ("cold authority") is not included in the protagonist block;
    # check for fields that ARE emitted: emotional_pacing, never, name.
    assert "Lord Ashford" in user
    assert "slow burn" in user          # emotional_pacing → protagonist anchor
    assert "Would never" in user or "would never" in user   # never → protagonist anchor
    assert "beg or show weakness" in user
    # Mira is a supporting character — routed through build_character_behaviour_anchors
    assert "Mira" in user
    assert "## Character behaviour anchors" in user


def test_chapter_prompt_omits_behaviour_anchors_when_no_characters():
    """build_chapter_prompt omits ## Character behaviour anchors when characters list is empty."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls

    msgs = build_chapter_prompt(
        prompt="A quiet morning.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    user = msgs[1]["content"]

    assert "## Character behaviour anchors" not in user


def test_behaviour_anchors_respects_hard_cap():
    """build_character_behaviour_anchors result never exceeds 1200 chars regardless of input size."""
    from app.services.storylab_generator import build_character_behaviour_anchors

    # Generate a large character list to stress the cap
    characters = [
        {
            "name": f"Character {i}",
            "role": "powerful commander with decades of experience in the northern campaigns",
            "status": "high nobility with military authority",
            "power_style": "iron-fisted control through fear and respect",
            "emotional_pacing": "volcanic — long fuse but catastrophic when triggered",
            "pursuit_style": "relentless, methodical, never leaves a loose end",
            "never": "show mercy to traitors; reveal personal weakness to subordinates",
        }
        for i in range(10)
    ]

    result = build_character_behaviour_anchors(characters)

    assert result != ""
    assert len(result) <= 1200


# ── outcome vs path ───────────────────────────────────────────────────────────

def test_chapter_prompt_contains_outcome_vs_path_block():
    """build_chapter_prompt always includes ## Outcome vs Path rules."""
    from app.services.storylab_generator import build_chapter_prompt
    from app.schemas.storylab import StoryLabControls

    msgs = build_chapter_prompt(
        prompt="A heated argument breaks out.",
        controls=StoryLabControls(),
        state_json={},
        summary="",
        characters=[],
    )
    user = msgs[1]["content"]

    assert "## Outcome vs Path" in user
    assert "MAXIMUM" in user or "maximum" in user.lower()
    assert "not a required outcome" in user or "not a requirement" in user


# ── quota tests (JWT-derived user_id) ────────────────────────────────────────

def test_chapter_generate_quota_exceeded_returns_429(client):
    """When daily limit is reached, generating another chapter returns 429."""
    from unittest.mock import patch
    from app.core.config import settings as app_settings

    headers = _sl_auth_headers(client)
    story_id = "quota-test-story-001"

    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 2):
        resp = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers,
        )
    assert resp.status_code == 200

    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 2):
        resp = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers,
        )
    assert resp.status_code == 200

    # Third generation is blocked (used = 2, limit = 2)
    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 2):
        resp = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers,
        )
    assert resp.status_code == 429


def test_chapter_generate_quota_429_payload_shape(client):
    """429 quota_exceeded response has required fields."""
    from unittest.mock import patch
    from app.core.config import settings as app_settings

    headers = _sl_auth_headers(client)
    story_id = "quota-shape-story-001"

    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 1):
        client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers,
        )

    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 1):
        resp = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers,
        )

    assert resp.status_code == 429
    d = resp.json()["detail"]
    assert d["error"] == "quota_exceeded"
    assert "detail" in d
    assert "hint" in d
    assert isinstance(d["reset_in_seconds"], int)
    assert d["reset_in_seconds"] >= 0
    assert d["limit"] == 1
    assert d["used"] == 1


def test_chapter_generate_quota_zero_means_unlimited(client):
    """STORYLAB_DAILY_LIMIT=0 disables quota enforcement entirely."""
    from unittest.mock import patch
    from app.core.config import settings as app_settings

    headers = _sl_auth_headers(client)
    story_id = "quota-unlimited-story-001"

    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 0):
        for _ in range(3):
            resp = client.post(
                f"/api/storylab/chapters/generate?story_id={story_id}",
                json=_CH_GENERATE_BODY,
                headers=headers,
            )
            assert resp.status_code == 200


def test_chapter_generate_quota_is_per_user(client):
    """Quota is tracked per JWT user — two users have independent limits."""
    from unittest.mock import patch
    from app.core.config import settings as app_settings

    story_id = "quota-per-user-story"
    headers_a = _sl_auth_headers(client, email="quota-user-a@ficshon.com", username="quotausera")
    headers_b = _sl_auth_headers(client, email="quota-user-b@ficshon.com", username="quotauserb")

    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 1):
        # Exhaust quota for user A
        client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers_a,
        )
        # User B should still be allowed (different JWT → different user_id)
        resp = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers_b,
        )
    assert resp.status_code == 200


def test_regenerate_not_blocked_by_quota(client):
    """Regenerate overwrites an existing row; it must NOT count against the daily quota."""
    from unittest.mock import patch
    from app.core.config import settings as app_settings

    headers = _sl_auth_headers(client)
    story_id = "quota-regen-story-001"

    # Generate one chapter (uses 1 of 1 allowed)
    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 1):
        gen_resp = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers,
        )
    assert gen_resp.status_code == 200
    chapter_number = gen_resp.json()["chapter_number"]

    # Regenerate must succeed — it rewrites an existing row, no new quota slot consumed.
    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 1):
        resp = client.post(
            f"/api/storylab/chapters/{chapter_number}/regenerate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers,
        )
    assert resp.status_code == 200, resp.text


def test_user_id_param_ignored_or_rejected(client):
    """?user_id query param is silently ignored; quota is derived from the JWT sub."""
    from unittest.mock import patch
    from app.core.config import settings as app_settings

    story_id = "spoof-test-story-001"
    headers_a = _sl_auth_headers(client, email="spoof-a@ficshon.com", username="spoofa")

    # User A generates with a fake ?user_id — the param is unknown and ignored.
    # The endpoint should succeed (no 422), and user A's own quota slot is consumed.
    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 1):
        resp = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}&user_id=99999",
            json=_CH_GENERATE_BODY,
            headers=headers_a,
        )
    assert resp.status_code == 200  # param is ignored, not rejected

    # User A's quota is now exhausted (tracked by their real JWT id, not 99999)
    with patch.object(app_settings, "STORYLAB_DAILY_LIMIT", 1):
        resp2 = client.post(
            f"/api/storylab/chapters/generate?story_id={story_id}",
            json=_CH_GENERATE_BODY,
            headers=headers_a,
        )
    assert resp2.status_code == 429  # user A is blocked, not the fake user 99999


# ── Story Canon / Memory Engine tests ────────────────────────────────────────

class TestSeedMemoryFromStoryCreation:
    """seed_memory_from_story_creation populates hard_truths and characters."""

    def test_seed_produces_hard_truth_for_each_character(self):
        from app.services.story_memory import seed_memory_from_story_creation

        memory = seed_memory_from_story_creation(
            title="Bloodlines",
            genre="urban_fantasy",
            premise="A demon hunter discovers her bloodline is cursed.",
            characters=[
                {"name": "Angelo Baptiste", "role": "mentor"},
                {"name": "Leonardo", "role": "protagonist"},
            ],
        )
        truths = memory["canon"]["hard_truths"]
        names_in_truths = " ".join(truths).lower()
        assert "angelo baptiste" in names_in_truths
        assert "leonardo" in names_in_truths
        assert any("alive" in t.lower() for t in truths if "angelo" in t.lower())

    def test_seed_creates_forbidden_contradiction_per_character(self):
        from app.services.story_memory import seed_memory_from_story_creation

        memory = seed_memory_from_story_creation(
            characters=[{"name": "Angelo Baptiste", "role": "patriarch"}],
        )
        forbidden = memory["canon"]["forbidden_contradictions"]
        assert any("Angelo Baptiste" in f for f in forbidden)

    def test_seed_stores_character_in_characters_dict(self):
        from app.services.story_memory import seed_memory_from_story_creation

        memory = seed_memory_from_story_creation(
            characters=[
                {
                    "name": "Leonardo",
                    "role": "protagonist",
                    "traits": ["Echo-like effect", "supernatural magnet"],
                }
            ],
        )
        assert "Leonardo" in memory["characters"]
        char = memory["characters"]["Leonardo"]
        assert "Echo-like effect" in char.get("abilities_or_traits", [])

    def test_seed_premise_added_to_hard_truths(self):
        from app.services.story_memory import seed_memory_from_story_creation

        memory = seed_memory_from_story_creation(premise="Angelo is the Demon Wolf.")
        assert any("Angelo is the Demon Wolf" in t for t in memory["canon"]["hard_truths"])

    def test_empty_seed_returns_valid_empty_schema(self):
        from app.services.story_memory import seed_memory_from_story_creation

        memory = seed_memory_from_story_creation()
        assert "canon" in memory
        assert "characters" in memory
        assert "relationships" in memory
        assert "open_threads" in memory
        assert "recent_events" in memory


class TestBuildCanonInjectionBlock:
    """build_canon_injection_block formats the memory into an injectable string."""

    def test_empty_memory_returns_empty_string(self):
        from app.services.story_memory import build_canon_injection_block

        assert build_canon_injection_block({}) == ""
        assert build_canon_injection_block({"canon": {"hard_truths": [], "world_rules": [], "forbidden_contradictions": []}, "characters": {}, "relationships": [], "open_threads": [], "recent_events": []}) == ""

    def test_block_includes_hard_truths(self):
        from app.services.story_memory import build_canon_injection_block

        memory = {
            "canon": {
                "hard_truths": ["Angelo Baptiste is alive."],
                "world_rules": [],
                "forbidden_contradictions": [],
            },
            "characters": {},
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }
        block = build_canon_injection_block(memory)
        assert "Angelo Baptiste is alive." in block
        assert "STORY CANON" in block

    def test_block_includes_forbidden_contradictions(self):
        from app.services.story_memory import build_canon_injection_block

        memory = {
            "canon": {
                "hard_truths": [],
                "world_rules": [],
                "forbidden_contradictions": ["Do not kill Angelo Baptiste"],
            },
            "characters": {},
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }
        block = build_canon_injection_block(memory)
        assert "Do not kill Angelo Baptiste" in block
        assert "FORBIDDEN" in block.upper()

    def test_block_includes_character_memory(self):
        from app.services.story_memory import build_canon_injection_block

        memory = {
            "canon": {"hard_truths": ["X"], "world_rules": [], "forbidden_contradictions": []},
            "characters": {
                "Leonardo": {
                    "identity": ["Role: protagonist"],
                    "current_status": ["alive"],
                    "abilities_or_traits": ["Echo-like supernatural effect"],
                    "goals": [],
                    "growth": [],
                    "secrets": [],
                }
            },
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }
        block = build_canon_injection_block(memory)
        assert "Leonardo" in block
        assert "Echo-like supernatural effect" in block

    def test_block_includes_anti_drift_constraints(self):
        from app.services.story_memory import build_canon_injection_block

        memory = {
            "canon": {"hard_truths": ["Foo is alive."], "world_rules": [], "forbidden_contradictions": []},
            "characters": {},
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }
        block = build_canon_injection_block(memory)
        assert "ANTI-DRIFT" in block or "anti-drift" in block.lower()
        assert "generic tropes" in block.lower()

    def test_block_includes_open_threads(self):
        from app.services.story_memory import build_canon_injection_block

        memory = {
            "canon": {"hard_truths": [], "world_rules": [], "forbidden_contradictions": []},
            "characters": {},
            "relationships": [],
            "open_threads": ["Why is Angelo hiding his identity?"],
            "recent_events": [],
        }
        block = build_canon_injection_block(memory)
        assert "Why is Angelo hiding his identity?" in block


class TestCheckForContradictions:
    """check_for_contradictions detects hard truth violations and mechanic drift."""

    def _make_memory(self, hard_truths=None, characters=None):
        return {
            "canon": {
                "hard_truths": hard_truths or [],
                "world_rules": [],
                "forbidden_contradictions": [],
            },
            "characters": characters or {},
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }

    def test_no_contradiction_on_clean_text(self):
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory(hard_truths=["Angelo Baptiste is alive."])
        text = "Angelo Baptiste walked into the room and greeted Leonardo."
        assert check_for_contradictions(text, memory) == []

    def test_detects_death_contradiction(self):
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory(hard_truths=["Angelo Baptiste is alive at story start."])
        text = "angelo baptiste died in the courtyard as leonardo watched helplessly."
        results = check_for_contradictions(text, memory)
        assert len(results) >= 1
        assert any("angelo baptiste" in r.lower() for r in results)

    def test_detects_dead_contradiction(self):
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory(hard_truths=["Angelo Baptiste is alive."])
        text = "It was clear that angelo baptiste is dead and gone forever."
        results = check_for_contradictions(text, memory)
        assert len(results) >= 1

    def test_detects_mechanic_drift(self):
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory(
            characters={
                "Leonardo": {
                    "identity": [],
                    "current_status": ["alive"],
                    "abilities_or_traits": ["Echo-like supernatural effect on nearby beings"],
                    "goals": [],
                    "growth": [],
                    "secrets": [],
                }
            }
        )
        text = "leonardo transformed into a werewolf under the full moon."
        results = check_for_contradictions(text, memory)
        assert len(results) >= 1
        assert any("mechanic drift" in r.lower() or "echo" in r.lower() for r in results)

    def test_empty_text_returns_no_contradictions(self):
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory(hard_truths=["Angelo is alive."])
        assert check_for_contradictions("", memory) == []
        assert check_for_contradictions("", {}) == []


class TestExtractAndMergeMemory:
    """extract_and_merge_memory preserves existing facts and merges new ones."""

    def _base_memory(self):
        from app.services.story_memory import seed_memory_from_story_creation
        return seed_memory_from_story_creation(
            characters=[
                {"name": "Angelo Baptiste", "role": "patriarch"},
                {"name": "Leonardo", "role": "protagonist"},
            ],
            premise="Angelo is the Demon Wolf.",
        )

    def test_existing_hard_truths_preserved_after_extract(self):
        from app.services.story_memory import extract_and_merge_memory

        existing = self._base_memory()
        original_truths = list(existing["canon"]["hard_truths"])

        updated = extract_and_merge_memory(
            existing_memory=existing,
            chapter_text="A chapter passes. Nothing changes.",
            chapter_number=2,
            story_id="test-preserve-001",
        )

        # All original truths must survive the merge
        for truth in original_truths:
            assert truth in updated["canon"]["hard_truths"], (
                f"Hard truth lost after merge: {truth!r}"
            )

    def test_existing_characters_preserved_after_extract(self):
        from app.services.story_memory import extract_and_merge_memory

        existing = self._base_memory()

        updated = extract_and_merge_memory(
            existing_memory=existing,
            chapter_text="Leonardo spoke briefly then left.",
            chapter_number=3,
            story_id="test-preserve-002",
        )

        assert "Angelo Baptiste" in updated["characters"]
        assert "Leonardo" in updated["characters"]

    def test_merge_does_not_drop_forbidden_contradictions(self):
        from app.services.story_memory import extract_and_merge_memory

        existing = self._base_memory()
        forbidden_before = list(existing["canon"]["forbidden_contradictions"])

        updated = extract_and_merge_memory(
            existing_memory=existing,
            chapter_text="A routine chapter with no major events.",
            chapter_number=2,
            story_id="test-forbidden-001",
        )

        for item in forbidden_before:
            assert item in updated["canon"]["forbidden_contradictions"], (
                f"Forbidden contradiction lost: {item!r}"
            )

    def test_merge_accepts_new_hard_truth_from_updates(self):
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty

        memory = _deep_copy_empty()
        memory["canon"]["hard_truths"].append("Angelo is alive.")

        updates = {
            "new_hard_truths": ["Leonardo cannot be possessed by demons."],
            "new_world_rules": [],
            "character_updates": {},
            "relationship_updates": [],
            "new_open_threads": [],
            "recent_events": [],
        }
        _apply_memory_updates(memory, updates)

        assert "Angelo is alive." in memory["canon"]["hard_truths"]
        assert "Leonardo cannot be possessed by demons." in memory["canon"]["hard_truths"]

    def test_merge_does_not_duplicate_hard_truths(self):
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty

        memory = _deep_copy_empty()
        memory["canon"]["hard_truths"].append("Angelo is alive.")

        updates = {"new_hard_truths": ["Angelo is alive."], "new_world_rules": [], "character_updates": {}, "relationship_updates": [], "new_open_threads": [], "recent_events": []}
        _apply_memory_updates(memory, updates)

        assert memory["canon"]["hard_truths"].count("Angelo is alive.") == 1

    def test_merge_upserts_relationship(self):
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty

        memory = _deep_copy_empty()
        memory["relationships"].append({
            "a": "Angelo Baptiste",
            "b": "Leonardo",
            "status": "family",
            "tension": "low",
            "recent_change": "",
        })

        updates = {
            "new_hard_truths": [],
            "new_world_rules": [],
            "character_updates": {},
            "relationship_updates": [
                {
                    "a": "Angelo Baptiste",
                    "b": "Leonardo",
                    "status": "family",
                    "tension": "high",
                    "recent_change": "Angelo revealed his demon nature",
                }
            ],
            "new_open_threads": [],
            "recent_events": [],
        }
        _apply_memory_updates(memory, updates)

        # Should update, not duplicate
        rels = memory["relationships"]
        assert len(rels) == 1
        assert rels[0]["tension"] == "high"
        assert "Angelo revealed" in rels[0]["recent_change"]

    def test_open_threads_capped_at_10(self):
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty

        memory = _deep_copy_empty()
        memory["open_threads"] = [f"Thread {i}" for i in range(9)]

        updates = {
            "new_hard_truths": [],
            "new_world_rules": [],
            "character_updates": {},
            "relationship_updates": [],
            "new_open_threads": ["New thread A", "New thread B"],
            "recent_events": [],
        }
        _apply_memory_updates(memory, updates)

        assert len(memory["open_threads"]) <= 10


class TestCanonInjectedIntoChapterPrompt:
    """Canon memory block is injected into build_chapter_prompt output."""

    def test_canon_block_appears_in_chapter_prompt_when_memory_present(self):
        from app.services.storylab_generator import build_chapter_prompt
        from app.schemas.storylab import StoryLabControls

        memory = {
            "canon": {
                "hard_truths": ["Angelo Baptiste is alive."],
                "world_rules": [],
                "forbidden_contradictions": ["Do not kill Angelo Baptiste."],
            },
            "characters": {
                "Leonardo": {
                    "identity": [],
                    "current_status": ["alive"],
                    "abilities_or_traits": ["Echo-like supernatural effect"],
                    "goals": [],
                    "growth": [],
                    "secrets": [],
                }
            },
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }

        msgs = build_chapter_prompt(
            prompt="Continue the story.",
            controls=StoryLabControls(),
            state_json={},
            summary="Angelo and Leonardo are at odds.",
            characters=[],
            canon_memory=memory,
        )
        user_content = msgs[1]["content"]

        assert "Angelo Baptiste is alive." in user_content
        assert "Echo-like supernatural effect" in user_content
        assert "STORY CANON" in user_content

    def test_canon_block_absent_when_no_memory(self):
        from app.services.storylab_generator import build_chapter_prompt
        from app.schemas.storylab import StoryLabControls

        msgs = build_chapter_prompt(
            prompt="Begin.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            canon_memory=None,
        )
        user_content = msgs[1]["content"]
        assert "STORY CANON" not in user_content

    def test_canon_block_appears_in_continuation_prompt(self):
        from app.services.storylab_generator import build_storylab_prompt
        from app.schemas.storylab import StoryLabControls

        memory = {
            "canon": {
                "hard_truths": ["Leonardo has an Echo-like effect on supernatural beings."],
                "world_rules": [],
                "forbidden_contradictions": [],
            },
            "characters": {},
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }

        msgs = build_storylab_prompt(
            text="The night felt different.",
            controls=StoryLabControls(),
            state_json={},
            summary="",
            characters=[],
            canon_memory=memory,
        )
        user_content = msgs[1]["content"]
        assert "Echo-like effect on supernatural beings" in user_content


class TestHardTruthsPersistAcrossChapterGeneration:
    """Hard truths survive multi-chapter extraction/merge cycles."""

    def test_hard_truths_survive_three_extract_merge_cycles(self):
        """Simulate 3 chapter extractions and confirm original hard_truths persist."""
        from app.services.story_memory import seed_memory_from_story_creation, extract_and_merge_memory

        memory = seed_memory_from_story_creation(
            characters=[
                {"name": "Angelo Baptiste", "role": "patriarch"},
                {"name": "Leonardo", "role": "protagonist"},
            ],
            premise="Angelo Baptiste is the Demon Wolf and is alive.",
        )
        original_truths = set(memory["canon"]["hard_truths"])

        # Simulate 3 stub-mode chapter extraction cycles
        for chapter_number in range(1, 4):
            memory = extract_and_merge_memory(
                existing_memory=memory,
                chapter_text=f"Chapter {chapter_number}: events unfold between Angelo and Leonardo.",
                chapter_number=chapter_number,
                story_id="multi-cycle-test",
            )

        # All original hard truths must survive
        for truth in original_truths:
            assert truth in memory["canon"]["hard_truths"], (
                f"Hard truth lost after 3 extraction cycles: {truth!r}"
            )

    def test_character_memory_survives_multiple_cycles(self):
        """Character facts from seeding must still exist after several merge cycles."""
        from app.services.story_memory import seed_memory_from_story_creation, extract_and_merge_memory

        memory = seed_memory_from_story_creation(
            characters=[
                {
                    "name": "Leonardo",
                    "traits": ["Echo-like supernatural effect", "demon magnet"],
                }
            ],
        )

        for i in range(3):
            memory = extract_and_merge_memory(
                existing_memory=memory,
                chapter_text=f"Chapter {i + 1}: Leonardo navigates the supernatural world.",
                chapter_number=i + 1,
                story_id="char-cycle-test",
            )

        assert "Leonardo" in memory["characters"]
        traits = memory["characters"]["Leonardo"].get("abilities_or_traits", [])
        assert "Echo-like supernatural effect" in traits

    def test_memory_schema_always_valid_after_merge(self):
        """extract_and_merge_memory always returns a dict with required top-level keys."""
        from app.services.story_memory import extract_and_merge_memory

        memory = extract_and_merge_memory(
            existing_memory={},
            chapter_text="A chapter with no meaningful events.",
            chapter_number=1,
            story_id="schema-check",
        )
        assert isinstance(memory, dict)
        assert "canon" in memory
        assert "characters" in memory
        assert "relationships" in memory
        assert "open_threads" in memory
        assert "recent_events" in memory
        assert isinstance(memory["canon"].get("hard_truths"), list)

    def test_default_state_includes_memory_key(self):
        """The _DEFAULT_STATE used for new StoryState rows includes the memory key."""
        from app.api.routes.storylab import _DEFAULT_STATE

        assert "memory" in _DEFAULT_STATE
        memory = _DEFAULT_STATE["memory"]
        assert "canon" in memory
        assert "characters" in memory
        assert isinstance(memory["canon"].get("hard_truths"), list)
