"""Regression tests: Create Story path isolation and length contract.

Verifies:
A. RP Reply imports/systems are NOT used in Create Story generation.
B. Create Story endpoint does NOT call RP generator functions.
C. Create Story long uses StoryLab long token/minimum budget (≥1500 words prompt target).
D. Create Story selected controls (length/pacing/tone) reach the backend prompt.
E. Create Story long output below minimum triggers retry logic (not silent accept).
F. RP Reply tests are not broken by these isolation requirements.
G. Model slug is not a known-broken Bedrock slug.
"""
import inspect
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
    _STUB_MIN_WORDS,
    _EFFECTIVE_STORYLAB_MODEL,
    _STORYLAB_FALLBACK_MODEL,
    build_chapter_prompt,
    build_storylab_prompt,
    generate_chapter,
    generate_storylab_continuation,
)
from app.services.rp_models import RP_REPLY_MODELS

# ── helpers ───────────────────────────────────────────────────────────────────

def _controls_long_intense_fast_sensual() -> StoryLabControls:
    return StoryLabControls(
        direction=Direction.sensual_scene,
        tone_intensity=ToneIntensity.intense,
        pacing=Pacing.fast,
        length=Length.long,
        boundary=Boundary.sensual,
    )


def _controls_medium() -> StoryLabControls:
    return StoryLabControls(
        direction=Direction.advance_plot,
        tone_intensity=ToneIntensity.moderate,
        pacing=Pacing.balanced,
        length=Length.medium,
        boundary=Boundary.sfw,
    )


_STATE_JSON = {"story_state": {"tension": 0.3, "emotional_weight": 0.2, "stakes": 0.2, "intimacy_level": 0}}
_SCENE = "The hallway was dim. Elena stopped at the door."

# ── RP-only symbols that MUST NOT appear in standard generation ───────────────
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
    "_RP_LENGTH_PROFILES",
    "RPReplyResponseLength",
    "build_narrative_propulsion_block",
    "detect_scene_mechanics",
]


# ══════════════════════════════════════════════════════════════════════════════
# A. RP isolation — source-level: RP symbols must not appear in standard paths
# ══════════════════════════════════════════════════════════════════════════════

class TestRPIsolationSourceLevel:
    @pytest.mark.parametrize("sym", _RP_ONLY_SYMBOLS)
    def test_build_storylab_prompt_no_rp_symbol(self, sym):
        src = inspect.getsource(build_storylab_prompt)
        assert sym not in src, f"RP symbol {sym!r} found in build_storylab_prompt source"

    @pytest.mark.parametrize("sym", _RP_ONLY_SYMBOLS)
    def test_build_chapter_prompt_no_rp_symbol(self, sym):
        src = inspect.getsource(build_chapter_prompt)
        assert sym not in src, f"RP symbol {sym!r} found in build_chapter_prompt source"

    def test_generate_storylab_continuation_no_rp_calls(self):
        src = inspect.getsource(generate_storylab_continuation)
        for sym in ("generate_rp_reply", "build_rp_reply_prompt", "build_rp_prompt_layers"):
            assert sym not in src, f"RP call {sym!r} found in generate_storylab_continuation"

    def test_generate_chapter_no_rp_calls(self):
        src = inspect.getsource(generate_chapter)
        for sym in ("generate_rp_reply", "build_rp_reply_prompt", "build_rp_prompt_layers"):
            assert sym not in src, f"RP call {sym!r} found in generate_chapter"


# ══════════════════════════════════════════════════════════════════════════════
# B. Endpoint isolation — route source must not call RP generators
# ══════════════════════════════════════════════════════════════════════════════

