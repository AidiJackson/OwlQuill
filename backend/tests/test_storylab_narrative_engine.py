"""Tests for the StoryLab narrative engine and its wiring into prompt builders.

Coverage:
  A. storylab_narrative_engine public API (detect_story_repetition, detect_story_progression,
     build_storylab_propulsion_block, build_storylab_loop_correction_block, _STORYLAB_PROPULSION_CORE)
  B. Propulsion block injected into build_storylab_prompt and build_chapter_prompt
  C. Propulsion block adapts to fast/intense/sensual/long controls
  D. RP prompt does NOT contain StoryLab propulsion block text
  E. Propulsion_correction param injects loop correction into prompt
  F. RP isolation — storylab_narrative_engine must NOT import rp_narrative_engine symbols
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
from app.services.storylab_narrative_engine import (
    _STORYLAB_PROPULSION_CORE,
    build_storylab_loop_correction_block,
    build_storylab_propulsion_block,
    detect_story_progression,
    detect_story_repetition,
)
from app.services.storylab_generator import (
    build_chapter_prompt,
    build_storylab_prompt,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

_STATE = {"story_state": {"tension": 0.3, "emotional_weight": 0.2, "stakes": 0.2, "intimacy_level": 0}}
_SCENE = "The hallway was dim. Elena stopped at the door."


def _controls(**kw) -> StoryLabControls:
    defaults = dict(
        direction=Direction.advance_plot,
        tone_intensity=ToneIntensity.moderate,
        pacing=Pacing.balanced,
        length=Length.medium,
        boundary=Boundary.sfw,
    )
    defaults.update(kw)
    return StoryLabControls(**defaults)


def _chapter_msgs(controls: StoryLabControls, propulsion_correction: str = "") -> list[dict]:
    return build_chapter_prompt(
        prompt="She reached for the door.",
        controls=controls,
        state_json=_STATE,
        summary="Elena visits her sister.",
        characters=[],
        propulsion_correction=propulsion_correction,
    )


def _storylab_msgs(controls: StoryLabControls, propulsion_correction: str = "") -> list[dict]:
    return build_storylab_prompt(
        text=_SCENE,
        controls=controls,
        state_json=_STATE,
        summary="Elena visits her sister.",
        characters=[],
        propulsion_correction=propulsion_correction,
    )


# ══════════════════════════════════════════════════════════════════════════════
# A. detect_story_repetition
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectStoryRepetition:
    def test_clean_text_no_repetition(self):
        text = (
            "Elena stepped into the kitchen. Marcus turned from the window. "
            "Their eyes met briefly before he looked away. "
            "She crossed to the counter, running her fingers along the cold marble. "
            "Neither spoke for a long moment."
        )
        result = detect_story_repetition(text)
        assert result["repeated_section_detected"] is False
        assert result["story_repetition_score"] < 0.3
        assert result["repeated_dialogue_count"] == 0

    def test_repeated_dialogue_detected(self):
        text = (
            '"You need to leave," he said.\n'
            'She shook her head. "I can\'t do that."\n'
            '"You need to leave," he repeated.\n'
            '"I won\'t," she answered.\n'
            '"You need to leave." His voice was flat this time.'
        )
        result = detect_story_repetition(text)
        assert result["repeated_dialogue_count"] >= 1
        assert result["repeated_section_detected"] is True

    def test_repeated_ngrams_detected(self):
        phrase = "the rain lashed against the darkened window pane"
        text = f"{phrase} as she waited. Time passed. {phrase} again without mercy. {phrase}."
        result = detect_story_repetition(text)
        assert result["repeated_ngram_count"] >= 1
        assert result["story_repetition_score"] > 0.0

    def test_atmospheric_repetition_weather(self):
        text = (
            "Storm. The thunder rolled again. Lightning split the sky. "
            "Rain. More storm outside. The tempest raged. "
            "Wind tore through. The downpour didn't stop."
        )
        result = detect_story_repetition(text)
        assert result["repeated_weather_count"] >= 4

    def test_repeated_attraction_narration(self):
        text = (
            "She felt the magnetic pull toward him. The attraction was undeniable. "
            "Electric chemistry crackled between them. She was drawn to him again. "
            "The magnetic force of her feelings. She couldn't deny the attraction. "
            "Something electric lingered. She wanted him."
        )
        result = detect_story_repetition(text)
        assert result["repeated_attraction_count"] >= 5
        assert result["repeated_section_detected"] is True

    def test_return_keys_present(self):
        result = detect_story_repetition("A short sentence.")
        expected_keys = {
            "repeated_section_detected", "story_repetition_score",
            "repeated_dialogue_count", "repeated_ngram_count",
            "repeated_weather_count", "repeated_attraction_count",
            "repeated_tension_count", "repeated_setting_beat_count",
            "repeated_phrases",
        }
        assert expected_keys == set(result.keys())

    def test_score_in_range(self):
        result = detect_story_repetition("She walked. He followed. Rain fell.")
        assert 0.0 <= result["story_repetition_score"] <= 1.0

    def test_repeated_phrases_list_max_five(self):
        text = " ".join(["alpha beta gamma delta epsilon zeta"] * 10)
        result = detect_story_repetition(text)
        assert len(result["repeated_phrases"]) <= 5


# ══════════════════════════════════════════════════════════════════════════════
# B. detect_story_progression
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectStoryProgression:
    def test_action_rich_text_high_score(self):
        text = (
            "He moved across the room and grabbed the door handle. "
            "She stepped back, turning to face him. He reached out and touched her arm. "
            "She pulled away and crossed to the window. "
            "He walked after her and pressed forward. "
            "She turned, kissed him briefly, then backed away again. "
            '"Don\'t," she said. He stood still.'
        )
        result = detect_story_progression(text)
        assert result["story_progression_score"] > 0.2
        assert result["action_count"] > 0

    def test_static_text_low_score(self):
        text = (
            "It was a dark time in her life. She had been feeling sad for a while. "
            "The memories lingered. Her thoughts circled the same questions endlessly. "
            "Nothing seemed to change. The world outside felt distant and grey."
        )
        result = detect_story_progression(text)
        assert result["story_progression_score"] < 0.5

    def test_return_keys_present(self):
        result = detect_story_progression("She walked to the door.")
        expected_keys = {
            "story_progression_score", "action_count",
            "dialogue_exchange_count", "scene_change_count",
            "revelation_count", "environment_count",
        }
        assert expected_keys == set(result.keys())

    def test_score_in_range(self):
        result = detect_story_progression("Nothing happened at all.")
        assert 0.0 <= result["story_progression_score"] <= 1.0

    def test_scene_change_detected(self):
        text = "She walked into the kitchen. He entered the room. She moved to the hallway."
        result = detect_story_progression(text)
        assert result["scene_change_count"] >= 1

    def test_revelation_detected(self):
        text = 'She finally said it aloud. He admitted everything he had been hiding. She told him the truth.'
        result = detect_story_progression(text)
        assert result["revelation_count"] >= 2


# ══════════════════════════════════════════════════════════════════════════════
# C. build_storylab_propulsion_block
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildStoryLabPropulsionBlock:
    def test_always_includes_core(self):
        block = build_storylab_propulsion_block(_controls())
        assert _STORYLAB_PROPULSION_CORE in block

    def test_fast_adds_addendum(self):
        block = build_storylab_propulsion_block(_controls(pacing=Pacing.fast))
        assert "fast" in block.lower() or "intense" in block.lower() or "stakes" in block.lower()

    def test_intense_adds_addendum(self):
        block = build_storylab_propulsion_block(_controls(tone_intensity=ToneIntensity.intense))
        assert "stakes" in block.lower() or "pressure" in block.lower()

    def test_sensual_boundary_adds_addendum(self):
        block = build_storylab_propulsion_block(_controls(boundary=Boundary.sensual))
        assert "chemistry" in block.lower() or "sensation" in block.lower()

    def test_sensual_direction_adds_addendum(self):
        block = build_storylab_propulsion_block(_controls(direction=Direction.sensual_scene))
        assert "chemistry" in block.lower() or "sensation" in block.lower()

    def test_romantic_direction_adds_sensual_addendum(self):
        block = build_storylab_propulsion_block(_controls(direction=Direction.romantic_moment))
        assert "chemistry" in block.lower() or "sensation" in block.lower()

    def test_long_adds_multi_section(self):
        block = build_storylab_propulsion_block(_controls(length=Length.long))
        assert "section" in block.lower() or "beat" in block.lower()

    def test_medium_sfw_balanced_no_extra_addenda(self):
        block = build_storylab_propulsion_block(_controls())
        # Core only — no fast/intense/sensual/long addenda for a medium/balanced/sfw setup
        assert block == _STORYLAB_PROPULSION_CORE

    def test_block_is_string(self):
        block = build_storylab_propulsion_block(_controls())
        assert isinstance(block, str) and len(block) > 10

    def test_all_controls_no_exception(self):
        for direction in Direction:
            for pacing in Pacing:
                for tone in ToneIntensity:
                    for length in Length:
                        for boundary in Boundary:
                            c = _controls(
                                direction=direction,
                                pacing=pacing,
                                tone_intensity=tone,
                                length=length,
                                boundary=boundary,
                            )
                            build_storylab_propulsion_block(c)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# D. build_storylab_loop_correction_block
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildStoryLabLoopCorrectionBlock:
    def test_returns_non_empty_string(self):
        block = build_storylab_loop_correction_block()
        assert isinstance(block, str) and len(block) > 10

    def test_references_repetition(self):
        block = build_storylab_loop_correction_block()
        lowered = block.lower()
        assert "repeat" in lowered or "rewrite" in lowered or "loop" in lowered


# ══════════════════════════════════════════════════════════════════════════════
# E. Propulsion block injected into build_storylab_prompt
# ══════════════════════════════════════════════════════════════════════════════

class TestPropulsionInjectedIntoStoryLabPrompt:
    def test_core_block_in_prompt(self):
        msgs = _storylab_msgs(_controls())
        user = msgs[1]["content"]
        assert _STORYLAB_PROPULSION_CORE in user, "Core propulsion block missing from build_storylab_prompt"

    def test_narrative_propulsion_header_in_prompt(self):
        msgs = _storylab_msgs(_controls())
        user = msgs[1]["content"]
        assert "## Narrative propulsion" in user

    def test_sensual_addendum_in_sensual_prompt(self):
        msgs = _storylab_msgs(_controls(boundary=Boundary.sensual))
        user = msgs[1]["content"]
        assert "chemistry" in user.lower() or "sensation" in user.lower()

    def test_long_addendum_in_long_prompt(self):
        msgs = _storylab_msgs(_controls(length=Length.long))
        user = msgs[1]["content"]
        assert "section" in user.lower() or "beat" in user.lower()

    def test_loop_correction_absent_by_default(self):
        msgs = _storylab_msgs(_controls())
        user = msgs[1]["content"]
        assert "## Loop correction" not in user

    def test_loop_correction_injected_when_set(self):
        msgs = _storylab_msgs(_controls(), propulsion_correction="DO NOT REPEAT THE SAME EXCHANGE.")
        user = msgs[1]["content"]
        assert "## Loop correction" in user
        assert "DO NOT REPEAT THE SAME EXCHANGE." in user

    def test_loop_correction_appears_before_task(self):
        correction = "ADVANCE THROUGH NEW ACTION."
        msgs = _storylab_msgs(_controls(), propulsion_correction=correction)
        user = msgs[1]["content"]
        correction_pos = user.index("## Loop correction")
        task_pos = user.index("## Task")
        assert correction_pos < task_pos, "Loop correction must appear before Task section"


# ══════════════════════════════════════════════════════════════════════════════
# F. Propulsion block injected into build_chapter_prompt
# ══════════════════════════════════════════════════════════════════════════════

class TestPropulsionInjectedIntoChapterPrompt:
    def test_core_block_in_chapter_prompt(self):
        msgs = _chapter_msgs(_controls())
        user = msgs[1]["content"]
        assert _STORYLAB_PROPULSION_CORE in user, "Core propulsion block missing from build_chapter_prompt"

    def test_narrative_propulsion_header_in_chapter_prompt(self):
        msgs = _chapter_msgs(_controls())
        user = msgs[1]["content"]
        assert "## Narrative propulsion" in user

    def test_fast_intense_addendum_in_chapter_prompt(self):
        msgs = _chapter_msgs(_controls(pacing=Pacing.fast, tone_intensity=ToneIntensity.intense))
        user = msgs[1]["content"]
        assert "stakes" in user.lower() or "pressure" in user.lower()

    def test_loop_correction_absent_by_default(self):
        msgs = _chapter_msgs(_controls())
        user = msgs[1]["content"]
        assert "## Loop correction" not in user

    def test_loop_correction_injected_when_set(self):
        msgs = _chapter_msgs(_controls(), propulsion_correction="ADVANCE THROUGH NEW ACTION.")
        user = msgs[1]["content"]
        assert "## Loop correction" in user
        assert "ADVANCE THROUGH NEW ACTION." in user

    def test_loop_correction_appears_before_task(self):
        correction = "DO NOT STALL."
        msgs = _chapter_msgs(_controls(), propulsion_correction=correction)
        user = msgs[1]["content"]
        correction_pos = user.index("## Loop correction")
        task_pos = user.index("## Task")
        assert correction_pos < task_pos, "Loop correction must appear before Task section"

    def test_propulsion_appears_after_narrative_contract(self):
        msgs = _chapter_msgs(_controls(tone_intensity=ToneIntensity.intense))
        user = msgs[1]["content"]
        contract_pos = user.index("## Narrative contract")
        propulsion_pos = user.index("## Narrative propulsion")
        assert contract_pos < propulsion_pos, "Narrative propulsion must appear after narrative contract"


# ══════════════════════════════════════════════════════════════════════════════
# G. RP prompt does NOT contain StoryLab propulsion block
# ══════════════════════════════════════════════════════════════════════════════

class TestRPPromptNoStoryLabPropulsion:
    def test_build_rp_reply_prompt_no_propulsion_core(self):
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
        assert _STORYLAB_PROPULSION_CORE not in combined, (
            "StoryLab propulsion core found in RP reply prompt — cross-contamination"
        )

    def test_build_rp_reply_prompt_no_narrative_propulsion_header(self):
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
        # The StoryLab header "## Narrative propulsion" should NOT appear in RP prompt
        # (the RP prompt uses its own narrative propulsion layer with different content)
        assert "Advance the chapter through concrete scene beats" not in combined, (
            "StoryLab propulsion core text found in RP prompt"
        )


# ══════════════════════════════════════════════════════════════════════════════
# H. RP isolation — storylab_narrative_engine imports no RP-only symbols
# ══════════════════════════════════════════════════════════════════════════════

class TestStoryLabNarrativeEngineRPIsolation:
    # Bare symbols that must NOT appear anywhere in storylab_narrative_engine source
    _RP_SYMBOLS = [
        "build_narrative_propulsion_block",
        "detect_scene_mechanics",
        "detect_scene_progression_events",
        "detect_paragraph_monotony",
        "rp_behavior_engine",
        "rp_scene_engine",
        "rp_escalation",
        "rp_models",
        "rp_beat_planner",
        "rp_spatial_engine",
        "rp_style_engine",
        "PARTNER_SILENCE_LAYER",
        "SCENE_PROGRESSION_BLOCK",
    ]

    @pytest.mark.parametrize("sym", _RP_SYMBOLS)
    def test_storylab_narrative_engine_no_rp_import(self, sym):
        import app.services.storylab_narrative_engine as engine
        src = inspect.getsource(engine)
        assert sym not in src, (
            f"RP symbol {sym!r} found in storylab_narrative_engine — isolation violation"
        )

    def test_storylab_narrative_engine_does_not_import_rp_module(self):
        import re as _re
        import app.services.storylab_narrative_engine as engine
        src = inspect.getsource(engine)
        # The docstring may mention rp_narrative_engine by name as a reference.
        # What must NOT exist is an actual import statement for it.
        assert not _re.search(r'^\s*(import|from)\s+.*rp_narrative_engine', src, _re.MULTILINE), (
            "storylab_narrative_engine contains an import of rp_narrative_engine — isolation violation"
        )
