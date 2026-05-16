"""Tests for the RP Style Engine: prose layer injection, archetype routing,
repetition detection, continuity preservation, and escalation story layering."""
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

_LENNOX_REPLY = (
    "||Lennox hadn't moved from the doorway. She stood with one shoulder against the frame, "
    "arms loose at her sides — the pose of someone who had made peace with waiting, "
    "or at least learned to look like it.||\n\n"
    '"You keep saying that," she said. Her voice was level. Not cold. Just even. '
    '"You keep saying it like it means something different every time."\n\n'
    "||She watched him. Not looking for a reaction — just watching. "
    "The way you watch a fire to see which way the smoke is going.||"
)

_STORM_SCENE = (
    "The rain was relentless against the stone windows. "
    "Lennox stood in the doorway, the shadow of the arch cutting across her face. "
    "The candle on the sill had gone out ten minutes ago.\n\n"
    '"You came back," she said. Not a question. '
    "Her eyes moved from the door to the dark behind it, then back to him."
)

_REPETITIVE_REPLY = (
    "He moved toward her. He turned to the window. He looked at her hands. "
    "He moved to the door. He turned back. He looked at her face. He moved again. "
    "She ached. She yearned. She ached for him. He ached. She ached still."
)

_MECHANICAL_REPLY = (
    "He sat down. She stood up. He looked. She moved. He reached. She stepped. "
    "He grabbed. She turned. He pulled. She stopped. He waited. She walked."
)


# ── Phase 1: Dark romance prose layer ────────────────────────────────────────

def test_dark_romance_prose_layer_is_string():
    from app.services.rp_style_engine import DARK_ROMANCE_PROSE_LAYER
    assert isinstance(DARK_ROMANCE_PROSE_LAYER, str)
    assert len(DARK_ROMANCE_PROSE_LAYER) > 100


def test_dark_romance_prose_layer_contains_key_concepts():
    from app.services.rp_style_engine import DARK_ROMANCE_PROSE_LAYER
    text = DARK_ROMANCE_PROSE_LAYER.lower()
    for concept in ("emotional tension", "atmosphere", "restraint", "obsession", "pacing"):
        assert concept in text, f"'{concept}' missing from DARK_ROMANCE_PROSE_LAYER"


# ── Phase 2: Escalation story layer ──────────────────────────────────────────

def test_escalation_story_layer_is_string():
    from app.services.rp_style_engine import ESCALATION_STORY_LAYER
    assert isinstance(ESCALATION_STORY_LAYER, str)
    assert len(ESCALATION_STORY_LAYER) > 50


def test_escalation_story_layer_mentions_earned_escalation():
    from app.services.rp_style_engine import ESCALATION_STORY_LAYER
    assert "earned" in ESCALATION_STORY_LAYER.lower()


def test_escalation_story_layer_mentions_continuation_space():
    from app.services.rp_style_engine import ESCALATION_STORY_LAYER
    text = ESCALATION_STORY_LAYER.lower()
    assert "continuation" in text or "collaborative" in text


# ── Phase 3: Style archetypes ─────────────────────────────────────────────────

def test_rp_style_archetypes_has_five_entries():
    from app.services.rp_style_engine import RP_STYLE_ARCHETYPES
    assert len(RP_STYLE_ARCHETYPES) == 5


def test_rp_style_archetypes_contains_all_expected():
    from app.services.rp_style_engine import RP_STYLE_ARCHETYPES
    expected = {
        "cinematic_dark_romance",
        "gothic_obsession",
        "slow_burn_tension",
        "dangerous_devotion",
        "primal_restraint",
    }
    assert RP_STYLE_ARCHETYPES == expected


def test_get_archetype_prompt_block_returns_string_for_each():
    from app.services.rp_style_engine import RP_STYLE_ARCHETYPES, get_archetype_prompt_block
    for archetype in RP_STYLE_ARCHETYPES:
        block = get_archetype_prompt_block(archetype)
        assert isinstance(block, str), f"Archetype '{archetype}' returned non-string"
        assert len(block) > 50, f"Archetype '{archetype}' prompt block too short"


def test_get_archetype_prompt_block_falls_back_for_unknown():
    from app.services.rp_style_engine import get_archetype_prompt_block, DEFAULT_ARCHETYPE, get_archetype_config
    result = get_archetype_prompt_block("not_a_real_archetype")
    default = get_archetype_config(DEFAULT_ARCHETYPE)["prompt_block"]
    assert result == default


