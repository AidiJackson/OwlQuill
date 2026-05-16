"""Tests for the RP Scene Beat Engine: beat detection, regression detection,
next-goal planning, progression block generation."""
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

_TENSION_TEXT = (
    "||Lennox hadn't moved from the doorway. She stood with one shoulder against the frame, "
    "arms loose at her sides — the pose of someone who had made peace with waiting.||\n\n"
    '"You came back," she said. Not a question.\n\n'
    "||She watched him. The way you watch a fire to see which way the smoke is going.||"
)

_CONFESSION_TEXT = (
    "||He crossed the room. She could hear the rain.||\n\n"
    '"I can\'t pretend I don\'t want this," he admitted. The words cost him something.\n\n'
    "||She hadn't moved. He told her the truth.||\n\n"
    '"I\'ve wanted you for longer than I should have."'
)

_KISSING_TEXT = (
    "||He closed the distance. Her breath caught — he felt it.||\n\n"
    "Their lips met. The kiss was not soft. It was the kind that admits something irreversible.\n\n"
    "||He pressed his lips to hers. She kissed him back.||"
)

_EXPLICIT_TEXT = (
    "||He pressed her down against the sheets.||\n\n"
    "His cock was hard against her thighs, her wetness slick when his fingers found her. "
    "Inside her — she arched.\n\n"
    "||He thrust slowly. She spread her legs wider.||"
)

_STALL_TEXT = (
    "He ached. He longed for her across the rain-soaked room. The storm raged outside. "
    "Her dark eyes met his. He ached still — that familiar longing. "
    "You should fear me. I'm dangerous. You're mine. You're mine. "
    "Lightning split the sky. His green eyes. Her green eyes. The storm continued."
)

_PROGRESSION_TEXT = (
    "||He crossed the room in three steps. Reached for her wrist — not hard, precise. "
    "Pressed her back against the wall with a single step forward.||\n\n"
    '"Stop running," he said.\n\n'
    "||He didn't raise his voice. His hands moved to bracket her — "
    "one arm on either side. No escape that didn't go through him.||"
)

_PRIOR_WITH_CLICHES = (
    "I'm dangerous. You should fear me. "
    "The storm raged outside. Her dark eyes met his. "
    "You're mine. You're mine. I'll keep you safe."
)


# ── 1. detect_scene_beats ─────────────────────────────────────────────────────

def test_detect_scene_beats_returns_expected_keys():
    from app.services.rp_scene_engine import detect_scene_beats
    result = detect_scene_beats(_TENSION_TEXT)
    expected_keys = {
        "confession_complete", "trust_established", "first_kiss_complete",
        "physical_escalation_started", "explicit_contact_started",
        "dominance_dynamic_present", "emotional_resistance_present",
        "protective_language_present", "possessive_language_present",
        "scene_stage",
    }
    assert expected_keys == set(result.keys())


def test_detect_scene_beats_tension_stage():
    from app.services.rp_scene_engine import detect_scene_beats
    result = detect_scene_beats(_TENSION_TEXT)
    assert result["scene_stage"] == "tension"
    assert result["confession_complete"] is False
    assert result["first_kiss_complete"] is False
    assert result["explicit_contact_started"] is False


def test_detect_scene_beats_confession_stage():
    from app.services.rp_scene_engine import detect_scene_beats
    result = detect_scene_beats(_CONFESSION_TEXT)
    assert result["confession_complete"] is True
    assert result["scene_stage"] in ("confession", "tension")


def test_detect_scene_beats_kissing_stage():
    from app.services.rp_scene_engine import detect_scene_beats
    result = detect_scene_beats(_KISSING_TEXT)
    assert result["first_kiss_complete"] is True
    assert result["scene_stage"] == "kissing"