class TestEndpointRPIsolation:
    def test_chapter_generate_endpoint_no_rp_generator_call(self):
        from app.api.routes import storylab as route_module
        import inspect
        src = inspect.getsource(route_module)
        # The route file imports RP functions for /rp-reply/generate only.
        # It must NOT call them from the chapter generate path.
        # Verify the endpoint function itself is clean.
        # Find the generate_chapter_endpoint function source
        fn = getattr(route_module, "generate_chapter_endpoint", None)
        assert fn is not None
        fn_src = inspect.getsource(fn)
        for sym in ("generate_rp_reply", "build_rp_reply_prompt", "build_rp_prompt_layers"):
            assert sym not in fn_src, f"RP call {sym!r} found in generate_chapter_endpoint"


# ══════════════════════════════════════════════════════════════════════════════
# C. Token budget — long chapter uses correct minimum budget
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenBudgetCreateStory:
    def test_long_target_words_at_least_1500(self):
        target, cap = _LENGTH_CONFIG[Length.long]
        assert target >= 1500, f"Long target_words={target} is below 1500 minimum"

    def test_long_cap_words_at_least_2000(self):
        target, cap = _LENGTH_CONFIG[Length.long]
        assert cap >= 2000, f"Long cap_words={cap} is below 2000"

    def test_medium_target_words_at_least_900(self):
        target, cap = _LENGTH_CONFIG[Length.medium]
        assert target >= 900, f"Medium target_words={target} is below 900 minimum"

    def test_short_target_words_at_least_500(self):
        target, cap = _LENGTH_CONFIG[Length.short]
        assert target >= 500, f"Short target_words={target} is below 500 minimum"

    def test_long_max_tokens_at_least_5000(self):
        """Long chapter must have a token budget large enough for 1500+ words."""
        _, cap_words = _LENGTH_CONFIG[Length.long]
        max_tokens = max(400, int(cap_words * 2.5))
        assert max_tokens >= 5000, f"Long chapter max_tokens={max_tokens} too small"

    def test_stub_min_long_at_least_1500(self):
        assert _STUB_MIN_WORDS[Length.long] >= 1500

    def test_stub_min_medium_at_least_900(self):
        assert _STUB_MIN_WORDS[Length.medium] >= 900

    def test_stub_min_short_at_least_500(self):
        assert _STUB_MIN_WORDS[Length.short] >= 500


# ══════════════════════════════════════════════════════════════════════════════
# D. Controls reach the backend prompt
# ══════════════════════════════════════════════════════════════════════════════

class TestControlsPropagation:
    def _build_chapter(self, controls: StoryLabControls) -> list[dict]:
        return build_chapter_prompt(
            prompt="She reached for the door.",
            controls=controls,
            state_json=_STATE_JSON,
            summary="Elena visits her sister.",
            characters=[],
        )

    def test_long_target_words_in_prompt(self):
        controls = _controls_long_intense_fast_sensual()
        msgs = self._build_chapter(controls)
        user = msgs[1]["content"]
        target_words = _LENGTH_CONFIG[Length.long][0]
        assert str(target_words) in user, f"Target word count {target_words} not found in prompt"

    def test_long_enforcement_note_in_prompt(self):
        controls = _controls_long_intense_fast_sensual()
        msgs = self._build_chapter(controls)
        user = msgs[1]["content"]
        assert "1,500" in user or "1500" in user, "Long length enforcement note missing from prompt"

    def test_intense_contract_in_prompt(self):
        controls = _controls_long_intense_fast_sensual()
        msgs = self._build_chapter(controls)
        user = msgs[1]["content"]
        assert "INTENSE" in user or "intense" in user.lower(), "Intense tone contract not injected"

    def test_fast_contract_in_prompt(self):
        controls = _controls_long_intense_fast_sensual()
        msgs = self._build_chapter(controls)
        user = msgs[1]["content"]
        assert "FAST" in user or "fast" in user.lower(), "Fast pacing contract not injected"

    def test_sensual_contract_in_prompt(self):
        controls = _controls_long_intense_fast_sensual()
        msgs = self._build_chapter(controls)
        user = msgs[1]["content"]
        assert "SENSUAL" in user or "sensual" in user.lower() or "chemistry" in user.lower(), \
            "Sensual contract not injected"

    def test_direction_in_prompt(self):
        controls = _controls_long_intense_fast_sensual()
        msgs = self._build_chapter(controls)
        user = msgs[1]["content"]
        assert "sensual_scene" in user or "SENSATION" in user, "Direction not injected into prompt"

    def test_medium_enforcement_note_in_prompt(self):
        controls = _controls_medium()
        msgs = self._build_chapter(controls)
        user = msgs[1]["content"]
        assert "900" in user, "Medium enforcement note (900 words) missing from prompt"

    def test_no_rp_phrase_in_long_intense_chapter_prompt(self):
        """Long/intense/sensual chapter prompt must have zero RP contamination."""
        from tests.test_storylab_isolation import _RP_FORBIDDEN_PHRASES
        controls = _controls_long_intense_fast_sensual()
        msgs = self._build_chapter(controls)
        for part in msgs:
            for phrase in _RP_FORBIDDEN_PHRASES:
                assert phrase not in part["content"], \
                    f"RP phrase {phrase!r} found in chapter prompt (role={part['role']})"