def test_default_archetype_is_cinematic_dark_romance():
    from app.services.rp_style_engine import DEFAULT_ARCHETYPE
    assert DEFAULT_ARCHETYPE == "cinematic_dark_romance"


def test_each_archetype_has_distinct_prompt_block():
    from app.services.rp_style_engine import RP_STYLE_ARCHETYPES, get_archetype_prompt_block
    blocks = [get_archetype_prompt_block(a) for a in sorted(RP_STYLE_ARCHETYPES)]
    # All blocks should be unique
    assert len(set(blocks)) == len(blocks), "Two archetypes share the same prompt block"


def test_build_style_layer_combines_all_layers():
    from app.services.rp_style_engine import (
        build_style_layer, DARK_ROMANCE_PROSE_LAYER, ESCALATION_STORY_LAYER,
    )
    combined = build_style_layer("cinematic_dark_romance")
    assert DARK_ROMANCE_PROSE_LAYER in combined
    assert ESCALATION_STORY_LAYER in combined


def test_build_style_layer_includes_archetype_block():
    from app.services.rp_style_engine import build_style_layer, get_archetype_prompt_block
    for archetype in ("gothic_obsession", "primal_restraint", "slow_burn_tension"):
        combined = build_style_layer(archetype)
        archetype_block = get_archetype_prompt_block(archetype)
        assert archetype_block in combined, f"Archetype block for '{archetype}' missing from combined layer"


def test_build_style_layer_defaults_to_cinematic_dark_romance():
    from app.services.rp_style_engine import build_style_layer, get_archetype_prompt_block, DEFAULT_ARCHETYPE
    default_combined = build_style_layer()
    explicit_combined = build_style_layer(DEFAULT_ARCHETYPE)
    assert default_combined == explicit_combined


# ── Phase 4: Repetition detection ─────────────────────────────────────────────

def test_detect_generic_cadence_returns_expected_keys():
    from app.services.rp_style_engine import detect_generic_cadence
    result = detect_generic_cadence(_LENNOX_REPLY)
    expected = {"warnings", "generic_cadence_risk", "prose_repetition_detected", "emotional_flattening_risk"}
    assert set(result.keys()) == expected


def test_detect_generic_cadence_clean_prose_has_no_warnings():
    from app.services.rp_style_engine import detect_generic_cadence
    result = detect_generic_cadence(_LENNOX_REPLY)
    assert not result["generic_cadence_risk"]
    assert not result["prose_repetition_detected"]
    assert not result["emotional_flattening_risk"]
    assert result["warnings"] == []


def test_detect_generic_cadence_repetitive_reply_flags_repetition():
    from app.services.rp_style_engine import detect_generic_cadence
    result = detect_generic_cadence(_REPETITIVE_REPLY)
    # Should catch action verb repetition and/or emotional word repetition
    assert result["prose_repetition_detected"] or result["emotional_flattening_risk"] or result["generic_cadence_risk"]
    assert len(result["warnings"]) > 0


def test_detect_generic_cadence_mechanical_reply_flags_generic_cadence():
    from app.services.rp_style_engine import detect_generic_cadence
    result = detect_generic_cadence(_MECHANICAL_REPLY)
    assert result["generic_cadence_risk"]


def test_detect_generic_cadence_warnings_are_strings():
    from app.services.rp_style_engine import detect_generic_cadence
    result = detect_generic_cadence(_REPETITIVE_REPLY)
    for w in result["warnings"]:
        assert isinstance(w, str)


def test_detect_generic_cadence_warning_keywords():
    from app.services.rp_style_engine import detect_generic_cadence
    result = detect_generic_cadence(_REPETITIVE_REPLY)
    combined = " ".join(result["warnings"]).lower()
    # At least one of the expected warning keywords should appear
    assert any(kw in combined for kw in ("repetition", "cadence", "flattening"))


def test_detect_generic_cadence_empty_string_no_crash():
    from app.services.rp_style_engine import detect_generic_cadence
    result = detect_generic_cadence("")
    assert isinstance(result["warnings"], list)
    assert isinstance(result["generic_cadence_risk"], bool)