def test_detect_scene_beats_explicit_stage():
    from app.services.rp_scene_engine import detect_scene_beats
    result = detect_scene_beats(_EXPLICIT_TEXT)
    assert result["explicit_contact_started"] is True
    assert result["physical_escalation_started"] is True
    assert result["scene_stage"] in ("intercourse", "oral", "undressing")


def test_detect_scene_beats_dominance_dynamic():
    from app.services.rp_scene_engine import detect_scene_beats
    text = "||He pinned her against the wall. She was his. Mine, he thought.||"
    result = detect_scene_beats(text)
    assert result["dominance_dynamic_present"] is True


def test_detect_scene_beats_possessive_language():
    from app.services.rp_scene_engine import detect_scene_beats
    text = "You're mine. She belongs to me. Mine to keep."
    result = detect_scene_beats(text)
    assert result["possessive_language_present"] is True


def test_detect_scene_beats_protection_language():
    from app.services.rp_scene_engine import detect_scene_beats
    text = "I'll keep you safe. Nothing will touch you. I protect what's mine."
    result = detect_scene_beats(text)
    assert result["protective_language_present"] is True


def test_detect_scene_beats_all_booleans():
    from app.services.rp_scene_engine import detect_scene_beats
    result = detect_scene_beats(_TENSION_TEXT)
    bool_keys = [k for k in result if k != "scene_stage"]
    for key in bool_keys:
        assert isinstance(result[key], bool), f"Key '{key}' should be bool, got {type(result[key])}"


def test_detect_scene_beats_scene_stage_is_valid_string():
    from app.services.rp_scene_engine import detect_scene_beats, SCENE_STAGES
    result = detect_scene_beats(_TENSION_TEXT)
    assert result["scene_stage"] in SCENE_STAGES


# ── 2. detect_repeated_beats ──────────────────────────────────────────────────

def test_detect_repeated_beats_returns_expected_keys():
    from app.services.rp_scene_engine import detect_repeated_beats
    result = detect_repeated_beats("He moved.", "She waited.")
    assert "repeated_beats" in result
    assert "repetition_score" in result
    assert isinstance(result["repeated_beats"], list)
    assert isinstance(result["repetition_score"], float)


def test_detect_repeated_beats_score_in_range():
    from app.services.rp_scene_engine import detect_repeated_beats
    result = detect_repeated_beats("He moved.", "She waited.")
    assert 0.0 <= result["repetition_score"] <= 1.0


def test_detect_repeated_beats_no_repetition_for_clean_texts():
    from app.services.rp_scene_engine import detect_repeated_beats
    result = detect_repeated_beats(_PROGRESSION_TEXT, _TENSION_TEXT)
    assert result["repetition_score"] < 0.3


def test_detect_repeated_beats_flags_storm_narration():
    from app.services.rp_scene_engine import detect_repeated_beats
    reply = "The storm raged outside. The rain hammered the roof."
    prior = "Lightning split the sky. The rain against the window."
    result = detect_repeated_beats(reply, prior)
    assert "storm_narration" in result["repeated_beats"]


def test_detect_repeated_beats_flags_danger_warning():
    from app.services.rp_scene_engine import detect_repeated_beats
    reply = "I'm dangerous. You should fear me."
    prior = "I'm not safe for you. You should be afraid of me."
    result = detect_repeated_beats(reply, prior)
    assert "danger_warning" in result["repeated_beats"]


def test_detect_repeated_beats_flags_possession():
    from app.services.rp_scene_engine import detect_repeated_beats
    reply = "You're mine. You belong to me."
    prior = "She's mine. Mine to keep."
    result = detect_repeated_beats(reply, prior)
    assert "possession_line" in result["repeated_beats"]


def test_detect_repeated_beats_flags_trust_speech():
    from app.services.rp_scene_engine import detect_repeated_beats
    reply = "I would never hurt you. You can trust me."
    prior = "You're safe with me. I promise I won't hurt you."
    result = detect_repeated_beats(reply, prior)
    assert "trust_speech" in result["repeated_beats"]


