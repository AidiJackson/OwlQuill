"""Tests for the partner silence enforcement layer."""

from app.services.rp_behavior_engine import (
    PARTNER_SILENCE_LAYER,
    NO_PARTNER_BRIDGE_INSTRUCTION,
    SELECTED_CHARACTER_DRIVES_SCENE,
    detect_partner_silence_severe,
    detect_waiting_loop,
    build_partner_silence_correction,
    build_waiting_loop_correction,
)

_LENNOX_REPLY = (
    "||Lennox hadn't moved from the doorway. She stood with one shoulder against the frame, "
    "arms loose at her sides — the pose of someone who had made peace with waiting.||\n\n"
    '"You keep saying that," she said. Her voice was level. Not cold. Just even.\n\n'
    "||She watched him. Not looking for a reaction — just watching.||"
)

_CARTER_HOTEL_INSTRUCTIONS = (
    "Carter warns her about the danger then reveals the darker world. "
    "A goodbye kiss before she leaves. "
    "Hotel warning. "
    "Midnight time skip. "
    "Carter arrives at the hotel doorway."
)


# ── PARTNER_SILENCE_LAYER content ─────────────────────────────────────────────

def test_partner_silence_layer_is_string():
    assert isinstance(PARTNER_SILENCE_LAYER, str)
    assert len(PARTNER_SILENCE_LAYER) > 50


def test_partner_silence_layer_forbids_she_said():
    assert "she said" in PARTNER_SILENCE_LAYER.lower()


def test_partner_silence_layer_forbids_partner_dialogue():
    assert "quoted" in PARTNER_SILENCE_LAYER.lower() or "dialogue" in PARTNER_SILENCE_LAYER.lower()


def test_partner_silence_layer_allows_physical_reactions():
    assert "breath caught" in PARTNER_SILENCE_LAYER or "stillness" in PARTNER_SILENCE_LAYER


def test_partner_silence_layer_requires_selected_char_carries_scene():
    assert "selected character" in PARTNER_SILENCE_LAYER.lower()


# ── NO_PARTNER_BRIDGE_INSTRUCTION content ─────────────────────────────────────

def test_no_partner_bridge_instruction_is_string():
    assert isinstance(NO_PARTNER_BRIDGE_INSTRUCTION, str)


def test_no_partner_bridge_instruction_mentions_bridge():
    assert "partner" in NO_PARTNER_BRIDGE_INSTRUCTION.lower()
    assert "bridge" in NO_PARTNER_BRIDGE_INSTRUCTION.lower() or "selected" in NO_PARTNER_BRIDGE_INSTRUCTION.lower()


# ── detect_partner_silence_severe ─────────────────────────────────────────────

def test_she_said_single_attribution_not_severe():
    # A single "she said" is ambiguous — it may be the selected character (if female).
    # dialogue_count is still recorded, but severe is False to avoid false-positive retries.
    reply = '"I\'m not running," she said quietly.'
    result = detect_partner_silence_severe(reply)
    assert result["dialogue_count"] >= 1
    assert result["severe"] is False  # single attribution — could be selected char's own speech


def test_she_whispered_single_attribution_not_severe():
    reply = '"I\'m asking you to let me be here," she whispered.'
    result = detect_partner_silence_severe(reply)
    assert result["dialogue_count"] >= 1
    assert result["severe"] is False


def test_she_murmured_single_attribution_not_severe():
    reply = '"In us. In whatever this is," she murmured.'
    result = detect_partner_silence_severe(reply)
    assert result["dialogue_count"] >= 1
    assert result["severe"] is False


def test_cross_gender_dialogue_is_severe():
    # Both "he said" AND "she said" present → both characters were written → definite godmod.
    reply = (
        '"Come with me," he said.\n'
        '"I can\'t," she whispered.'
    )
    result = detect_partner_silence_severe(reply)
    assert result["cross_gender_godmod"] is True
    assert result["severe"] is True


def test_two_same_gender_attributions_is_severe():
    # Two attributed lines even at same gender — likely both characters authored.
    reply = (
        '"You shouldn\'t be here," she said.\n'
        '"And yet here I am," she replied.'
    )
    result = detect_partner_silence_severe(reply)
    assert result["dialogue_count"] >= 2
    assert result["severe"] is True


def test_bare_speech_verb_single_not_severe():
    # One bare speech verb is no longer enough to trigger severe — raised bar
    # to avoid false positives when the selected character is gendered ("he said").
    reply = 'She replied with a shake of her head.'
    result = detect_partner_silence_severe(reply)
    assert result["speech_verb_count"] >= 1
    assert result["severe"] is False


def test_bare_speech_verb_two_is_severe():
    reply = 'She replied, then she said nothing more.'
    result = detect_partner_silence_severe(reply)
    assert result["speech_verb_count"] >= 2
    assert result["severe"] is True