def test_detect_generic_cadence_emotion_word_repetition():
    from app.services.rp_style_engine import detect_generic_cadence
    # 4x "ached" in short text should trigger emotional flattening
    text = "She ached. He ached. They both ached. She ached again. He wanted, ached, burned."
    result = detect_generic_cadence(text)
    assert result["emotional_flattening_risk"]


def test_detect_generic_cadence_action_verb_repetition():
    from app.services.rp_style_engine import detect_generic_cadence
    text = "He moved to the door. He moved to the window. She moved away. He moved again."
    result = detect_generic_cadence(text)
    assert result["prose_repetition_detected"] or result["generic_cadence_risk"]


# ── Phase 5: Scene continuity preservation ───────────────────────────────────

def test_maintain_scene_continuity_returns_expected_keys():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    expected = {
        "environment", "environment_terms", "tension_state",
        "physical_positioning", "continuity_prompt", "floating_scene_risk",
    }
    assert set(result.keys()) == expected


def test_maintain_scene_continuity_detects_weather():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert "weather" in result["environment"]


def test_maintain_scene_continuity_detects_architecture():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert "architecture" in result["environment"]


def test_maintain_scene_continuity_detects_light():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert "light" in result["environment"]


def test_maintain_scene_continuity_environment_terms_not_empty_for_rich_scene():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert len(result["environment_terms"]) > 0


def test_maintain_scene_continuity_generates_continuity_prompt():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert isinstance(result["continuity_prompt"], str)
    assert len(result["continuity_prompt"]) > 20


def test_maintain_scene_continuity_continuity_prompt_mentions_environment():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert "environment" in result["continuity_prompt"].lower() or "scene" in result["continuity_prompt"].lower()


def test_maintain_scene_continuity_detects_tension_state():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert result["tension_state"] in ("coiled", "charged", "breaking", "neutral")


def test_maintain_scene_continuity_detects_physical_positioning():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE)
    assert isinstance(result["physical_positioning"], list)
    # "doorway" is in the storm scene
    assert len(result["physical_positioning"]) > 0


def test_maintain_scene_continuity_floating_scene_detected():
    from app.services.rp_style_engine import maintain_scene_continuity
    # Prior context has rich environment; partner reply has none
    prior = "The rain beat against the stone wall. The candle flickered in the dark shadows."
    bare_reply = "She looked at him. He said nothing."
    result = maintain_scene_continuity(bare_reply, prior_context=prior)
    assert result["floating_scene_risk"] is True


def test_maintain_scene_continuity_no_floating_when_both_rich():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity(_STORM_SCENE, prior_context=_STORM_SCENE)
    assert result["floating_scene_risk"] is False


def test_maintain_scene_continuity_empty_reply_no_crash():
    from app.services.rp_style_engine import maintain_scene_continuity
    result = maintain_scene_continuity("")
    assert isinstance(result["environment"], list)
    assert result["tension_state"] in ("coiled", "charged", "breaking", "neutral")


# ── Escalation story layering (integration) ───────────────────────────────────

def test_build_style_layer_contains_escalation_layer():
    from app.services.rp_style_engine import build_style_layer, ESCALATION_STORY_LAYER
    layer = build_style_layer("slow_burn_tension")
    assert ESCALATION_STORY_LAYER in layer


def test_escalation_layer_mentions_stages():
    from app.services.rp_style_engine import ESCALATION_STORY_LAYER
    text = ESCALATION_STORY_LAYER.lower()
    stages = ["tension", "touch", "intimacy", "vulnerability"]
    for stage in stages:
        assert stage in text, f"'{stage}' missing from ESCALATION_STORY_LAYER"


# ── Warning generation integration ────────────────────────────────────────────

def test_detect_generic_cadence_warning_generation_for_each_risk_type():
    from app.services.rp_style_engine import detect_generic_cadence

    # Emotional flattening risk
    emotional_text = "She ached for him. She yearned. She ached still. He burned. She ached."
    r1 = detect_generic_cadence(emotional_text)
    assert r1["emotional_flattening_risk"]
    assert any("flattening" in w.lower() for w in r1["warnings"])

    # Generic cadence risk (all mechanical short sentences)
    mechanical_text = " ".join(["He moved. She turned. He looked. She stepped. He reached. She stopped. He moved. She turned. He looked."])
    r2 = detect_generic_cadence(mechanical_text)
    assert r2["generic_cadence_risk"] or r2["prose_repetition_detected"]
    assert len(r2["warnings"]) > 0