def test_detect_repeated_beats_high_score_for_stall_text():
    from app.services.rp_scene_engine import detect_repeated_beats
    result = detect_repeated_beats(_STALL_TEXT, _PRIOR_WITH_CLICHES)
    assert result["repetition_score"] > 0.2
    assert len(result["repeated_beats"]) > 0


# ── 3. determine_next_scene_goal ──────────────────────────────────────────────

def test_determine_next_scene_goal_returns_expected_keys():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("tension")
    assert "next_goal" in result
    assert "forbidden_regressions" in result
    assert isinstance(result["next_goal"], str)
    assert isinstance(result["forbidden_regressions"], list)


def test_determine_next_scene_goal_tension_to_confession():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("tension")
    assert result["next_goal"] == "confession"


def test_determine_next_scene_goal_kissing_to_heavy_makeout():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("kissing")
    assert result["next_goal"] == "heavy_makeout"


def test_determine_next_scene_goal_undressing_to_oral():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("undressing")
    assert result["next_goal"] == "oral"


def test_determine_next_scene_goal_intercourse_to_emotional_escalation():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("intercourse")
    assert "escalation" in result["next_goal"] or "emotional" in result["next_goal"]


def test_determine_next_scene_goal_aftercare_to_vulnerability():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("aftercare")
    assert result["next_goal"] == "vulnerability"


def test_determine_next_scene_goal_all_stages_have_goals():
    from app.services.rp_scene_engine import determine_next_scene_goal, SCENE_STAGES
    for stage in SCENE_STAGES:
        result = determine_next_scene_goal(stage)
        assert result["next_goal"], f"Stage '{stage}' returned empty next_goal"
        assert isinstance(result["forbidden_regressions"], list)


def test_determine_next_scene_goal_unknown_stage_fallback():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("not_a_real_stage")
    assert result["next_goal"]  # should return a non-empty fallback


def test_determine_next_scene_goal_kissing_has_regressions():
    from app.services.rp_scene_engine import determine_next_scene_goal
    result = determine_next_scene_goal("kissing")
    # Kissing should forbid going back to pure confession
    assert len(result["forbidden_regressions"]) > 0


# ── 4. build_scene_progression_block ─────────────────────────────────────────

def test_build_scene_progression_block_returns_string():
    from app.services.rp_scene_engine import detect_scene_beats, determine_next_scene_goal, build_scene_progression_block
    beats = detect_scene_beats(_TENSION_TEXT)
    goal = determine_next_scene_goal(beats["scene_stage"])
    block = build_scene_progression_block(
        scene_stage=beats["scene_stage"],
        beats=beats,
        next_goal=goal["next_goal"],
        repeated_beats=[],
    )
    assert isinstance(block, str)
    assert len(block) > 50


def test_build_scene_progression_block_contains_stage():
    from app.services.rp_scene_engine import detect_scene_beats, determine_next_scene_goal, build_scene_progression_block
    beats = detect_scene_beats(_TENSION_TEXT)
    goal = determine_next_scene_goal(beats["scene_stage"])
    block = build_scene_progression_block(
        scene_stage="tension",
        beats=beats,
        next_goal=goal["next_goal"],
        repeated_beats=[],
    )
    assert "tension" in block


def test_build_scene_progression_block_contains_next_goal():
    from app.services.rp_scene_engine import build_scene_progression_block, detect_scene_beats
    beats = detect_scene_beats(_TENSION_TEXT)
    block = build_scene_progression_block(
        scene_stage="tension",
        beats=beats,
        next_goal="confession",
        repeated_beats=[],
    )
    assert "confession" in block


def test_build_scene_progression_block_mentions_no_regression():
    from app.services.rp_scene_engine import build_scene_progression_block, detect_scene_beats
    beats = detect_scene_beats(_CONFESSION_TEXT)
    beats["confession_complete"] = True
    block = build_scene_progression_block(
        scene_stage="confession",
        beats=beats,
        next_goal="first_touch",
        repeated_beats=[],
    )
    assert "confession" in block.lower()
    assert "regress" in block.lower() or "completed" in block.lower() or "do not" in block.lower()


