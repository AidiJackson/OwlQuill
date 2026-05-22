"""Regression tests: StoryLab standard generation is isolated from RP orchestration systems.

Verifies:
1. Standard StoryLab prompts contain NO RP-specific instruction blocks.
2. Chapter prompt token budgets are long-form (not capped to RP reply profiles).
3. Stub output does NOT inject RP ending cadence ("aftermath settled", etc.).
4. Stub word count meets minimum narrative threshold.
5. RP systems are confined to RP-only code paths.
"""
import pytest

from app.schemas.storylab import (
    Boundary,
    Direction,
    Length,
    Pacing,
    StoryLabControls,
    ToneIntensity,
)
from app.services.storylab_generator import (
    _LENGTH_CONFIG,
    _generate_stub_text,
    _qualify,
    build_chapter_prompt,
    build_storylab_prompt,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

_CONTROLS_LONG = StoryLabControls(
    direction=Direction.advance_plot,
    tone_intensity=ToneIntensity.moderate,
    pacing=Pacing.balanced,
    length=Length.long,
    boundary=Boundary.sfw,
)

_CONTROLS_MEDIUM = StoryLabControls(
    direction=Direction.add_dialogue,
    tone_intensity=ToneIntensity.moderate,
    pacing=Pacing.balanced,
    length=Length.medium,
    boundary=Boundary.sfw,
)

_CONTROLS_SHORT = StoryLabControls(
    direction=Direction.quiet_reflection,
    tone_intensity=ToneIntensity.light,
    pacing=Pacing.slow,
    length=Length.short,
    boundary=Boundary.sfw,
)

_STATE_JSON = {
    "story_state": {
        "tension": 0.3,
        "emotional_weight": 0.2,
        "stakes": 0.2,
        "intimacy_level": 0,
    }
}

_SCENE_TEXT = (
    "The hallway was dim. Elena stopped at the door, hand raised to knock. "
    "She hesitated — three seconds, four — then let her arm fall back to her side."
)


# ── RP phrases that must NEVER appear in standard StoryLab prompts ─────────────

_RP_FORBIDDEN_PHRASES = [
    "COLLABORATIVE RP ENFORCEMENT",
    "PARTNER-CONTROL PROTECTION",
    "PARTNER SILENCE",
    "SCENE PROGRESSION ENFORCEMENT",
    "INFERNO EXPLICITNESS",
    "ROLE LOCK — POV LOCK",
    "Write ONLY as the selected character",
    "Never write dialogue, thoughts, choices",
    "Partner reactions may be implied",
    "Scene Beat Engine",
    "RP BEHAVIORAL ENFORCEMENT",
    "Scene Drive",
    "selected character must carry the scene",
    "Do not stop and wait for the partner",
    "partner character to bridge",
]

# ── RP ending cadence phrases that must NOT appear in stub output ──────────────

_ENDING_CADENCE_FORBIDDEN = [
    "aftermath settled",
    "scene resolved",
    "completion mode",
    "progression success",
    "narrative closure",
]


# ══════════════════════════════════════════════════════════════════════════════
# 1. Prompt isolation — standard StoryLab continuation prompt
# ══════════════════════════════════════════════════════════════════════════════

class TestContinuationPromptIsolation:
    def _build(self, controls=None):
        return build_storylab_prompt(
            text=_SCENE_TEXT,
            controls=controls or _CONTROLS_LONG,
            state_json=_STATE_JSON,
            summary="Elena is visiting her estranged sister.",
            characters=[],
        )

    def test_returns_two_messages(self):
        msgs = self._build()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    @pytest.mark.parametrize("phrase", _RP_FORBIDDEN_PHRASES)
    def test_no_rp_phrase_in_system(self, phrase):
        msgs = self._build()
        assert phrase not in msgs[0]["content"], (
            f"RP phrase {phrase!r} found in standard StoryLab system prompt"
        )

    @pytest.mark.parametrize("phrase", _RP_FORBIDDEN_PHRASES)
    def test_no_rp_phrase_in_user(self, phrase):
        msgs = self._build()
        assert phrase not in msgs[1]["content"], (
            f"RP phrase {phrase!r} found in standard StoryLab user prompt"
        )

    def test_system_prompt_is_novelist(self):
        msgs = self._build()
        assert "professional novelist" in msgs[0]["content"].lower()

    def test_user_prompt_contains_scene_text(self):
        msgs = self._build()
        assert _SCENE_TEXT[-50:] in msgs[1]["content"]

    def test_user_prompt_contains_target_length(self):
        msgs = self._build()
        assert "Target length" in msgs[1]["content"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. Prompt isolation — chapter generation prompt
# ══════════════════════════════════════════════════════════════════════════════

class TestChapterPromptIsolation:
    def _build(self, controls=None):
        return build_chapter_prompt(
            prompt="Elena finally knocks. The door opens.",
            controls=controls or _CONTROLS_LONG,
            state_json=_STATE_JSON,
            summary="Elena is visiting her estranged sister.",
            characters=[],
            previous_chapter_text=_SCENE_TEXT,
        )

    def test_returns_two_messages(self):
        msgs = self._build()
        assert len(msgs) == 2

    @pytest.mark.parametrize("phrase", _RP_FORBIDDEN_PHRASES)
    def test_no_rp_phrase_in_system(self, phrase):
        msgs = self._build()
        assert phrase not in msgs[0]["content"], (
            f"RP phrase {phrase!r} found in standard chapter system prompt"
        )

    @pytest.mark.parametrize("phrase", _RP_FORBIDDEN_PHRASES)
    def test_no_rp_phrase_in_user(self, phrase):
        msgs = self._build()
        assert phrase not in msgs[1]["content"], (
            f"RP phrase {phrase!r} found in standard chapter user prompt"
        )

    def test_system_prompt_is_novelist(self):
        msgs = self._build()
        assert "professional novelist" in msgs[0]["content"].lower()

    def test_chapter_task_instruction_present(self):
        msgs = self._build()
        assert "Write a complete chapter" in msgs[1]["content"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. Token budget — standard StoryLab uses long-form token caps
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenBudget:
    def test_long_cap_words(self):
        target, cap = _LENGTH_CONFIG[Length.long]
        assert cap >= 2000, f"Long chapter cap too small: {cap} words"

    def test_medium_cap_words(self):
        target, cap = _LENGTH_CONFIG[Length.medium]
        assert cap >= 1000, f"Medium chapter cap too small: {cap} words"

    def test_long_target_words(self):
        target, cap = _LENGTH_CONFIG[Length.long]
        assert target >= 1500, f"Long chapter target too small: {target} words"

    def test_medium_target_words(self):
        target, cap = _LENGTH_CONFIG[Length.medium]
        assert target >= 700, f"Medium chapter target too small: {target} words"

    def test_long_max_tokens_calculation(self):
        """Chapter OpenRouter call uses cap_words * 2.5 — must exceed 4000 for long."""
        _, cap_words = _LENGTH_CONFIG[Length.long]
        max_tokens = max(400, int(cap_words * 2.5))
        assert max_tokens >= 4000, f"Long chapter max_tokens too small: {max_tokens}"

    def test_short_max_tokens_not_zero(self):
        _, cap_words = _LENGTH_CONFIG[Length.short]
        max_tokens = max(400, int(cap_words * 2.5))
        assert max_tokens >= 400

    def test_rp_profiles_not_imported_into_chapter_prompt_builder(self):
        """Chapter prompt builder must not reference RP reply length profiles."""
        import inspect
        from app.services import storylab_generator
        src = inspect.getsource(build_chapter_prompt)
        assert "_rp_length_profile" not in src
        assert "_RP_LENGTH_PROFILES" not in src
        assert "RPReplyResponseLength" not in src


# ══════════════════════════════════════════════════════════════════════════════
# 4. Stub — no RP ending cadence; minimum word count
# ══════════════════════════════════════════════════════════════════════════════

class TestStubOutput:
    @pytest.mark.parametrize("phrase", _ENDING_CADENCE_FORBIDDEN)
    def test_no_ending_cadence_in_long_stub(self, phrase):
        text = _generate_stub_text("story-001", _CONTROLS_LONG)
        assert phrase.lower() not in text.lower(), (
            f"RP ending cadence {phrase!r} found in long-length stub output"
        )

    @pytest.mark.parametrize("phrase", _ENDING_CADENCE_FORBIDDEN)
    def test_no_ending_cadence_in_medium_stub(self, phrase):
        text = _generate_stub_text("story-002", _CONTROLS_MEDIUM)
        assert phrase.lower() not in text.lower()

    @pytest.mark.parametrize("phrase", _ENDING_CADENCE_FORBIDDEN)
    def test_no_ending_cadence_in_short_stub(self, phrase):
        text = _generate_stub_text("story-003", _CONTROLS_SHORT)
        assert phrase.lower() not in text.lower()

    def test_stub_produces_nonempty_text(self):
        text = _generate_stub_text("story-001", _CONTROLS_LONG)
        assert text.strip()

    def test_stub_minimum_word_count(self):
        """Stub must produce at least 10 words so it's clearly narrative, not empty."""
        for controls in (_CONTROLS_SHORT, _CONTROLS_MEDIUM, _CONTROLS_LONG):
            text = _generate_stub_text("story-001", controls)
            wc = len(text.split())
            assert wc >= 10, f"Stub too short ({wc} words) for length={controls.length}"

    def test_qualify_long_no_aftermath_phrase(self):
        """_qualify must not inject 'aftermath settled' for any length."""
        result = _qualify("The scene continued.", ToneIntensity.moderate, Pacing.balanced, Length.long)
        assert "aftermath settled" not in result.lower()

    def test_qualify_all_lengths_no_rp_cadence(self):
        for length in (Length.short, Length.medium, Length.long):
            result = _qualify("Text.", ToneIntensity.moderate, Pacing.balanced, length)
            for phrase in _ENDING_CADENCE_FORBIDDEN:
                assert phrase.lower() not in result.lower(), (
                    f"RP cadence {phrase!r} found in _qualify output for length={length}"
                )

    def test_stub_does_not_contain_rp_enforcement_blocks(self):
        for controls in (_CONTROLS_SHORT, _CONTROLS_MEDIUM, _CONTROLS_LONG):
            text = _generate_stub_text("story-001", controls)
            for phrase in _RP_FORBIDDEN_PHRASES:
                assert phrase not in text, (
                    f"RP phrase {phrase!r} found in stub output for length={controls.length}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# 5. RP system isolation — RP functions must not be called from standard paths
# ══════════════════════════════════════════════════════════════════════════════

class TestRPSystemIsolation:
    _RP_ONLY_SYMBOLS = [
        "build_rp_prompt_layers",
        "build_rp_reply_prompt",
        "generate_rp_reply",
        "COLLABORATIVE_RP_ENFORCEMENT_LAYER",
        "PARTNER_SILENCE_LAYER",
        "SCENE_PROGRESSION_BLOCK",
        "SELECTED_CHARACTER_DRIVES_SCENE",
        "build_behavior_enforcement_block",
        "get_heat_prompt_block",
        "build_spatial_continuity_block",
        "detect_scene_beats",
        "build_scene_progression_block",
    ]

    def test_build_storylab_prompt_source_no_rp_calls(self):
        import inspect
        src = inspect.getsource(build_storylab_prompt)
        for sym in self._RP_ONLY_SYMBOLS:
            assert sym not in src, (
                f"RP symbol {sym!r} referenced inside build_storylab_prompt"
            )

    def test_build_chapter_prompt_source_no_rp_calls(self):
        import inspect
        src = inspect.getsource(build_chapter_prompt)
        for sym in self._RP_ONLY_SYMBOLS:
            assert sym not in src, (
                f"RP symbol {sym!r} referenced inside build_chapter_prompt"
            )

    def test_rp_reply_prompt_builder_exists_separately(self):
        from app.services.storylab_generator import build_rp_reply_prompt
        assert callable(build_rp_reply_prompt)

    def test_generate_rp_reply_exists_separately(self):
        from app.services.storylab_generator import generate_rp_reply
        assert callable(generate_rp_reply)

    def test_standard_generate_does_not_call_rp_reply(self):
        import inspect
        from app.services.storylab_generator import generate_storylab_continuation, generate_chapter
        for fn in (generate_storylab_continuation, generate_chapter):
            src = inspect.getsource(fn)
            assert "generate_rp_reply" not in src
            assert "build_rp_reply_prompt" not in src
            assert "build_rp_prompt_layers" not in src


# ══════════════════════════════════════════════════════════════════════════════
# 6. Endpoint-level isolation — RP route must not bleed into standard routes
# ══════════════════════════════════════════════════════════════════════════════

class TestEndpointIsolation:
    def test_standard_chapter_endpoint_returns_200(self, client):
        from tests.conftest import get_auth_token, auth_headers
        token = get_auth_token(client)
        story_resp = client.post(
            "/storylab/stories",
            headers=auth_headers(token),
            json={"title": "Isolation Test", "genre": "drama", "premise": "A test story."},
        )
        assert story_resp.status_code == 201, story_resp.text
        story_id = story_resp.json()["id"]

        resp = client.post(
            f"/storylab/chapters/generate?story_id={story_id}",
            headers=auth_headers(token),
            json={
                "prompt": "The door opened slowly.",
                "controls": {
                    "direction": "advance_plot",
                    "tone_intensity": "moderate",
                    "pacing": "balanced",
                    "length": "medium",
                    "boundary": "sfw",
                },
                "mode": "solo",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "generated_text" in data
        assert isinstance(data["generated_text"], str)

    def test_standard_chapter_output_no_rp_cadence(self, client):
        from tests.conftest import get_auth_token, auth_headers
        token = get_auth_token(client)
        story_resp = client.post(
            "/storylab/stories",
            headers=auth_headers(token),
            json={"title": "Cadence Test", "genre": "drama", "premise": "A test story."},
        )
        assert story_resp.status_code == 201, story_resp.text
        story_id = story_resp.json()["id"]

        resp = client.post(
            f"/storylab/chapters/generate?story_id={story_id}",
            headers=auth_headers(token),
            json={
                "prompt": "The conversation grew tense.",
                "controls": {
                    "direction": "argument_begins",
                    "tone_intensity": "intense",
                    "pacing": "balanced",
                    "length": "long",
                    "boundary": "sfw",
                },
                "mode": "solo",
            },
        )
        assert resp.status_code == 200, resp.text
        text = resp.json()["generated_text"].lower()
        for phrase in _ENDING_CADENCE_FORBIDDEN:
            assert phrase.lower() not in text, (
                f"RP ending cadence {phrase!r} found in standard chapter output"
            )

    def test_standard_chapter_output_minimum_word_count(self, client):
        """Standard chapter generation (stub or real) must exceed minimum word count."""
        from tests.conftest import get_auth_token, auth_headers
        token = get_auth_token(client)
        story_resp = client.post(
            "/storylab/stories",
            headers=auth_headers(token),
            json={"title": "Word Count Test", "genre": "thriller", "premise": "A test story."},
        )
        assert story_resp.status_code == 201, story_resp.text
        story_id = story_resp.json()["id"]

        resp = client.post(
            f"/storylab/chapters/generate?story_id={story_id}",
            headers=auth_headers(token),
            json={
                "prompt": "Something happens.",
                "controls": {
                    "direction": "advance_plot",
                    "tone_intensity": "moderate",
                    "pacing": "balanced",
                    "length": "medium",
                    "boundary": "sfw",
                },
                "mode": "solo",
            },
        )
        assert resp.status_code == 200, resp.text
        text = resp.json()["generated_text"]
        word_count = len(text.split())
        assert word_count >= 10, f"Chapter output too short: {word_count} words"
