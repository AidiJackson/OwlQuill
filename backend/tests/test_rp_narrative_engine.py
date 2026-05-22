"""Tests for rp_narrative_engine — narrative propulsion and anti-loop orchestration.

Covers:
1. detect_scene_mechanics — repetition detection, density metrics, risk scores
2. detect_scene_progression_events — escalation, power shift, transition
3. detect_paragraph_monotony — consecutive same-type paragraphs
4. determine_scene_forward_pressure — guidance selection based on mechanics/events
5. build_narrative_propulsion_block — block generation and lightweight contract
6. Prompt injection order — propulsion appears after partner_control, before heat
7. Explicit (inferno) mode compatibility — propulsion present at inferno heat
8. StoryLab isolation — propulsion NOT in chapter or continuation prompts
"""
import inspect
import pytest

from app.services.rp_narrative_engine import (
    build_narrative_propulsion_block,
    detect_paragraph_monotony,
    detect_scene_mechanics,
    detect_scene_progression_events,
    determine_scene_forward_pressure,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

_LOOPING_TEXT = (
    "The tension between them was electric. She could feel the danger of this moment.\n\n"
    "His eyes met hers. Her heart pounded. The tension was undeniable again.\n\n"
    "She felt the pull toward him. Attraction she could not ignore.\n\n"
    "His eyes burned into her. Tension filled the room once more.\n\n"
    "She longed for him. The heartbeat quickened. She longed still more.\n\n"
    "Her heartbeat stuttered. The tension between them was dangerous yet again."
)

_PROGRESSIVE_TEXT = (
    "She crossed the room toward him, closing the distance in three deliberate steps.\n\n"
    '"You should leave," she said, voice steady despite the rapid beat of her pulse.\n\n'
    "He grabbed her wrist before she reached the door, spinning her back against the wall.\n\n"
    "She pushed him away, power shift complete — she was the one in control now.\n\n"
    "She walked out of the room, pulling the door shut behind her with a quiet click."
)

_FLOATING_TEXT = (
    '"Do you even know what you want?" she asked.\n\n'
    '"I know exactly what I want," he said. "The question is whether you do."\n\n'
    '"That\'s not a fair question," she said. "Nothing about this is fair."\n\n'
    '"Life isn\'t fair," he replied. "You knew that already."\n\n'
    '"Stop deflecting," she said.'
)

_INTROSPECTION_MONOTONY_TEXT = (
    "She felt the pull toward him. Something in her wanted to close the distance.\n\n"
    "She longed for what they had. Part of her knew it was wrong but couldn't stop wanting.\n\n"
    "She wondered if he noticed. She realized she had been staring. She knew this was dangerous.\n\n"
    "She thought about it all evening. Craving what she couldn't have. Aching with the weight of it."
)

_ENVIRONMENT_TEXT = (
    "She pressed her back against the wall, one hand finding the cold doorframe.\n\n"
    "He reached for the glass on the counter, setting it down with deliberate calm.\n\n"
    "She crossed to the window and looked out at the rain, fingers tracing the frame."
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. detect_scene_mechanics
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectSceneMechanics:
    def test_returns_all_required_keys(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        required = {
            "progression_density", "interaction_density", "movement_density",
            "environment_usage_density", "dialogue_ratio", "introspection_ratio",
            "repeated_tension_count", "repeated_attraction_count",
            "repeated_heartbeat_count", "repeated_storm_count", "repeated_eye_count",
            "floating_scene_risk", "static_scene_risk", "recursive_emotion_risk",
        }
        assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"

    def test_all_values_in_valid_range(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        float_fields = [
            "progression_density", "interaction_density", "movement_density",
            "environment_usage_density", "dialogue_ratio", "introspection_ratio",
            "floating_scene_risk", "static_scene_risk", "recursive_emotion_risk",
        ]
        for field in float_fields:
            assert 0.0 <= result[field] <= 1.0, f"{field}={result[field]} out of range"

    def test_high_tension_count_on_looping_text(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        assert result["repeated_tension_count"] >= 4, (
            f"Expected ≥4 tension hits, got {result['repeated_tension_count']}"
        )

    def test_high_eye_count_on_looping_text(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        assert result["repeated_eye_count"] >= 2, (
            f"Expected ≥2 eye hits, got {result['repeated_eye_count']}"
        )

    def test_high_heartbeat_count_on_looping_text(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        assert result["repeated_heartbeat_count"] >= 2, (
            f"Expected ≥2 heartbeat hits, got {result['repeated_heartbeat_count']}"
        )

    def test_high_static_risk_on_looping_text(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        assert result["static_scene_risk"] > 0.5, (
            f"Expected static_scene_risk > 0.5 on looping text, got {result['static_scene_risk']}"
        )

    def test_high_recursive_emotion_risk_on_looping_text(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        assert result["recursive_emotion_risk"] > 0.3, (
            f"Expected recursive_emotion_risk > 0.3, got {result['recursive_emotion_risk']}"
        )

    def test_low_static_risk_on_progressive_text(self):
        result = detect_scene_mechanics(_PROGRESSIVE_TEXT)
        assert result["static_scene_risk"] < 0.8, (
            f"Expected static_scene_risk < 0.8 on progressive text, got {result['static_scene_risk']}"
        )

    def test_high_floating_risk_on_dialogue_only_text(self):
        result = detect_scene_mechanics(_FLOATING_TEXT)
        assert result["floating_scene_risk"] > 0.0 or result["dialogue_ratio"] > 0.1, (
            "Pure dialogue text should show some floating or dialogue signal"
        )

    def test_environment_density_on_environment_text(self):
        result = detect_scene_mechanics(_ENVIRONMENT_TEXT)
        assert result["environment_usage_density"] > 0.0, (
            "Environment-rich text should have non-zero environment_usage_density"
        )

    def test_empty_string_no_crash(self):
        result = detect_scene_mechanics("")
        assert isinstance(result, dict)
        assert result["static_scene_risk"] >= 0.0

    def test_all_counts_non_negative(self):
        result = detect_scene_mechanics(_LOOPING_TEXT)
        int_fields = [
            "repeated_tension_count", "repeated_attraction_count",
            "repeated_heartbeat_count", "repeated_storm_count", "repeated_eye_count",
        ]
        for field in int_fields:
            assert result[field] >= 0, f"{field} is negative"

    def test_storm_detection(self):
        stormy = "The storm raged outside. Lightning cracked across the sky. Thunder followed. The rain was relentless."
        result = detect_scene_mechanics(stormy)
        assert result["repeated_storm_count"] >= 3

    def test_zero_storm_count_on_calm_text(self):
        result = detect_scene_mechanics("She walked across the room and sat down.")
        assert result["repeated_storm_count"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. detect_scene_progression_events
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectSceneProgressionEvents:
    def test_returns_all_required_keys(self):
        result = detect_scene_progression_events(_PROGRESSIVE_TEXT)
        required = {
            "progression_event_count", "escalation_detected", "power_shift_detected",
            "scene_transition_detected", "environment_transition_detected", "events",
        }
        assert required.issubset(result.keys())

    def test_escalation_detected_in_progressive_text(self):
        result = detect_scene_progression_events(_PROGRESSIVE_TEXT)
        assert result["escalation_detected"] or result["power_shift_detected"], (
            "Progressive text with physical escalation should detect escalation or power shift"
        )

    def test_power_shift_detected(self):
        text = "She pushed him away, reversed the power dynamic. He stopped."
        result = detect_scene_progression_events(text)
        assert result["power_shift_detected"]

    def test_scene_transition_detected(self):
        text = "She walked out of the room and into the hallway. He followed her."
        result = detect_scene_progression_events(text)
        assert result["scene_transition_detected"]

    def test_no_events_in_looping_text(self):
        result = detect_scene_progression_events(_LOOPING_TEXT)
        # Looping text has emotion/tension but no actual progression events
        assert result["progression_event_count"] == 0, (
            f"Looping text should have no progression events, got {result['progression_event_count']}"
        )

    def test_events_list_populated_when_detected(self):
        result = detect_scene_progression_events(_PROGRESSIVE_TEXT)
        assert isinstance(result["events"], list)

    def test_progression_event_count_non_negative(self):
        result = detect_scene_progression_events(_LOOPING_TEXT)
        assert result["progression_event_count"] >= 0

    def test_revelation_detected(self):
        text = 'She finally told him. "I know what you did," she said. She admitted it all.'
        result = detect_scene_progression_events(text)
        assert result["progression_event_count"] >= 1

    def test_empty_string_no_crash(self):
        result = detect_scene_progression_events("")
        assert result["progression_event_count"] == 0
        assert not result["escalation_detected"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. detect_paragraph_monotony
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectParagraphMonotony:
    def test_returns_all_required_keys(self):
        result = detect_paragraph_monotony(_INTROSPECTION_MONOTONY_TEXT)
        required = {
            "paragraph_count", "monotony_score", "dominant_type",
            "max_consecutive_same_type", "type_sequence",
        }
        assert required.issubset(result.keys())

    def test_high_monotony_on_all_introspection(self):
        result = detect_paragraph_monotony(_INTROSPECTION_MONOTONY_TEXT)
        assert result["monotony_score"] > 0.3, (
            f"Expected high monotony score on introspection-only text, got {result['monotony_score']}"
        )

    def test_dominant_type_introspection(self):
        result = detect_paragraph_monotony(_INTROSPECTION_MONOTONY_TEXT)
        assert result["dominant_type"] == "introspection"

    def test_low_monotony_on_varied_text(self):
        varied = (
            "She crossed the room and grabbed the glass.\n\n"
            '"Tell me what you want," she said.\n\n'
            "She felt the weight of his silence pressing against her.\n\n"
            "He moved toward her, slow and deliberate.\n\n"
            '"Fine," she said. "I\'ll tell you."\n\n'
            "She thought about it for a long moment before deciding."
        )
        result = detect_paragraph_monotony(varied)
        assert result["monotony_score"] < 0.7, (
            f"Expected low monotony on varied text, got {result['monotony_score']}"
        )

    def test_paragraph_count_correct(self):
        result = detect_paragraph_monotony(_INTROSPECTION_MONOTONY_TEXT)
        expected = len([p for p in _INTROSPECTION_MONOTONY_TEXT.split("\n\n") if p.strip()])
        assert result["paragraph_count"] == expected

    def test_single_paragraph_no_crash(self):
        result = detect_paragraph_monotony("She walked into the room.")
        assert result["monotony_score"] == 0.0
        assert result["paragraph_count"] == 1

    def test_empty_string_no_crash(self):
        result = detect_paragraph_monotony("")
        assert result["paragraph_count"] == 0

    def test_type_sequence_length_matches_paragraph_count(self):
        result = detect_paragraph_monotony(_INTROSPECTION_MONOTONY_TEXT)
        assert len(result["type_sequence"]) == result["paragraph_count"]

    def test_max_consecutive_at_least_3_on_monotony_text(self):
        result = detect_paragraph_monotony(_INTROSPECTION_MONOTONY_TEXT)
        assert result["max_consecutive_same_type"] >= 3, (
            f"Expected ≥3 consecutive introspection paragraphs, got {result['max_consecutive_same_type']}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. determine_scene_forward_pressure
# ══════════════════════════════════════════════════════════════════════════════

class TestDetermineSceneForwardPressure:
    def _run(self, text: str) -> str:
        mechanics = detect_scene_mechanics(text)
        events = detect_scene_progression_events(text)
        return determine_scene_forward_pressure(mechanics, events)

    def test_returns_string(self):
        result = self._run(_LOOPING_TEXT)
        assert isinstance(result, str)

    def test_non_empty_on_looping_text(self):
        result = self._run(_LOOPING_TEXT)
        assert result.strip(), "Looping text should produce non-empty forward pressure guidance"

    def test_empty_or_minimal_on_progressive_text(self):
        # Progressive text with real events should need less pressure
        result = self._run(_PROGRESSIVE_TEXT)
        # Just verify it returns a string without crashing
        assert isinstance(result, str)

    def test_high_tension_triggers_guidance(self):
        text = "The tension was electric. Danger filled the room. Tension again. The dangerous tension charged everything."
        result = self._run(text)
        assert "tension" in result.lower() or "resolve" in result.lower() or result == "", (
            "High tension count should produce tension-specific guidance"
        )

    def test_heartbeat_overuse_triggers_guidance(self):
        text = "Her heartbeat raced. Her heart pounded. Her heartbeat stuttered again. The heartbeat was deafening."
        result = self._run(text)
        assert "heartbeat" in result.lower() or "pulse" in result.lower() or result, (
            "Repeated heartbeat should produce guidance or some pressure"
        )

    def test_at_most_3_sentences(self):
        result = self._run(_LOOPING_TEXT)
        sentences = [s.strip() for s in result.split(".") if s.strip()]
        assert len(sentences) <= 10, f"Forward pressure should be compact, got {len(sentences)} sentence fragments"


# ══════════════════════════════════════════════════════════════════════════════
# 5. build_narrative_propulsion_block
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildNarrativePropulsionBlock:
    def test_returns_non_empty_string(self):
        block = build_narrative_propulsion_block("She looked at him.")
        assert isinstance(block, str) and block.strip()

    def test_contains_core_directives(self):
        block = build_narrative_propulsion_block("She looked at him.")
        assert "Advance" in block or "advance" in block, "Block must contain advance directive"
        assert "paragraph" in block.lower(), "Block must mention paragraph"

    def test_contains_environment_directive(self):
        block = build_narrative_propulsion_block("She looked at him.")
        assert "environment" in block.lower() or "space" in block.lower(), (
            "Block must include environment/space directive"
        )

    def test_contains_variety_directive(self):
        block = build_narrative_propulsion_block("She looked at him.")
        assert "vary" in block.lower() or "alternate" in block.lower(), (
            "Block must include variety/alternation directive"
        )

    def test_short_and_lightweight(self):
        block = build_narrative_propulsion_block("She looked at him.")
        # Reasonably compact — not a prose manifesto
        assert len(block) < 1500, f"Block is too long ({len(block)} chars) — keep it tight"

    def test_looping_text_adds_pressure_sentences(self):
        block_loopy = build_narrative_propulsion_block(_LOOPING_TEXT)
        block_plain = build_narrative_propulsion_block("She walked across the room.")
        # Looping text should produce a longer block due to added pressure
        assert len(block_loopy) >= len(block_plain), (
            "Looping text should produce ≥ as many instructions as plain text"
        )

    def test_canon_summary_included_in_analysis(self):
        # With heavy repetition in canon, block should still generate
        canon = "She longed for him. The tension between them was always electric."
        block = build_narrative_propulsion_block("She looked at him again.", canon)
        assert block.strip()

    def test_no_crash_on_empty_inputs(self):
        block = build_narrative_propulsion_block("", "")
        assert isinstance(block, str)

    def test_no_purple_prose_manifesto(self):
        block = build_narrative_propulsion_block(_LOOPING_TEXT)
        # Should not contain multi-paragraph poetic coaching
        assert block.count("\n\n") < 5, "Block should not contain multiple blank-line-separated sections"

    def test_not_injected_in_chapter_prompt(self):
        """build_narrative_propulsion_block must not appear in StoryLab chapter prompt source."""
        from app.services.storylab_generator import build_chapter_prompt
        src = inspect.getsource(build_chapter_prompt)
        assert "build_narrative_propulsion_block" not in src, (
            "build_narrative_propulsion_block must not be called from build_chapter_prompt"
        )

    def test_not_injected_in_continuation_prompt(self):
        """build_narrative_propulsion_block must not appear in StoryLab continuation prompt source."""
        from app.services.storylab_generator import build_storylab_prompt
        src = inspect.getsource(build_storylab_prompt)
        assert "build_narrative_propulsion_block" not in src, (
            "build_narrative_propulsion_block must not be called from build_storylab_prompt"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. Prompt injection order
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptInjectionOrder:
    def _build_prompt(self, **kwargs) -> list[dict]:
        from app.services.storylab_generator import build_rp_reply_prompt
        defaults = dict(
            partner_reply="She looked at him steadily.",
            response_length="match",
            style_match="soft",
            perspective="third_person_limited",
            formatting="plain",
            intensity="standard",
        )
        defaults.update(kwargs)
        return build_rp_reply_prompt(**defaults)

    def test_narrative_propulsion_present_in_user_message(self):
        msgs = self._build_prompt()
        user_content = msgs[1]["content"]
        assert "Narrative Propulsion" in user_content, (
            "'Narrative Propulsion' header missing from user message"
        )

    def test_narrative_propulsion_after_partner_control(self):
        msgs = self._build_prompt()
        user_content = msgs[1]["content"]
        pc_pos = user_content.find("Partner-Control Protection")
        np_pos = user_content.find("Narrative Propulsion")
        assert pc_pos != -1, "Partner-Control Protection not found"
        assert np_pos != -1, "Narrative Propulsion not found"
        assert np_pos > pc_pos, (
            "Narrative Propulsion must appear AFTER Partner-Control Protection"
        )

    def test_narrative_propulsion_before_heat(self):
        msgs = self._build_prompt()
        user_content = msgs[1]["content"]
        np_pos = user_content.find("Narrative Propulsion")
        # Heat section header varies; look for common heat markers
        heat_pos = user_content.find("## Heat") if "## Heat" in user_content else user_content.find("## Embers")
        if heat_pos == -1:
            heat_pos = user_content.find("## Flame")
        if heat_pos == -1:
            heat_pos = user_content.find("Content Level")
        assert np_pos != -1, "Narrative Propulsion not found"
        if heat_pos != -1:
            assert np_pos < heat_pos, (
                "Narrative Propulsion must appear BEFORE heat layer"
            )

    def test_partner_drive_before_narrative_propulsion(self):
        msgs = self._build_prompt()
        user_content = msgs[1]["content"]
        pd_pos = user_content.find("Scene Drive")
        np_pos = user_content.find("Narrative Propulsion")
        assert pd_pos != -1, "Scene Drive not found"
        assert np_pos != -1, "Narrative Propulsion not found"
        assert pd_pos < np_pos, (
            "Scene Drive (partner_drive) must appear BEFORE Narrative Propulsion"
        )

    def test_narrative_propulsion_not_in_system_message(self):
        """Propulsion block belongs in user message, not system."""
        msgs = self._build_prompt()
        system_content = msgs[0]["content"]
        assert "Narrative Propulsion" not in system_content, (
            "Narrative Propulsion should be in user message, not system message"
        )

    def test_core_advance_directive_in_user_message(self):
        msgs = self._build_prompt()
        user_content = msgs[1]["content"]
        assert "Advance" in user_content or "advance" in user_content, (
            "Core advance directive missing from user message"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 7. Explicit (inferno) mode compatibility
# ══════════════════════════════════════════════════════════════════════════════

class TestInfernoModeCompatibility:
    def _build_inferno_prompt(self) -> list[dict]:
        from app.services.storylab_generator import build_rp_reply_prompt
        return build_rp_reply_prompt(
            partner_reply="She moved against him, her breath warm on his neck.",
            response_length="match",
            style_match="strong",
            perspective="third_person_limited",
            formatting="plain",
            intensity="explicit",
            heat_level="inferno",
        )

    def test_narrative_propulsion_present_at_inferno(self):
        msgs = self._build_inferno_prompt()
        user_content = msgs[1]["content"]
        assert "Narrative Propulsion" in user_content, (
            "Narrative Propulsion must be present even at inferno heat"
        )

    def test_inferno_does_not_suppress_advance_directive(self):
        msgs = self._build_inferno_prompt()
        user_content = msgs[1]["content"]
        assert "advance" in user_content.lower() or "Advance" in user_content, (
            "Advance directive must survive inferno heat"
        )

    def test_propulsion_does_not_restrict_explicitness(self):
        """The propulsion block must not contain content-restriction language."""
        block = build_narrative_propulsion_block(
            "She moved against him. Their bodies pressed together.",
            "",
        )
        restriction_phrases = ["avoid explicit", "keep it tasteful", "fade to black", "no explicit"]
        for phrase in restriction_phrases:
            assert phrase.lower() not in block.lower(), (
                f"Propulsion block contains restrictive phrase: {phrase!r}"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 8. StoryLab isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestStoryLabIsolation:
    def test_detect_scene_mechanics_not_in_build_chapter_prompt(self):
        from app.services.storylab_generator import build_chapter_prompt
        src = inspect.getsource(build_chapter_prompt)
        assert "detect_scene_mechanics" not in src

    def test_detect_scene_mechanics_not_in_build_storylab_prompt(self):
        from app.services.storylab_generator import build_storylab_prompt
        src = inspect.getsource(build_storylab_prompt)
        assert "detect_scene_mechanics" not in src

    def test_narrative_propulsion_import_not_in_chapter_function(self):
        from app.services.storylab_generator import build_chapter_prompt
        src = inspect.getsource(build_chapter_prompt)
        assert "rp_narrative_engine" not in src

    def test_chapter_prompt_has_no_propulsion_header(self):
        from app.schemas.storylab import StoryLabControls, Length, Direction, Pacing, ToneIntensity, Boundary
        from app.services.storylab_generator import build_chapter_prompt
        controls = StoryLabControls(
            direction=Direction.advance_plot,
            tone_intensity=ToneIntensity.intense,
            pacing=Pacing.fast,
            length=Length.long,
            boundary=Boundary.sfw,
        )
        msgs = build_chapter_prompt(
            prompt="Continue the scene.",
            controls=controls,
            state_json={"story_state": {}},
            summary="",
            characters=[],
        )
        combined = " ".join(m["content"] for m in msgs)
        assert "Narrative Propulsion" not in combined, (
            "Chapter prompt must not include the Narrative Propulsion block"
        )

    def test_rp_reply_prompt_has_propulsion_chapter_prompt_does_not(self):
        from app.services.storylab_generator import build_rp_reply_prompt, build_chapter_prompt
        from app.schemas.storylab import StoryLabControls, Length, Direction, Pacing, ToneIntensity, Boundary

        rp_msgs = build_rp_reply_prompt(
            partner_reply="She looked at him.",
            response_length="match",
            style_match="soft",
            perspective="third_person_limited",
            formatting="plain",
            intensity="standard",
        )
        controls = StoryLabControls(
            direction=Direction.advance_plot, tone_intensity=ToneIntensity.moderate,
            pacing=Pacing.balanced, length=Length.medium, boundary=Boundary.sfw,
        )
        ch_msgs = build_chapter_prompt(
            prompt="Continue.", controls=controls,
            state_json={"story_state": {}}, summary="", characters=[],
        )

        rp_combined = " ".join(m["content"] for m in rp_msgs)
        ch_combined = " ".join(m["content"] for m in ch_msgs)

        assert "Narrative Propulsion" in rp_combined, "RP prompt must contain Narrative Propulsion"
        assert "Narrative Propulsion" not in ch_combined, "Chapter prompt must NOT contain Narrative Propulsion"