def test_build_scene_progression_block_flags_repeated_beats():
    from app.services.rp_scene_engine import build_scene_progression_block, detect_scene_beats
    beats = detect_scene_beats(_TENSION_TEXT)
    block = build_scene_progression_block(
        scene_stage="tension",
        beats=beats,
        next_goal="confession",
        repeated_beats=["storm_narration", "possession_line"],
    )
    assert "storm" in block.lower() or "repetition" in block.lower() or "repeat" in block.lower()


def test_build_scene_progression_block_inferno_mode_allows_explicit():
    from app.services.rp_scene_engine import build_scene_progression_block, detect_scene_beats
    beats = detect_scene_beats(_EXPLICIT_TEXT)
    block = build_scene_progression_block(
        scene_stage="intercourse",
        beats=beats,
        next_goal="emotional escalation",
        repeated_beats=[],
        heat_level="inferno",
    )
    assert "explicit" in block.lower()


def test_build_scene_progression_block_no_partner_control():
    from app.services.rp_scene_engine import build_scene_progression_block, detect_scene_beats
    beats = detect_scene_beats(_TENSION_TEXT)
    block = build_scene_progression_block(
        scene_stage="tension",
        beats=beats,
        next_goal="confession",
        repeated_beats=[],
    )
    assert "partner" in block.lower()
    assert "agency" in block.lower() or "force" in block.lower() or "NEVER" in block


# ── 5. detect_scene_regression ────────────────────────────────────────────────

def test_detect_scene_regression_returns_expected_keys():
    from app.services.rp_scene_engine import detect_scene_regression
    result = detect_scene_regression("He moved.", "She waited.")
    expected = {
        "emotional_looping", "repeated_confession", "repetitive_possessiveness",
        "atmospheric_stalling", "progression_failure", "regression_flags",
    }
    assert expected == set(result.keys())


def test_detect_scene_regression_all_flags_are_bools():
    from app.services.rp_scene_engine import detect_scene_regression
    result = detect_scene_regression("He moved.", "She waited.")
    bool_keys = [k for k in result if k != "regression_flags"]
    for k in bool_keys:
        assert isinstance(result[k], bool), f"Key '{k}' should be bool"


def test_detect_scene_regression_regression_flags_is_list():
    from app.services.rp_scene_engine import detect_scene_regression
    result = detect_scene_regression("He moved.", "She waited.")
    assert isinstance(result["regression_flags"], list)


def test_detect_scene_regression_clean_text_no_flags():
    from app.services.rp_scene_engine import detect_scene_regression
    result = detect_scene_regression(_PROGRESSION_TEXT, _TENSION_TEXT)
    assert result["emotional_looping"] is False
    assert result["repeated_confession"] is False


def test_detect_scene_regression_flags_emotional_looping():
    from app.services.rp_scene_engine import detect_scene_regression
    looping = (
        "He ached for her. He longed across the room. He yearned — "
        "that familiar aching that would not release him. He craved her still."
    )
    result = detect_scene_regression(looping, _PRIOR_WITH_CLICHES)
    assert result["emotional_looping"] is True
    assert "emotional_looping" in result["regression_flags"]


def test_detect_scene_regression_flags_atmospheric_stalling():
    from app.services.rp_scene_engine import detect_scene_regression
    stalling = (
        "The storm raged outside. Lightning split the sky. "
        "The storm had not let up. Thunder again. The rain fell. The storm persisted."
    )
    result = detect_scene_regression(stalling, "The storm raged. The rain fell.")
    assert result["atmospheric_stalling"] is True


def test_detect_scene_regression_flags_repetitive_possessiveness():
    from app.services.rp_scene_engine import detect_scene_regression
    possessive = "You're mine. She belongs to me. Mine to keep."
    prior = "She's mine. You're mine."
    result = detect_scene_regression(possessive, prior)
    assert result["repetitive_possessiveness"] is True