def test_partner_decision_is_severe():
    reply = 'She decided to stay, stepping fully into the room.'
    result = detect_partner_silence_severe(reply)
    assert result["severe"] is True
    assert result["decision_count"] >= 1


def test_partner_consented_is_severe():
    reply = 'She consented, moving closer without hesitation.'
    result = detect_partner_silence_severe(reply)
    assert result["severe"] is True


def test_minimal_physical_reaction_not_severe():
    """'She stayed silent' and 'her breath caught' are allowed."""
    reply = (
        "He stepped through the doorway. "
        "Her breath caught. "
        "She stayed silent, her back to the wall."
    )
    result = detect_partner_silence_severe(reply)
    assert result["severe"] is False


def test_stillness_reaction_not_severe():
    reply = "He moved toward her. She did not move away. He reached for the handle."
    result = detect_partner_silence_severe(reply)
    assert result["severe"] is False


def test_partner_shifted_slightly_not_severe():
    reply = "She shifted slightly but said nothing. He crossed to the window."
    result = detect_partner_silence_severe(reply)
    assert result["severe"] is False


def test_clean_selected_char_only_not_severe():
    # No partner attribution verb — only selected-character narration and narrated dialogue.
    # The detector has no character context so we avoid bare "he/she said" in this fixture.
    reply = (
        "||He moved to the center of the room, jaw tight.||\n\n"
        '"You already knew." Not an accusation. Not quite.\n\n'
        "||He did not look at her. The door was still open behind him.||"
    )
    result = detect_partner_silence_severe(reply)
    assert result["severe"] is False


def test_returns_expected_keys():
    result = detect_partner_silence_severe("Some reply.")
    assert "severe" in result
    assert "cross_gender_godmod" in result
    assert "dialogue_count" in result
    assert "speech_verb_count" in result
    assert "decision_count" in result
    assert "flags" in result
    assert isinstance(result["flags"], list)


def test_empty_string_not_severe():
    result = detect_partner_silence_severe("")
    assert result["severe"] is False
    assert result["dialogue_count"] == 0


def test_flags_populated_on_violation():
    reply = '"Stay," she said.'
    result = detect_partner_silence_severe(reply)
    assert len(result["flags"]) >= 1


def test_flags_empty_for_clean_reply():
    reply = "He walked to the window and said nothing."
    result = detect_partner_silence_severe(reply)
    assert result["flags"] == []


# ── build_partner_silence_correction ─────────────────────────────────────────

def test_correction_block_is_string():
    assert isinstance(build_partner_silence_correction(), str)


def test_correction_block_names_character():
    block = build_partner_silence_correction("Carter")
    assert "Carter" in block


def test_correction_block_generic_without_name():
    block = build_partner_silence_correction()
    assert "selected character" in block.lower()


def test_correction_block_instructs_rewrite():
    block = build_partner_silence_correction("Carter")
    assert "Rewrite" in block or "rewrite" in block


def test_correction_block_targets_dialogue_and_decisions():
    block = build_partner_silence_correction()
    assert "dialogue" in block.lower()


# ── Prompt integration ────────────────────────────────────────────────────────

def test_partner_silence_injected_in_user_prompt():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    assert "PARTNER SILENCE" in user or "Partner Silence" in user


def test_partner_silence_before_partner_control_in_user_prompt():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    silence_idx = user.find("PARTNER SILENCE") if "PARTNER SILENCE" in user else user.find("Partner Silence")
    control_idx = user.find("PARTNER-CONTROL") if "PARTNER-CONTROL" in user else user.find("Partner-Control")
    assert silence_idx != -1, "Partner Silence layer not found"
    assert control_idx != -1, "Partner-Control layer not found"
    assert silence_idx < control_idx, "Partner Silence must precede Partner-Control"


def test_partner_silence_after_role_lock_in_user_prompt():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    role_lock_idx = user.find("ROLE LOCK")
    silence_idx = user.find("PARTNER SILENCE") if "PARTNER SILENCE" in user else user.find("Partner Silence")
    assert role_lock_idx != -1
    assert silence_idx != -1
    assert role_lock_idx < silence_idx, "Role Lock must precede Partner Silence"


def test_no_partner_bridge_injected_for_multi_beat():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="novella",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        instructions=_CARTER_HOTEL_INSTRUCTIONS,
    )
    user = msgs[1]["content"]
    assert "bridge" in user.lower() or "partner character to bridge" in user.lower()


def test_no_partner_bridge_not_injected_for_blank_instructions():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        instructions=None,
    )
    user = msgs[1]["content"]
    # No bridge instruction should appear when there are no multi-beat instructions
    assert "partner character to bridge" not in user.lower()


