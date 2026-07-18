"""Tests for RP reply length profiles and beat execution fixes."""
import pytest

_CARTER_HOTEL_INSTRUCTIONS = (
    "Carter warns her about the danger then reveals the darker world. "
    "A goodbye kiss before she leaves. "
    "Hotel warning. "
    "Midnight time skip. "
    "Carter arrives at the hotel doorway."
)

_LENNOX_REPLY = (
    "||Lennox hadn't moved from the doorway. She stood with one shoulder against the frame, "
    "arms loose at her sides — the pose of someone who had made peace with waiting.||\n\n"
    '"You keep saying that," she said. Her voice was level. Not cold. Just even.\n\n'
    "||She watched him. Not looking for a reaction — just watching.||"
)


# ── Length profile unit tests ─────────────────────────────────────────────────

def test_novella_max_tokens_larger_than_long():
    from app.services.storylab_generator import _rp_reply_max_tokens
    partner_words = 80
    assert _rp_reply_max_tokens("novella", partner_words) > _rp_reply_max_tokens("long", partner_words)


def test_long_max_tokens_larger_than_match():
    from app.services.storylab_generator import _rp_reply_max_tokens
    partner_words = 80
    assert _rp_reply_max_tokens("long", partner_words) > _rp_reply_max_tokens("match", partner_words)


def test_long_max_tokens_larger_than_short():
    from app.services.storylab_generator import _rp_reply_max_tokens
    partner_words = 80
    assert _rp_reply_max_tokens("long", partner_words) > _rp_reply_max_tokens("short", partner_words)


def test_novella_max_tokens_is_2200():
    """Novella budget is ~3x its 700-word target (retuned to enforce length)."""
    from app.services.storylab_generator import _rp_reply_max_tokens
    assert _rp_reply_max_tokens("novella", 80) == 2200


def test_short_max_tokens_is_450():
    """Short budget is ~3x its 100-word target (retuned to enforce length)."""
    from app.services.storylab_generator import _rp_reply_max_tokens
    assert _rp_reply_max_tokens("short", 80) == 450


def test_long_max_tokens_is_1100():
    """Long budget is ~3x its 350-word target (retuned to enforce length)."""
    from app.services.storylab_generator import _rp_reply_max_tokens
    assert _rp_reply_max_tokens("long", 80) == 1100


def test_match_max_tokens_capped():
    from app.services.storylab_generator import _rp_reply_max_tokens
    # Even with a huge partner reply, match should stay within its cap
    mt = _rp_reply_max_tokens("match", 5000)
    assert mt <= 2000


def test_match_max_tokens_scales_with_partner():
    from app.services.storylab_generator import _rp_reply_max_tokens
    small = _rp_reply_max_tokens("match", 50)
    large = _rp_reply_max_tokens("match", 400)
    assert large > small


def test_length_profile_label_short():
    from app.services.storylab_generator import _rp_length_profile
    p = _rp_length_profile("short", 80)
    assert "short" in str(p["label"]).lower()


def test_length_profile_label_novella():
    from app.services.storylab_generator import _rp_length_profile
    p = _rp_length_profile("novella", 80)
    assert "novella" in str(p["label"]).lower()


def test_novella_prompt_includes_beat_hint():
    """Novella length instruction should include the beat execution hint."""
    from app.services.storylab_generator import _rp_length_instruction
    instr = _rp_length_instruction("novella", 80)
    assert "one third" in instr
    assert "requested beats" in instr


def test_short_prompt_does_not_include_beat_hint():
    from app.services.storylab_generator import _rp_length_instruction
    instr = _rp_length_instruction("short", 80)
    assert "requested beats" not in instr


# ── Beat planner strengthening tests ─────────────────────────────────────────

def test_carter_hotel_detects_4_plus_beats():
    from app.services.rp_beat_planner import extract_requested_beats
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert len(beats) >= 4


def test_4_plus_beats_forces_multi_beat_detected():
    from app.services.rp_beat_planner import detect_multi_beat_instruction
    # Even without temporal keywords, 4+ beats should force True
    # (The Carter example happens to have "then" and "before" so it's always True,
    # but test the 4+ beat override path too)
    from app.services.rp_beat_planner import extract_requested_beats
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert len(beats) >= 4
    assert detect_multi_beat_instruction(_CARTER_HOTEL_INSTRUCTIONS) is True