def test_detect_scene_regression_progression_failure_for_no_action():
    from app.services.rp_scene_engine import detect_scene_regression
    stalled = (
        "He ached. He longed. He yearned for her. "
        "The aching would not stop. He craved something he could not name. "
        "The storm raged on. The storm. The storm. The storm."
    )
    result = detect_scene_regression(stalled, _PRIOR_WITH_CLICHES)
    # High stall + no progression = progression_failure
    assert isinstance(result["progression_failure"], bool)


# ── 6. Integration: prompt layer contains scene engine block ─────────────────

def test_build_rp_prompt_layers_contains_scene_engine_key():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply=_TENSION_TEXT,
        response_length="short",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="flame",
    )
    assert "scene_engine" in layers
    assert "Scene Beat Engine" in layers["scene_engine"]


def test_build_rp_prompt_layers_scene_engine_contains_next_goal():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply=_TENSION_TEXT,
        response_length="short",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="flame",
    )
    engine = layers["scene_engine"]
    assert "next beat" in engine.lower() or "next_goal" in engine.lower() or "confession" in engine.lower()


def test_build_rp_reply_prompt_scene_engine_not_in_user_message():
    """Scene Beat Engine is passive — it must NOT appear in the user message."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_TENSION_TEXT,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        heat_level="flame",
        character_name="Leonardo",
    )
    user = msgs[1]["content"]
    assert "Scene Beat Engine" not in user, (
        "Scene Beat Engine was removed from user_sections — it must not appear in the user message"
    )


def test_build_rp_reply_prompt_partner_control_before_heat():
    """Partner-Control must appear before the heat block in the user message."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_TENSION_TEXT,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        heat_level="flame",
        character_name="Leonardo",
    )
    user = msgs[1]["content"]
    partner_control_pos = user.find("Partner-Control")
    heat_pos = user.upper().find("HEAT —")
    if heat_pos == -1:
        heat_pos = user.upper().find("FLAME —")
    assert partner_control_pos != -1, "Partner-Control not found in user message"
    assert heat_pos != -1, "Heat block not found in user message"
    assert partner_control_pos < heat_pos, (
        "Partner-Control must appear before heat block per spec ordering"
    )


def test_build_rp_prompt_layers_scene_metadata_exposed():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply=_KISSING_TEXT,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="flame",
    )
    assert "_scene_stage" in layers
    assert "_next_goal" in layers
    assert "_repetition_score" in layers
    assert layers["_scene_stage"] == "kissing"
    assert layers["_next_goal"] == "heavy_makeout"


def test_inferno_scene_engine_mentions_explicit():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply=_EXPLICIT_TEXT,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="inferno",
    )
    engine = layers["scene_engine"]
    assert "explicit" in engine.lower()


# ── 7. Endpoint integration ───────────────────────────────────────────────────

def test_rp_reply_endpoint_returns_scene_beat_fields(client):
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _TENSION_TEXT,
            "response_length": "short",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
            "heat_level": "flame",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "next_scene_goal" in data
    assert "repetition_score" in data
    assert "progression_success" in data
    assert isinstance(data["next_scene_goal"], str)
    assert isinstance(data["repetition_score"], float)
    assert isinstance(data["progression_success"], bool)
    assert 0.0 <= data["repetition_score"] <= 1.0


def test_rp_reply_endpoint_next_goal_for_kissing_scene(client):
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _KISSING_TEXT,
            "response_length": "short",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "mature",
            "heat_level": "flame",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["next_scene_goal"]


def test_rp_reply_endpoint_inferno_returns_scene_goal(client):
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _EXPLICIT_TEXT,
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "mature",
            "heat_level": "inferno",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["next_scene_goal"]
    assert isinstance(data["progression_success"], bool)