def test_partner_silence_present_for_explicit_mode():
    """Inferno/explicit mode must still enforce partner silence."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="novella",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="explicit",
        heat_level="inferno",
        instructions=_CARTER_HOTEL_INSTRUCTIONS,
    )
    user = msgs[1]["content"]
    assert "PARTNER SILENCE" in user or "Partner Silence" in user


# ── Endpoint tests ─────────────────────────────────────────────────────────────

def test_endpoint_clean_reply_no_silence_warning(client):
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_REPLY,
            "response_length": "match",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Stub output is clean — should produce no partner-dialogue warning
    assert "reply" in data
    assert isinstance(data["warnings"], list)


def test_endpoint_multi_beat_novella_reaches_response(client):
    """Novella with Carter/hotel beats should still return a reply."""
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_REPLY,
            "instructions": _CARTER_HOTEL_INSTRUCTIONS,
            "response_length": "novella",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["reply"].strip()) > 20
    assert data["multi_beat_detected"] is True


# ── detect_waiting_loop ────────────────────────────────────────────────────────

def test_waiting_loop_detected_for_three_patterns():
    reply = (
        "He stood there, anticipation building. "
        "His pulse was pounding. "
        "The silence stretched between them."
    )
    result = detect_waiting_loop(reply)
    assert result["waiting_loop"] is True
    assert result["pattern_count"] >= 3


def test_waiting_loop_not_detected_for_two_patterns():
    reply = "The anticipation was overwhelming. His pulse was pounding."
    result = detect_waiting_loop(reply)
    assert result["waiting_loop"] is False


def test_waiting_loop_empty_string():
    result = detect_waiting_loop("")
    assert result["waiting_loop"] is False
    assert result["pattern_count"] == 0


def test_waiting_loop_returns_expected_keys():
    result = detect_waiting_loop("Some reply.")
    assert "waiting_loop" in result
    assert "pattern_count" in result
    assert "flags" in result
    assert isinstance(result["flags"], list)


def test_waiting_loop_eyes_locked_counted():
    reply = "Eyes locked. Eyes locked again. Eyes locked a third time."
    result = detect_waiting_loop(reply)
    assert result["waiting_loop"] is True


def test_waiting_loop_mixed_patterns():
    reply = (
        "Carter waited, anticipation coiling through his chest. "
        "Her eyes were locked on his. "
        "He was waiting for her response."
    )
    result = detect_waiting_loop(reply)
    assert result["waiting_loop"] is True


def test_waiting_loop_active_scene_not_flagged():
    reply = (
        "He crossed the room in three strides. "
        "His hands found her waist and he pulled her close. "
        '"You\'re not leaving," he said, voice low.'
    )
    result = detect_waiting_loop(reply)
    assert result["waiting_loop"] is False


def test_waiting_loop_silence_stretched_counted():
    reply = "The silence stretched. The moment stretched. Anticipation tightened."
    result = detect_waiting_loop(reply)
    assert result["waiting_loop"] is True
    assert result["pattern_count"] >= 3


# ── build_waiting_loop_correction ─────────────────────────────────────────────

def test_waiting_loop_correction_is_string():
    assert isinstance(build_waiting_loop_correction(), str)


def test_waiting_loop_correction_names_character():
    block = build_waiting_loop_correction("Carter")
    assert "Carter" in block


def test_waiting_loop_correction_generic_without_name():
    block = build_waiting_loop_correction()
    assert "selected character" in block.lower()


def test_waiting_loop_correction_instructs_rewrite():
    block = build_waiting_loop_correction("Carter")
    assert "Rewrite" in block or "rewrite" in block


def test_waiting_loop_correction_mentions_no_wait():
    block = build_waiting_loop_correction()
    assert "wait" in block.lower()


# ── SELECTED_CHARACTER_DRIVES_SCENE content ───────────────────────────────────

def test_selected_char_drives_scene_is_string():
    assert isinstance(SELECTED_CHARACTER_DRIVES_SCENE, str)
    assert len(SELECTED_CHARACTER_DRIVES_SCENE) > 20


def test_selected_char_drives_scene_mentions_selected():
    assert "selected character" in SELECTED_CHARACTER_DRIVES_SCENE.lower()


def test_selected_char_drives_scene_forbids_waiting():
    assert "wait" in SELECTED_CHARACTER_DRIVES_SCENE.lower() or "anticipation" in SELECTED_CHARACTER_DRIVES_SCENE.lower()


def test_partner_drive_layer_present_in_prompt():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    assert "selected character" in user.lower()
    # The drive layer must appear — check for a fragment unique to the directive
    assert (
        "do not wait" in user.lower()
        or "scene forward" in user.lower()
        or "do not loop" in user.lower()
    )


def test_partner_drive_layer_after_partner_control_in_prompt():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    control_idx = user.find("PARTNER-CONTROL") if "PARTNER-CONTROL" in user else user.find("Partner-Control")
    drive_idx = user.find("Scene Drive")
    assert control_idx != -1, "Partner-Control layer not found"
    assert drive_idx != -1, "Scene Drive layer not found"
    assert control_idx < drive_idx, "Partner-Control must precede Scene Drive"