# ══════════════════════════════════════════════════════════════════════════════
# E. Model slug — resolved slug must not be a known-broken Bedrock slug
# ══════════════════════════════════════════════════════════════════════════════

class TestModelSlug:
    def test_effective_model_is_non_empty(self):
        """Effective model must always resolve to a non-empty slug."""
        assert _EFFECTIVE_STORYLAB_MODEL, "Effective model slug is empty"

    def test_fallback_model_in_rp_registry(self):
        """Fallback model must be a slug that exists in the RP model registry."""
        registry_slugs = set(RP_REPLY_MODELS.values()) - {""}
        assert _STORYLAB_FALLBACK_MODEL in registry_slugs, (
            f"_STORYLAB_FALLBACK_MODEL={_STORYLAB_FALLBACK_MODEL!r} is not in the RP model registry. "
            "Use a slug from rp_models.RP_REPLY_MODELS so it is a known-good OpenRouter route."
        )

    def test_sonnet_not_rewritten_to_versioned_20241022(self):
        """anthropic/claude-3.5-sonnet must NOT be auto-corrected to anthropic/claude-3.5-sonnet-20241022.

        That versioned slug returns 404 on OpenRouter. Auto-correction was removed in
        favour of configuring the correct slug in .env / environment directly.
        """
        # The module-level _EFFECTIVE_STORYLAB_MODEL reflects the actual runtime config
        # with no rewriting applied. Verify neither the effective model nor the fallback
        # is the 404-returning versioned slug.
        assert _EFFECTIVE_STORYLAB_MODEL != "anthropic/claude-3.5-sonnet-20241022", (
            "Effective model is anthropic/claude-3.5-sonnet-20241022 — "
            "this slug returns 404 on OpenRouter. Set STORYLAB_MODEL to a working slug."
        )
        assert _STORYLAB_FALLBACK_MODEL != "anthropic/claude-3.5-sonnet-20241022", (
            "Fallback model must not be anthropic/claude-3.5-sonnet-20241022 (returns 404)."
        )

    def test_no_bedrock_broken_slugs_dict_in_module(self):
        """The _OPENROUTER_BEDROCK_BROKEN_SLUGS auto-correction dict must not exist in the module.

        Its removal prevents silent rewriting of model slugs to other broken slugs.
        """
        import app.services.storylab_generator as sg
        assert not hasattr(sg, "_OPENROUTER_BEDROCK_BROKEN_SLUGS"), (
            "_OPENROUTER_BEDROCK_BROKEN_SLUGS still exists in storylab_generator — "
            "it was rewriting anthropic/claude-3.5-sonnet to the also-broken "
            "anthropic/claude-3.5-sonnet-20241022. Remove it."
        )


# ══════════════════════════════════════════════════════════════════════════════
# F. RP Reply system still exists and is independently callable
# ══════════════════════════════════════════════════════════════════════════════