def test_beat_completion_mode_full_sequence_for_4_plus():
    from app.services.rp_beat_planner import beat_completion_mode, extract_requested_beats
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    assert beat_completion_mode(beats) == "full_sequence"


def test_beat_completion_mode_multi_beat_for_exactly_3():
    from app.services.rp_beat_planner import beat_completion_mode
    assert beat_completion_mode(["a", "b", "c"]) == "multi_beat"


def test_beat_completion_mode_single_for_fewer_than_3():
    from app.services.rp_beat_planner import beat_completion_mode
    assert beat_completion_mode([]) == "single"
    assert beat_completion_mode(["a"]) == "single"
    assert beat_completion_mode(["a", "b"]) == "single"


def test_full_sequence_block_injected_for_4_plus_beats():
    """4+ beats should inject the stronger completion block."""
    from app.services.rp_beat_planner import build_beat_execution_block, extract_requested_beats
    beats = extract_requested_beats(_CARTER_HOTEL_INSTRUCTIONS)
    block = build_beat_execution_block(beats)
    assert "complete all major requested beats" in block.lower()


def test_multi_beat_block_injected_for_exactly_3_beats():
    from app.services.rp_beat_planner import build_beat_execution_block
    block = build_beat_execution_block(["warning", "kiss", "reveal"])
    assert "requested sequence" in block
    assert "complete all major requested beats" not in block.lower()


def test_no_block_for_fewer_than_3_beats():
    from app.services.rp_beat_planner import build_beat_execution_block
    assert build_beat_execution_block(["warning", "kiss"]) == ""


# ── Prompt integration ────────────────────────────────────────────────────────

def test_beat_block_injected_before_partner_reply_for_carter():
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
    beat_idx = user.find("Beat Execution") if "Beat Execution" in user else user.find("Beat Completion")
    partner_idx = user.find("## Partner's Reply")
    assert beat_idx != -1, "No beat block found in user prompt"
    assert partner_idx != -1
    assert beat_idx < partner_idx


def test_blank_instructions_no_beat_block():
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
    assert "Beat Execution" not in user
    assert "Beat Completion" not in user


def test_explicit_mode_unaffected_by_beat_planner():
    """Explicit/inferno mode should still get beat block when instructions are multi-beat."""
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
    # Beat block present
    assert "Beat Execution" in user or "Beat Completion" in user
    # Inferno heat still active
    assert "INFERNO" in user.upper() or "inferno" in user.lower()


# ── Endpoint response schema ───────────────────────────────────────────────────

def test_endpoint_returns_length_profile_fields(client):
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
    assert "resolved_length_profile" in data
    assert "novella" in data["resolved_length_profile"].lower()
    assert "max_tokens_used" in data
    assert data["max_tokens_used"] == 2200
    assert "requested_beat_count" in data
    assert data["requested_beat_count"] >= 4
    assert "beat_completion_mode" in data
    assert data["beat_completion_mode"] == "full_sequence"


def test_endpoint_short_has_lower_token_budget_than_novella(client):
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)

    def call(length):
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": _LENNOX_REPLY,
                "response_length": length,
                "style_match": "off",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "standard",
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["max_tokens_used"]

    assert call("short") < call("novella")


def test_endpoint_multi_beat_detected_true_for_carter(client):
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_REPLY,
            "instructions": _CARTER_HOTEL_INSTRUCTIONS,
            "response_length": "long",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["multi_beat_detected"] is True
    assert data["requested_beat_count"] >= 4


def test_endpoint_explicit_mode_max_tokens_unaffected(client):
    """Explicit mode should still get the full token budget for novella."""
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    from tests.conftest import make_admin
    # Explicit/inferno heat is admin-only during launch (explicit_admin_only gate).
    make_admin("user@test.com")
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_REPLY,
            "response_length": "novella",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "explicit",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["max_tokens_used"] == 2200


def test_endpoint_blank_instructions_beat_mode_single(client):
    from tests.conftest import get_auth_token, auth_headers
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_REPLY,
            "response_length": "match",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["multi_beat_detected"] is False
    assert data["beat_completion_mode"] == "single"
    assert data["requested_beat_count"] == 0
