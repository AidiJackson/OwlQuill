"""Tests for the beat planner — multi-beat instruction detection and extraction."""
import pytest

from app.services.rp_beat_planner import (
    build_beat_execution_block,
    detect_multi_beat_instruction,
    extract_requested_beats,
)


# ── detect_multi_beat_instruction ─────────────────────────────────────────────

def test_detects_then_keyword():
    assert detect_multi_beat_instruction("Carter warns her and then kisses her goodbye") is True


def test_detects_after_keyword():
    assert detect_multi_beat_instruction("Carter warns her. After that, they leave for the hotel.") is True


def test_detects_midnight_keyword():
    assert detect_multi_beat_instruction("A time skip to midnight. Carter arrives at the hotel.") is True


def test_detects_before_keyword():
    assert detect_multi_beat_instruction("Before she leaves, Carter grabs her hand.") is True


def test_detects_eventually_keyword():
    assert detect_multi_beat_instruction("Carter confesses eventually, then steps away.") is True


def test_detects_next_keyword():
    assert detect_multi_beat_instruction("Carter reveals the truth. Next, they move to the hotel.") is True


def test_detects_four_plus_action_verbs():
    instructions = "Carter warns her, reveals the darker world, moves toward her, and holds her gaze."
    assert detect_multi_beat_instruction(instructions) is True


def test_detects_three_plus_sentence_clauses():
    instructions = (
        "Carter warns her about the danger. "
        "He reveals what he knows. "
        "She steps back."
    )
    assert detect_multi_beat_instruction(instructions) is True


def test_simple_one_line_returns_false():
    assert detect_multi_beat_instruction("Carter responds with cold fury.") is False


def test_empty_string_returns_false():
    assert detect_multi_beat_instruction("") is False


def test_none_returns_false():
    assert detect_multi_beat_instruction(None) is False  # type: ignore[arg-type]


def test_blank_whitespace_returns_false():
    assert detect_multi_beat_instruction("   ") is False


# ── extract_requested_beats ───────────────────────────────────────────────────

_CARTER_HOTEL_INSTRUCTIONS = (
    "Carter warns her about the danger then reveals the darker world. "
    "A goodbye kiss before she leaves. "
    "Hotel warning. "
    "Midnight time skip. "
    "Carter arrives at the hotel doorway."
)


def test_extracts_warning_beat():
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert "warning" in beats


def test_extracts_kiss_beat():
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert "kiss" in beats


def test_extracts_reveal_beat():
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert "reveal" in beats


def test_extracts_time_skip_beat():
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert "time_skip" in beats


def test_extracts_hotel_scene_beat():
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert "hotel_scene" in beats


def test_extracts_arrival_beat():
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert "arrival" in beats


def test_multiple_beats_extracted_from_carter_example():
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert len(beats) >= 4


def test_empty_instructions_returns_empty_list():
    assert extract_requested_beats("") == []


def test_none_instructions_returns_empty_list():
    assert extract_requested_beats(None) == []  # type: ignore[arg-type]


def test_simple_instruction_returns_minimal_beats():
    beats = extract_requested_beats("Carter is cold and silent.")
    # Should find zero or very few beats for a simple instruction with no beat keywords
    assert len(beats) <= 1


# ── build_beat_execution_block ────────────────────────────────────────────────

def test_block_returned_for_three_or_more_beats():
    beats = ["warning", "kiss", "reveal"]
    block = build_beat_execution_block(beats)
    assert block != ""


def test_block_contains_sequence_language():
    beats = ["warning", "kiss", "reveal"]
    block = build_beat_execution_block(beats)
    assert "requested sequence" in block
    assert "opening emotional reaction" in block
    assert "Preserve partner agency" in block


def test_block_contains_budget_guidance():
    beats = ["warning", "kiss", "reveal"]
    block = build_beat_execution_block(beats)
    assert "one third" in block


def test_block_empty_for_fewer_than_three_beats():
    assert build_beat_execution_block([]) == ""
    assert build_beat_execution_block(["warning"]) == ""
    assert build_beat_execution_block(["warning", "kiss"]) == ""


def test_block_non_empty_for_exactly_three_beats():
    assert build_beat_execution_block(["a", "b", "c"]) != ""


def test_block_non_empty_for_five_beats():
    assert build_beat_execution_block(["a", "b", "c", "d", "e"]) != ""


# ── prompt integration tests ───────────────────────────────────────────────────

def test_beat_block_injected_before_partner_reply_in_prompt():
    """Beat block (Execution or Completion) must appear before the partner reply section."""
    from app.services.storylab_generator import build_rp_reply_prompt

    msgs = build_rp_reply_prompt(
        partner_reply="Lennox stepped back from the doorway.",
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        instructions=_CARTER_HOTEL_INSTRUCTIONS,
    )
    user = msgs[1]["content"]
    # Carter example has 4+ beats so the header is "Beat Completion"; accept either
    beat_block_idx = user.find("## Beat Execution")
    if beat_block_idx == -1:
        beat_block_idx = user.find("## Beat Completion")
    partner_reply_idx = user.find("## Partner's Reply")
    assert beat_block_idx != -1, "No beat block found in user prompt"
    assert partner_reply_idx != -1, "Partner's Reply section not found in user prompt"
    assert beat_block_idx < partner_reply_idx, (
        "Beat block must appear before Partner's Reply"
    )


def test_beat_block_not_injected_when_instructions_blank():
    """With blank instructions, no beat execution block should appear."""
    from app.services.storylab_generator import build_rp_reply_prompt

    msgs = build_rp_reply_prompt(
        partner_reply="She stepped away.",
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        instructions=None,
    )
    user = msgs[1]["content"]
    assert "Beat Execution" not in user


def test_beat_block_not_injected_for_simple_one_beat_instruction():
    """Single-beat instruction should not trigger the beat execution block."""
    from app.services.storylab_generator import build_rp_reply_prompt

    msgs = build_rp_reply_prompt(
        partner_reply="She stepped away.",
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        instructions="Carter responds with cold fury.",
    )
    user = msgs[1]["content"]
    assert "Beat Execution" not in user


# ── endpoint response schema tests ────────────────────────────────────────────

def test_rp_reply_response_includes_multi_beat_fields(client):
    """Endpoint response includes multi_beat_detected and requested_beats."""
    from tests.conftest import get_auth_token, auth_headers

    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "Lennox hadn't moved from the doorway. She watched him.",
            "instructions": _CARTER_HOTEL_INSTRUCTIONS,
            "response_length": "match",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "multi_beat_detected" in data
    assert isinstance(data["multi_beat_detected"], bool)
    assert data["multi_beat_detected"] is True
    assert "requested_beats" in data
    assert isinstance(data["requested_beats"], list)
    assert len(data["requested_beats"]) >= 3


def test_rp_reply_response_multi_beat_false_for_simple_instruction(client):
    """Simple one-line instruction should return multi_beat_detected=False."""
    from tests.conftest import get_auth_token, auth_headers

    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She stepped away from the window.",
            "instructions": "Carter is cold and distant.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["multi_beat_detected"] is False
    assert data["requested_beats"] == []


def test_rp_reply_response_multi_beat_false_for_no_instructions(client):
    """No instructions should return multi_beat_detected=False and empty requested_beats."""
    from tests.conftest import get_auth_token, auth_headers

    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She stepped away from the window.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["multi_beat_detected"] is False
    assert data["requested_beats"] == []