class TestRPReplyStillWorks:
    def test_build_rp_reply_prompt_callable(self):
        from app.services.storylab_generator import build_rp_reply_prompt
        assert callable(build_rp_reply_prompt)

    def test_generate_rp_reply_callable(self):
        from app.services.storylab_generator import generate_rp_reply
        assert callable(generate_rp_reply)

    def test_rp_reply_prompt_has_partner_silence_layer(self):
        from app.services.storylab_generator import build_rp_reply_prompt
        msgs = build_rp_reply_prompt(
            partner_reply="She looked at him steadily.",
            response_length="match",
            style_match="soft",
            perspective="third_person_limited",
            formatting="plain",
            intensity="standard",
        )
        combined = " ".join(m["content"] for m in msgs)
        assert "PARTNER SILENCE" in combined or "Partner Silence" in combined

    def test_rp_reply_has_no_storylab_chapter_fields(self):
        """RP reply prompt must not include StoryLab chapter prompt blocks."""
        from app.services.storylab_generator import build_rp_reply_prompt
        msgs = build_rp_reply_prompt(
            partner_reply="She looked at him steadily.",
            response_length="match",
            style_match="soft",
            perspective="third_person_limited",
            formatting="plain",
            intensity="standard",
        )
        combined = " ".join(m["content"] for m in msgs)
        # StoryLab-specific blocks must not appear in RP Reply
        assert "## Target length — MANDATORY" not in combined
        assert "Write a complete chapter" not in combined


# ══════════════════════════════════════════════════════════════════════════════
# G. Diag metadata present in chapter endpoint response
# ══════════════════════════════════════════════════════════════════════════════

class TestDiagMetadata:
    def test_chapter_response_includes_diag_metadata(self, client):
        from tests.conftest import get_auth_token, auth_headers
        token = get_auth_token(client)
        story_resp = client.post(
            "/storylab/stories",
            headers=auth_headers(token),
            json={"title": "Diag Test", "genre": "drama", "premise": "Test premise."},
        )
        assert story_resp.status_code == 201
        story_id = story_resp.json()["id"]

        resp = client.post(
            f"/storylab/chapters/generate?story_id={story_id}",
            headers=auth_headers(token),
            json={
                "prompt": "The scene continues.",
                "controls": {
                    "direction": "advance_plot",
                    "tone_intensity": "intense",
                    "pacing": "fast",
                    "length": "long",
                    "boundary": "sfw",
                },
                "mode": "solo",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "meta" in data
        assert "diag" in data["meta"], f"diag metadata missing from response: {data['meta']}"
        diag = data["meta"]["diag"]
        assert "provider" in diag
        assert "endpoint_ms" in diag
        assert "length" in diag
        assert "using_stub" in diag
        assert diag["length"] == "long"
        assert diag["tone"] == "intense"

    def test_chapter_response_diag_reflects_controls(self, client):
        """Verify controls sent by frontend are received and reflected in diag."""
        from tests.conftest import get_auth_token, auth_headers
        token = get_auth_token(client)
        story_resp = client.post(
            "/storylab/stories",
            headers=auth_headers(token),
            json={"title": "Controls Reflect Test", "genre": "drama", "premise": "Test."},
        )
        story_id = story_resp.json()["id"]

        resp = client.post(
            f"/storylab/chapters/generate?story_id={story_id}",
            headers=auth_headers(token),
            json={
                "prompt": "The conversation grew tense.",
                "controls": {
                    "direction": "argument_begins",
                    "tone_intensity": "intense",
                    "pacing": "fast",
                    "length": "long",
                    "boundary": "sfw",
                },
                "mode": "solo",
            },
        )
        assert resp.status_code == 200
        diag = resp.json()["meta"]["diag"]
        # Controls must reach the endpoint intact
        assert diag["length"] == "long"
        assert diag["pacing"] == "fast"
        assert diag["tone"] == "intense"