# ── Archetype prompt block content spot-checks ────────────────────────────────

def test_gothic_obsession_mentions_darkness():
    from app.services.rp_style_engine import get_archetype_prompt_block
    block = get_archetype_prompt_block("gothic_obsession").lower()
    assert any(word in block for word in ("dark", "shadow", "obsession", "fixation", "haunted"))


def test_slow_burn_mentions_withholding():
    from app.services.rp_style_engine import get_archetype_prompt_block
    block = get_archetype_prompt_block("slow_burn_tension").lower()
    assert any(word in block for word in ("withhold", "restrain", "silence", "almost", "deferred"))


def test_dangerous_devotion_mentions_possessiveness():
    from app.services.rp_style_engine import get_archetype_prompt_block
    block = get_archetype_prompt_block("dangerous_devotion").lower()
    assert any(word in block for word in ("possess", "devotion", "dangerous", "obsess", "protect"))


def test_primal_restraint_mentions_control():
    from app.services.rp_style_engine import get_archetype_prompt_block
    block = get_archetype_prompt_block("primal_restraint").lower()
    assert any(word in block for word in ("control", "restrain", "coiled", "primal", "edge"))


# ── Orchestration Stabilization V1: detect_ai_cadence ────────────────────────

def test_detect_ai_cadence_returns_expected_keys():
    from app.services.rp_style_engine import detect_ai_cadence
    result = detect_ai_cadence("He moved toward her.")
    expected = {"warnings", "ai_cadence_risk", "breath_gaze_density", "possession_loop_risk", "rhythm_monotone_risk"}
    assert set(result.keys()) == expected


def test_detect_ai_cadence_clean_reply_no_possession_risk():
    from app.services.rp_style_engine import detect_ai_cadence
    clean = (
        "||He crossed the room without a word. Set the glass on the sill "
        "and kept the window between them.||\n\n"
        '"I heard you," he said.\n\n'
        "||He turned. The distance felt deliberate.||"
    )
    result = detect_ai_cadence(clean)
    assert result["breath_gaze_density"] < 0.5
    assert result["possession_loop_risk"] is False


def test_detect_ai_cadence_breath_gaze_density_high_triggers_risk():
    from app.services.rp_style_engine import detect_ai_cadence
    gaze_heavy = (
        "His eyes met hers. Her breath caught. He gazed into her face. "
        "Her breath hitched again. His gaze darkened. She shivered. "
        "Her breathing came faster. He held her gaze. She shuddered."
    )
    result = detect_ai_cadence(gaze_heavy)
    assert result["breath_gaze_density"] > 0.0
    assert result["ai_cadence_risk"] is True


def test_detect_ai_cadence_possession_loop_triggers_risk():
    from app.services.rp_style_engine import detect_ai_cadence
    possessive = (
        '"You\'re mine," he said. His voice dropped. '
        '"You\'re mine — do you understand that?" '
        "||She belonged to him.||"
    )
    result = detect_ai_cadence(possessive)
    assert result["possession_loop_risk"] is True
    assert result["ai_cadence_risk"] is True


def test_detect_ai_cadence_rhythm_monotone_repeated_opener():
    from app.services.rp_style_engine import detect_ai_cadence
    monotone = (
        "He moved toward her.\n\n"
        "He turned to the window.\n\n"
        "He reached for the glass.\n\n"
        "He looked at her finally."
    )
    result = detect_ai_cadence(monotone)
    assert result["rhythm_monotone_risk"] is True


def test_detect_ai_cadence_warnings_are_strings():
    from app.services.rp_style_engine import detect_ai_cadence
    heavy = "His eyes met hers. Her breath caught. He gazed. She shivered. Breath hitched. His gaze fixed."
    result = detect_ai_cadence(heavy)
    for w in result["warnings"]:
        assert isinstance(w, str)


def test_detect_ai_cadence_density_in_range():
    from app.services.rp_style_engine import detect_ai_cadence
    result = detect_ai_cadence("Any text here.")
    assert 0.0 <= result["breath_gaze_density"] <= 1.0


def test_detect_ai_cadence_empty_string_no_crash():
    from app.services.rp_style_engine import detect_ai_cadence
    result = detect_ai_cadence("")
    assert isinstance(result["warnings"], list)
    assert isinstance(result["ai_cadence_risk"], bool)
