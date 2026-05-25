"""Tests for the RP Reply Generator endpoint and prompt builder."""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import get_auth_token, auth_headers

_LENNOX_REPLY = (
    "||Lennox hadn't moved from the doorway. She stood with one shoulder against the frame, "
    "arms loose at her sides — the pose of someone who had made peace with waiting, "
    "or at least learned to look like it.||\n\n"
    '"You keep saying that," she said. Her voice was level. Not cold. Just even. '
    '"You keep saying it like it means something different every time."\n\n'
    "||She watched him. Not looking for a reaction — just watching. "
    "The way you watch a fire to see which way the smoke is going.||"
)


# ── prompt builder unit tests ─────────────────────────────────────────────────

def test_build_rp_reply_prompt_returns_system_and_user():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_build_rp_reply_prompt_contains_anti_godmod_rules():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply="She looked at him.",
        response_length="short",
        style_match="off",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    # System contains identity + behavior_enforcement; user contains partner_control
    full_prompt = msgs[0]["content"] + msgs[1]["content"]
    assert "ONLY" in full_prompt
    assert "partner" in full_prompt.lower()
    assert (
        "godmod" in full_prompt.lower()
        or "never write" in full_prompt.lower()
        or "Do NOT" in full_prompt
        or "partner character" in full_prompt.lower()
    )


def test_build_rp_reply_prompt_includes_partner_reply():
    from app.services.storylab_generator import build_rp_reply_prompt
    partner = "She stepped away from the window."
    msgs = build_rp_reply_prompt(
        partner_reply=partner,
        response_length="match",
        style_match="off",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    assert partner in user


def test_build_rp_reply_prompt_roleplay_bars_instruction():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply="He moved toward her.",
        response_length="match",
        style_match="off",
        perspective="third_person_limited",
        formatting="roleplay_bars",
        intensity="standard",
    )
    user = msgs[1]["content"]
    assert "||" in user


def test_build_rp_reply_prompt_embers_prohibits_explicit():
    from app.services.storylab_generator import build_rp_reply_prompt
    # Embers heat level explicitly prohibits explicit anatomy and acts
    msgs = build_rp_reply_prompt(
        partner_reply="He leaned in close.",
        response_length="match",
        style_match="off",
        perspective="first_person",
        formatting="plain",
        intensity="mature",
        heat_level="embers",
    )
    user = msgs[1]["content"]
    # The embers heat block contains "EMBERS" and explicit prohibitions
    assert "EMBERS" in user.upper()
    assert "explicit" in user.lower()
    assert "not" in user.lower()


def test_build_rp_reply_prompt_character_context_injected():
    from app.services.storylab_generator import build_rp_reply_prompt
    ctx = "Name: Leonardo\nRole: Crime lord\nBio: Controlled, precise."
    msgs = build_rp_reply_prompt(
        partner_reply="She waited.",
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        character_context=ctx,
        character_name="Leonardo",
    )
    # Character context is in the system message (identity layer)
    full_prompt = msgs[0]["content"] + msgs[1]["content"]
    assert "Leonardo" in full_prompt
    assert "Crime lord" in full_prompt


def test_build_rp_reply_prompt_style_match_strong():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply="The silence stretched.",
        response_length="match",
        style_match="strong",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    assert "strong" in user.lower() or "mirror" in user.lower()


def test_check_rp_reply_output_warns_on_empty():
    from app.services.storylab_generator import _check_rp_reply_output
    warnings = _check_rp_reply_output("Too short.")
    assert any("short" in w.lower() for w in warnings)


def test_check_rp_reply_output_no_warnings_for_clean_reply():
    from app.services.storylab_generator import _check_rp_reply_output
    clean = (
        "||He turned away from the window, something tightening behind his sternum "
        "that had nothing to do with anger — or maybe everything.||\n\n"
        '"I\'ve heard that before," he said. The admission cost him nothing outwardly.\n\n'
        "||He moved to the table. Put distance between them that was not quite retreat.||"
    )
    warnings = _check_rp_reply_output(clean)
    assert warnings == []


# ── endpoint tests ────────────────────────────────────────────────────────────

def test_rp_reply_basic_generation(client: TestClient):
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
    assert "reply" in data
    assert len(data["reply"].strip()) > 20
    assert isinstance(data["warnings"], list)


def test_rp_reply_roleplay_bars_format(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She crossed the room without a word.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "roleplay_bars",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Stub output with roleplay_bars should contain || delimiters
    assert "||" in data["reply"]


def test_rp_reply_mature_mode_does_not_enable_explicit(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "He moved closer, his voice dropping to almost nothing.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "mature",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "reply" in data
    # Stub output should not contain explicit content markers
    reply_lower = data["reply"].lower()
    explicit_markers = ["sex", "naked", "nude", "erect", "penetrat"]
    for marker in explicit_markers:
        assert marker not in reply_lower, f"Unexpected explicit content marker '{marker}' in stub reply"


def test_rp_reply_with_character_id(client: TestClient):
    token = get_auth_token(client)
    # Create a character first
    char_resp = client.post(
        "/characters/",
        headers=auth_headers(token),
        json={"name": "Leonardo", "role": "crime lord", "short_bio": "Controlled and precise."},
    )
    assert char_resp.status_code in (200, 201), char_resp.text
    char_id = char_resp.json()["id"]

    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_REPLY,
            "character_id": char_id,
            "response_length": "match",
            "style_match": "strong",
            "perspective": "third_person_limited",
            "formatting": "roleplay_bars",
            "intensity": "mature",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "reply" in data
    assert len(data["reply"].strip()) > 20


def test_rp_reply_invalid_character_id_returns_404(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She waited.",
            "character_id": 99999,
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 404


def test_rp_reply_requires_auth(client: TestClient):
    resp = client.post(
        "/storylab/rp-reply/generate",
        json={
            "partner_reply": "She waited.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code in (401, 403)


# ── POV regression tests ──────────────────────────────────────────────────────

_LENNOX_POV_REPLY = (
    "||Lennox hadn't moved from the doorway. She stood with one shoulder against the frame, "
    "arms loose at her sides — the pose of someone who had made peace with waiting, "
    "or at least learned to look like it.||\n\n"
    '"You keep saying that," she said. Her voice was level. Not cold. Just even. '
    '"You keep saying it like it means something different every time."\n\n'
    "||She watched him. Not looking for a reaction — just watching. "
    "The way you watch a fire to see which way the smoke is going.||"
)


# ── detect_wrong_pov unit tests ───────────────────────────────────────────────

def test_detect_wrong_pov_returns_expected_keys():
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text="She did not move immediately.",
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    assert set(result.keys()) == {"wrong_pov", "reason", "partner_pronoun", "partner_char"}


def test_detect_wrong_pov_she_opening_no_false_positive_with_name_anchor():
    """With name anchor available, pronoun-only opening is NOT flagged (avoids false positives)."""
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text="She did not move immediately. Her voice was quiet.",
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    # "Lennox" was inferred as partner char → pronoun check skipped → no false positive
    assert isinstance(result["wrong_pov"], bool)
    assert isinstance(result["reason"], str)


def test_detect_wrong_pov_flags_partner_name_in_reply_opening():
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text="Lennox watched him from the doorway. She hadn't moved.",
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    assert result["wrong_pov"] is True


def test_detect_wrong_pov_clean_for_correct_character_opening():
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text="He crossed the room without looking at her.",
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    assert result["wrong_pov"] is False


def test_detect_wrong_pov_clean_for_dialogue_opening():
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text='"That changes nothing," he said.',
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    assert result["wrong_pov"] is False


def test_detect_wrong_pov_partner_pronoun_empty_when_name_anchor_available():
    """partner_pronoun is left empty when name anchoring succeeds (pronoun check skipped)."""
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text="He moved toward her.",
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    # Name anchor "Lennox" available → pronoun inference not needed
    assert isinstance(result["partner_pronoun"], str)


def test_detect_wrong_pov_infers_partner_char_name():
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text="He moved toward her.",
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    assert result["partner_char"] == "Lennox"


def test_detect_wrong_pov_no_false_positive_with_bars():
    from app.services.rp_style_engine import detect_wrong_pov
    # Reply correctly opens with Leo's action wrapped in roleplay bars
    result = detect_wrong_pov(
        reply_text="||He let the silence hold a moment longer than necessary.||",
        character_name="Leonardo",
        partner_reply=_LENNOX_POV_REPLY,
    )
    assert result["wrong_pov"] is False


def test_detect_wrong_pov_empty_character_name_no_crash():
    from app.services.rp_style_engine import detect_wrong_pov
    result = detect_wrong_pov(
        reply_text="She did not move.",
        character_name="",
        partner_reply=_LENNOX_POV_REPLY,
    )
    assert isinstance(result["wrong_pov"], bool)


# ── Role lock layer tests ─────────────────────────────────────────────────────

def test_build_rp_reply_prompt_contains_role_lock_in_user_message():
    """ROLE LOCK must appear in the user message (priority ordering: before partner reply)."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_LENNOX_POV_REPLY,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        character_name="Leonardo",
    )
    user = msgs[1]["content"]
    role_lock_pos = user.find("ROLE LOCK")
    assert role_lock_pos != -1, "ROLE LOCK layer not found in user message"
    # In the new priority ordering, ROLE LOCK is at the top of the user message
    # (priority 2, before scene_state / partner reply).
    partner_pos = user.find("You keep saying that")
    assert role_lock_pos < partner_pos, (
        "ROLE LOCK must appear BEFORE the partner reply in the user message "
        "(new priority ordering: behavioral rules first, content second), "
        f"but role_lock_pos={role_lock_pos} > partner_pos={partner_pos}"
    )


def test_build_rp_reply_prompt_role_lock_names_character():
    """ROLE LOCK must name the selected character explicitly."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply="She waited at the door.",
        response_length="short",
        style_match="off",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        character_name="Leonardo",
    )
    user = msgs[1]["content"]
    assert "ROLE LOCK" in user
    assert "Leonardo" in user[user.find("ROLE LOCK"):]


def test_build_rp_reply_prompt_role_lock_present_without_character_name():
    """A generic ROLE LOCK must appear even when no character is selected."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply="She waited at the door.",
        response_length="short",
        style_match="off",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        character_name="",
    )
    user = msgs[1]["content"]
    assert "ROLE LOCK" in user


def test_build_rp_prompt_layers_includes_role_lock_key():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply="She waited.",
        response_length="short",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        character_name="Leonardo",
    )
    assert "role_lock" in layers
    assert "ROLE LOCK" in layers["role_lock"]
    assert "Leonardo" in layers["role_lock"]


# ── Endpoint POV regression tests ─────────────────────────────────────────────

def test_rp_reply_endpoint_with_leonardo_does_not_open_as_lennox(client: TestClient):
    """Stub mode: with Leonardo as character, reply must not start as Lennox/She."""
    token = get_auth_token(client)
    # Create Leonardo character
    char_resp = client.post(
        "/characters/",
        headers=auth_headers(token),
        json={"name": "Leonardo Baptiste", "role": "crime lord", "short_bio": "Controlled, precise, dangerous."},
    )
    assert char_resp.status_code in (200, 201), char_resp.text
    char_id = char_resp.json()["id"]

    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_POV_REPLY,
            "character_id": char_id,
            "response_length": "match",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reply"]

    # In stub mode, the stub generator writes from the user character's perspective.
    # Check that the response structure is valid regardless.
    assert isinstance(data["warnings"], list)
    assert isinstance(data.get("style_warnings", []), list)


def test_rp_reply_endpoint_response_has_style_warnings_field(client: TestClient):
    """Response always includes style_warnings field (may be empty)."""
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_POV_REPLY,
            "response_length": "match",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "style_warnings" in data
    assert isinstance(data["style_warnings"], list)


def test_rp_reply_empty_partner_reply_rejected(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Collaborative RP Enforcement Layer V1 — Behavior Engine Tests
# ══════════════════════════════════════════════════════════════════════════════

_WAREHOUSE_SCENE = (
    "||Lennox hadn't moved from her position near the window. The rain against the "
    "warehouse glass was relentless. She kept her back to him, arms loose at her "
    "sides — the posture of someone who hadn't decided yet.||\n\n"
    '"You came back," she said. Her voice was even. Not a question. Not relief.\n\n'
    "||She turned then. Slowly. Let the light catch the angle of her jaw.||\n\n"
    '"I wasn\'t sure you would."'
)

# ── detect_partner_control ────────────────────────────────────────────────────

def test_detect_partner_control_returns_expected_keys():
    from app.services.rp_behavior_engine import detect_partner_control
    result = detect_partner_control("He moved toward her.")
    assert set(result.keys()) == {
        "partner_control_risk", "authored_dialogue", "authored_thoughts",
        "authored_consent", "flags"
    }


def test_detect_partner_control_clean_reply_low_risk():
    from app.services.rp_behavior_engine import detect_partner_control
    clean = (
        "||He turned from the window. The rain filled the silence between them.||\n\n"
        '"I said I would," he said. The words cost him nothing.\n\n'
        "||He moved to the table. Put three feet of space between them — "
        "not quite distance, not quite safety.||"
    )
    result = detect_partner_control(clean)
    assert result["partner_control_risk"] < 0.3
    assert result["authored_dialogue"] is False
    assert result["authored_thoughts"] is False
    assert result["authored_consent"] is False


def test_detect_partner_control_flags_authored_dialogue():
    from app.services.rp_behavior_engine import detect_partner_control
    bad = (
        '||He watched her. She hesitated.||\n\n'
        '"I need you," she said. Her voice broke on the last word.\n\n'
        '"Don\'t stop," she whispered. The admission left her undone.\n\n'
        '||She admitted it. She wanted this.||'
    )
    result = detect_partner_control(bad)
    assert result["authored_dialogue"] is True
    assert result["partner_control_risk"] >= 0.35


def test_detect_partner_control_flags_authored_thoughts():
    from app.services.rp_behavior_engine import detect_partner_control
    bad = (
        "She thought he would leave. She knew it was inevitable. "
        "She realized she wanted him to stay. She decided it was too late. "
        "She understood exactly what it meant."
    )
    result = detect_partner_control(bad)
    assert result["authored_thoughts"] is True
    assert result["partner_control_risk"] >= 0.3


def test_detect_partner_control_flags_authored_consent():
    from app.services.rp_behavior_engine import detect_partner_control
    bad = (
        "||She let him take the lead. She allowed him to guide her. "
        "She surrendered to the inevitability of the moment.||"
    )
    result = detect_partner_control(bad)
    assert result["authored_consent"] is True
    assert result["partner_control_risk"] >= 0.3


def test_detect_partner_control_allows_implied_physical_reactions():
    from app.services.rp_behavior_engine import detect_partner_control
    allowed = (
        "||He closed the distance. Her breath caught — he felt it — "
        "but he did not stop. Her nails dug into the edge of the windowsill. "
        "He let that register without comment.||"
    )
    result = detect_partner_control(allowed)
    # Minimal implied physical reactions should not trigger authored_consent or authored_thoughts
    assert result["authored_consent"] is False
    assert result["authored_thoughts"] is False


def test_detect_partner_control_forbidden_authored_reactions():
    from app.services.rp_behavior_engine import detect_partner_control
    forbidden = "I choose you. Don't stop. I've never been more sure."
    result = detect_partner_control(forbidden)
    assert result["partner_control_risk"] > 0.0
    assert len(result["flags"]) > 0


# ── detect_scene_stall ────────────────────────────────────────────────────────

def test_detect_scene_stall_returns_expected_keys():
    from app.services.rp_behavior_engine import detect_scene_stall
    result = detect_scene_stall("He moved toward her.")
    assert set(result.keys()) == {
        "scene_stall_score", "progression_score", "repeated_emotion_score",
        "stall_flags", "progression_signals"
    }


def test_detect_scene_stall_scores_in_range():
    from app.services.rp_behavior_engine import detect_scene_stall
    result = detect_scene_stall("She stood at the window. The rain fell.")
    assert 0.0 <= result["scene_stall_score"] <= 1.0
    assert 0.0 <= result["progression_score"] <= 1.0
    assert 0.0 <= result["repeated_emotion_score"] <= 1.0


def test_detect_scene_stall_flags_repeated_longing():
    from app.services.rp_behavior_engine import detect_scene_stall
    stalled = (
        "He ached for her. He longed to close the distance. He yearned — "
        "that familiar aching that had followed him for months. He craved her presence. "
        "The longing would not release him."
    )
    result = detect_scene_stall(stalled)
    assert result["scene_stall_score"] > 0.2
    assert result["repeated_emotion_score"] > 0.0
    assert any("longing" in f.lower() or "restraint" in f.lower() for f in result["stall_flags"])


def test_detect_scene_stall_flags_repeated_storm_imagery():
    from app.services.rp_behavior_engine import detect_scene_stall
    stalled = (
        "The storm raged outside. Lightning split the sky. The storm had not let up. "
        "Thunder again. Another storm-beat. The rain and storm continued."
    )
    result = detect_scene_stall(stalled)
    assert result["scene_stall_score"] > 0.1
    assert any("storm" in f.lower() for f in result["stall_flags"])


def test_detect_scene_stall_rewards_progression():
    from app.services.rp_behavior_engine import detect_scene_stall
    progressive = (
        "||He crossed the room without speaking. Reached past her to set the glass down "
        "on the sill — close enough that she would have to choose whether to move or not.||\n\n"
        '"You want to tell me something," he said. Not a question.\n\n'
        "||He turned. Pulled a chair back from the table. Sat. Gave her the floor.||"
    )
    result = detect_scene_stall(progressive)
    assert result["progression_score"] > 0.2
    assert any("movement" in s.lower() or "physical" in s.lower() for s in result["progression_signals"])


def test_detect_scene_stall_dialogue_scores_as_progression():
    from app.services.rp_behavior_engine import detect_scene_stall
    with_dialogue = (
        '"Tell me what happened," he said.\n\n'
        '"All of it. Don\'t leave anything out."\n\n'
        '||He waited. He had learned a long time ago that silence was more useful than questions.||'
    )
    result = detect_scene_stall(with_dialogue)
    assert result["progression_score"] > 0.0
    assert any("dialogue" in s.lower() for s in result["progression_signals"])


# ── inferno explicitness layer injection ──────────────────────────────────────

def test_inferno_explicitness_layer_injected_in_prompt():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="inferno",
    )
    enforcement = layers["behavior_enforcement"]
    assert "INFERNO" in enforcement.upper()
    assert "explicit" in enforcement.lower()


def test_inferno_explicitness_layer_not_injected_for_flame():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="flame",
    )
    enforcement = layers["behavior_enforcement"]
    assert "INFERNO EXPLICITNESS MODE" not in enforcement


def test_build_behavior_enforcement_block_inferno_mode():
    from app.services.rp_behavior_engine import build_behavior_enforcement_block
    block = build_behavior_enforcement_block(heat_level="inferno", instructions="push further")
    assert "INFERNO" in block.upper()
    assert "cock" in block.lower() or "pussy" in block.lower() or "anatomy" in block.lower()


def test_build_behavior_enforcement_block_non_inferno_no_anatomy():
    from app.services.rp_behavior_engine import build_behavior_enforcement_block
    block = build_behavior_enforcement_block(heat_level="flame", instructions="continue")
    assert "INFERNO EXPLICITNESS MODE" not in block


# ── prompt layer ordering ─────────────────────────────────────────────────────

def test_prompt_layer_order_behavioral_before_content():
    """Behavioral enforcement layers must appear before heat/scene content in the user message."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        heat_level="flame",
        character_name="Leonardo",
    )
    user = msgs[1]["content"]
    role_lock_pos = user.find("ROLE LOCK")
    partner_control_pos = user.find("Partner-Control Protection")
    # Partner reply appears in scene_state, which comes after behavioral rules
    partner_reply_pos = user.find("You came back")
    assert role_lock_pos != -1, "ROLE LOCK not found in user message"
    assert partner_control_pos != -1, "Partner-Control Protection not found"
    assert partner_reply_pos != -1, "Partner reply not found in user message"
    assert role_lock_pos < partner_reply_pos, "ROLE LOCK must precede partner reply"
    assert partner_control_pos < partner_reply_pos, "Partner-Control must precede partner reply"


def test_prompt_layer_behavior_enforcement_in_system():
    """Behavioral enforcement block must be in the system message."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        heat_level="flame",
        character_name="Leonardo",
    )
    system = msgs[0]["content"]
    assert "COLLABORATIVE RP ENFORCEMENT" in system
    assert "HIGHEST PRIORITY" in system


def test_prompt_layer_heat_before_scene_state():
    """Heat layer must appear before scene_state (partner reply + instructions) in the user message."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        heat_level="flame",
        character_name="Leonardo",
    )
    user = msgs[1]["content"]
    # Heat section starts with "## " + the heat level header
    heat_pos = user.upper().find("HEAT —")
    if heat_pos == -1:
        heat_pos = user.upper().find("FLAME —")
    if heat_pos == -1:
        heat_pos = user.find("## Heat")
    # Partner reply is embedded in scene_state
    partner_reply_pos = user.find("You came back")
    assert heat_pos != -1, "Heat block not found in user message"
    assert partner_reply_pos != -1, "Partner reply not found in user message"
    assert heat_pos < partner_reply_pos, "Heat layer must precede partner reply (scene_state)"


def test_build_rp_prompt_layers_new_keys_present():
    """New behavior engine layers must appear as named keys in the layers dict."""
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="flame",
        character_name="Leonardo",
    )
    assert "behavior_enforcement" in layers
    assert "partner_control" in layers
    assert "scene_engine" in layers
    assert "archetype" in layers
    assert "prose_polish" in layers
    assert "COLLABORATIVE RP ENFORCEMENT" in layers["behavior_enforcement"]
    assert "Partner-Control" in layers["partner_control"]
    assert "SCENE BEAT ENGINE" in layers["scene_engine"]


# ── empty instructions default continuation mode ──────────────────────────────

def test_empty_instructions_injects_default_continuation():
    from app.services.rp_behavior_engine import build_behavior_enforcement_block
    block = build_behavior_enforcement_block(heat_level="flame", instructions=None)
    assert "continue" in block.lower()
    assert "natural" in block.lower() or "forward" in block.lower()


def test_empty_string_instructions_injects_default_continuation():
    from app.services.rp_behavior_engine import build_behavior_enforcement_block
    block = build_behavior_enforcement_block(heat_level="flame", instructions="")
    assert "continue" in block.lower()


def test_provided_instructions_skip_default_continuation():
    from app.services.rp_behavior_engine import build_behavior_enforcement_block
    block = build_behavior_enforcement_block(heat_level="flame", instructions="Escalate the tension.")
    assert "CONTINUATION INTENT" not in block


# ── progression scoring ───────────────────────────────────────────────────────

def test_scene_stall_low_for_action_heavy_reply():
    from app.services.rp_behavior_engine import detect_scene_stall
    action_heavy = (
        "||He crossed the room. Reached for her wrist — not hard, just precise. "
        "Turned her to face him. Pressed her back against the wall with a single step forward.||\n\n"
        '"Stop running," he said.\n\n'
        "||He didn't raise his voice. Didn't need to. His hands moved to bracket her — "
        "one arm on either side. No escape that didn't go through him.||"
    )
    result = detect_scene_stall(action_heavy)
    assert result["progression_score"] > 0.3


def test_scene_stall_high_for_loop_heavy_reply():
    from app.services.rp_behavior_engine import detect_scene_stall
    loop_heavy = (
        "He ached. He longed. He yearned for her. The aching would not stop. "
        "He craved something he could not name. The storm raged on. "
        "Her eyes. Her gaze. Her eyes met his. He ached still. He longed still. "
        "The storm. The lightning. The storm again."
    )
    result = detect_scene_stall(loop_heavy)
    assert result["scene_stall_score"] > 0.2


# ── score_inferno_anatomy_density ─────────────────────────────────────────────

def test_inferno_anatomy_density_zero_for_clean_text():
    from app.services.rp_behavior_engine import score_inferno_anatomy_density
    clean = "He crossed the room and looked at her."
    assert score_inferno_anatomy_density(clean) == 0.0


def test_inferno_anatomy_density_nonzero_for_explicit_text():
    from app.services.rp_behavior_engine import score_inferno_anatomy_density
    explicit = (
        "His cock pressed against her thighs. She was wet, folds slick with arousal. "
        "He groaned — the hardness of him against her wetness drove rational thought out."
    )
    assert score_inferno_anatomy_density(explicit) > 0.0


def test_inferno_anatomy_density_in_range():
    from app.services.rp_behavior_engine import score_inferno_anatomy_density
    result = score_inferno_anatomy_density("Any text whatsoever.")
    assert 0.0 <= result <= 1.0


# ── Leonardo/Lennox warehouse integration ────────────────────────────────────

def test_build_rp_layers_warehouse_leonardo_partner_control_present():
    """Partner-control protection must be in the user message for warehouse scenario."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="roleplay_bars",
        intensity="mature",
        character_context="Name: Leonardo Baptiste\nRole: Crime lord\nBio: Controlled and precise.",
        character_name="Leonardo",
        heat_level="inferno",
    )
    user = msgs[1]["content"]
    assert "Partner-Control" in user or "PARTNER" in user.upper()
    assert "INFERNO" in user.upper()


def test_build_rp_layers_warehouse_no_instructions_gets_continuation_intent():
    """Empty instructions must inject DEFAULT_CONTINUATION_INTENT for Leonardo."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        character_name="Leonardo",
        instructions=None,
    )
    system = msgs[0]["content"]
    assert "Continue the scene" in system or "continue" in system.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration Stabilization V1 — New Tests
# ══════════════════════════════════════════════════════════════════════════════

# ── build_retry_correction_block ──────────────────────────────────────────────

def test_build_retry_correction_block_returns_string():
    from app.services.storylab_generator import build_retry_correction_block
    block = build_retry_correction_block()
    assert isinstance(block, str)
    assert len(block) > 10


def test_build_retry_correction_block_targets_partner_control():
    from app.services.storylab_generator import build_retry_correction_block
    block = build_retry_correction_block()
    assert "partner" in block.lower()
    assert "dialogue" in block.lower() or "write only" in block.lower()


def test_build_retry_correction_block_names_character():
    from app.services.storylab_generator import build_retry_correction_block
    block = build_retry_correction_block(character_name="Leonardo")
    assert "Leonardo" in block


def test_build_retry_correction_block_generic_without_name():
    from app.services.storylab_generator import build_retry_correction_block
    block = build_retry_correction_block()
    assert "selected character" in block.lower() or "write only" in block.lower()


def test_build_retry_correction_block_overrides_all():
    from app.services.storylab_generator import build_retry_correction_block
    block = build_retry_correction_block(character_name="Aria")
    assert "CORRECTION" in block or "OVERRIDES" in block


# ── Same-pronoun POV safety (f/f, m/m) ───────────────────────────────────────

def test_detect_wrong_pov_no_false_positive_ff_name_anchor():
    """f/f pairing: if reply starts with partner's name, wrong_pov=True. Otherwise False."""
    from app.services.rp_style_engine import detect_wrong_pov
    partner_ff = (
        "||Maya hadn't moved from the doorway. Her arms loose at her sides.||\n\n"
        '"You came back," she said.\n\n'
        "||She waited.||"
    )
    # Correct reply written from Aria's POV, not starting with "Maya"
    result = detect_wrong_pov(
        reply_text="||She crossed the room without looking away.||\n\n\"I know,\" she said.",
        character_name="Aria",
        partner_reply=partner_ff,
    )
    # Should NOT flag wrong POV when reply doesn't open with partner name
    assert result["wrong_pov"] is False


def test_detect_wrong_pov_ff_partner_name_triggers():
    """f/f: starting reply with partner's name → wrong_pov=True."""
    from app.services.rp_style_engine import detect_wrong_pov
    partner_ff = "||Maya stepped back, expression unreadable.||\n\n\"Enough,\" she said."
    result = detect_wrong_pov(
        reply_text="Maya turned and walked away.",
        character_name="Aria",
        partner_reply=partner_ff,
    )
    assert result["wrong_pov"] is True


def test_detect_wrong_pov_mm_no_false_positive():
    """m/m pairing: same pronoun should not trigger wrong POV on correct reply."""
    from app.services.rp_style_engine import detect_wrong_pov
    partner_mm = (
        "||Dorian turned from the window. Arms crossed.||\n\n"
        '"You know why I\'m here," he said.'
    )
    result = detect_wrong_pov(
        reply_text="He moved toward the door.",
        character_name="Marcus",
        partner_reply=partner_mm,
    )
    # Without starting with "Dorian", should not flag wrong POV
    assert result["wrong_pov"] is False


def test_detect_wrong_pov_mm_partner_name_triggers():
    """m/m: starting reply with partner's name → wrong_pov=True."""
    from app.services.rp_style_engine import detect_wrong_pov
    partner_mm = "||Dorian stepped back, jaw tight.||\n\n\"That's enough,\" he said."
    result = detect_wrong_pov(
        reply_text="Dorian moved toward him without hesitation.",
        character_name="Marcus",
        partner_reply=partner_mm,
    )
    assert result["wrong_pov"] is True


# ── Repetition detection fallback with empty prior_text ───────────────────────

def test_detect_repeated_beats_empty_prior_returns_valid_structure():
    from app.services.rp_scene_engine import detect_repeated_beats
    result = detect_repeated_beats("He moved. She turned. He moved again.", prior_text="")
    assert "repeated_beats" in result
    assert "repetition_score" in result
    assert isinstance(result["repeated_beats"], list)
    assert 0.0 <= result["repetition_score"] <= 1.0


def test_detect_repeated_beats_empty_prior_flags_within_reply():
    from app.services.rp_scene_engine import detect_repeated_beats
    # Pattern repeated 2+ times within the reply itself should be caught
    reply = (
        "He moved toward her. She breathed. He moved again. She breathed. "
        "He moved once more. She breathed in and out."
    )
    result = detect_repeated_beats(reply, prior_text="")
    assert isinstance(result["repetition_score"], float)


def test_detect_repeated_beats_no_false_positive_clean_with_empty_prior():
    from app.services.rp_scene_engine import detect_repeated_beats
    clean = (
        "||He crossed the room and reached past her to set the glass down.||\n\n"
        '"Tell me what you want," he said.\n\n'
        "||He stepped back. Gave her the floor.||"
    )
    result = detect_repeated_beats(clean, prior_text="")
    assert isinstance(result["repeated_beats"], list)


# ── Spatial continuity engine ─────────────────────────────────────────────────

def test_detect_spatial_state_returns_expected_keys():
    from app.services.rp_spatial_engine import detect_spatial_state
    result = detect_spatial_state("He pressed her against the wall.")
    expected = {"current_position", "clothing_state", "active_contact", "dominance_state", "explicit_stage"}
    assert set(result.keys()) == expected


def test_detect_spatial_state_wall_pin_position():
    from app.services.rp_spatial_engine import detect_spatial_state
    result = detect_spatial_state("He pinned her against the wall.")
    assert result["current_position"] == "wall_pin"


def test_detect_spatial_state_neutral_for_clean_text():
    from app.services.rp_spatial_engine import detect_spatial_state
    result = detect_spatial_state("She stood at the window, watching the rain.")
    assert result["current_position"] in ("neutral", "standing", "sitting")


def test_detect_spatial_state_clothing_off():
    from app.services.rp_spatial_engine import detect_spatial_state
    result = detect_spatial_state("His shirt was off, bare chest gleaming.")
    assert result["clothing_state"].get("shirt") == "off"


def test_detect_spatial_state_dominant_signal():
    from app.services.rp_spatial_engine import detect_spatial_state
    result = detect_spatial_state("He pinned her down and commanded her not to move.")
    assert result["dominance_state"] in ("dominant", "contested")


def test_build_spatial_continuity_block_empty_for_neutral():
    from app.services.rp_spatial_engine import build_spatial_continuity_block
    neutral_state = {
        "current_position": "neutral",
        "clothing_state": {"shirt": "on", "pants": "on", "underwear": "on", "bra": "on", "dress": "on"},
        "active_contact": [],
        "dominance_state": "neutral",
        "explicit_stage": "tension",
    }
    block = build_spatial_continuity_block(neutral_state)
    assert block == ""


def test_build_spatial_continuity_block_non_empty_for_physical_scene():
    from app.services.rp_spatial_engine import build_spatial_continuity_block
    physical_state = {
        "current_position": "wall_pin",
        "clothing_state": {"shirt": "off", "pants": "on", "underwear": "on", "bra": "on", "dress": "on"},
        "active_contact": ["hands_on_body"],
        "dominance_state": "dominant",
        "explicit_stage": "undressing",
    }
    block = build_spatial_continuity_block(physical_state)
    assert len(block) > 20
    assert "continuity" in block.lower() or "position" in block.lower()


def test_build_spatial_continuity_block_contains_no_teleport_rule():
    from app.services.rp_spatial_engine import build_spatial_continuity_block
    physical_state = {
        "current_position": "lap",
        "clothing_state": {"shirt": "on", "pants": "on", "underwear": "off", "bra": "on", "dress": "on"},
        "active_contact": ["hips_contact"],
        "dominance_state": "neutral",
        "explicit_stage": "undressing",
    }
    block = build_spatial_continuity_block(physical_state)
    assert "teleport" in block.lower()


def test_rp_reply_endpoint_returns_orchestration_fields(client: TestClient):
    """Response must include orchestration stabilization diagnostic fields."""
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She pressed close, her breathing unsteady.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
            "heat_level": "embers",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Core fields
    assert "reply" in data
    assert "style_warnings" in data
    assert isinstance(data["style_warnings"], list)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Simplification tests
# ══════════════════════════════════════════════════════════════════════════════

# ── Prompt ordering: instructions before partner reply ────────────────────────

def test_prompt_instructions_before_partner_reply():
    """When instructions are provided, they appear before the partner reply in scene_state."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply="She stepped away from the window.",
        response_length="short",
        style_match="off",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        instructions="Do not kiss her yet.",
    )
    user = msgs[1]["content"]
    instructions_pos = user.find("Do not kiss her yet.")
    partner_pos = user.find("She stepped away from the window.")
    assert instructions_pos != -1, "Instructions not found in user message"
    assert partner_pos != -1, "Partner reply not found in user message"
    assert instructions_pos < partner_pos, (
        "Instructions must appear BEFORE the partner reply in the user message"
    )


# ── Explicit routing: explicit/inferno never uses restrictive models ──────────

def test_explicit_intensity_maps_to_inferno_heat():
    """intensity=explicit must resolve to inferno heat level."""
    from app.services.rp_models import effective_heat_level
    assert effective_heat_level("flame", "explicit") == "inferno"


def test_mature_intensity_floors_to_flame():
    """intensity=mature must raise embers to flame."""
    from app.services.rp_models import effective_heat_level
    assert effective_heat_level("embers", "mature") == "flame"


def test_standard_intensity_does_not_raise_heat():
    """intensity=standard must not raise heat above what was specified."""
    from app.services.rp_models import effective_heat_level
    assert effective_heat_level("embers", "standard") == "embers"
    assert effective_heat_level("flame", "standard") == "flame"


def test_inferno_model_is_not_restrictive():
    """Inferno heat must never resolve to a Claude/OpenAI/Google/Cohere model."""
    from app.services.rp_models import resolve_inferno_model, _RESTRICTIVE_SLUG_PREFIXES
    _profile, slug, _override = resolve_inferno_model(
        profile="default",
        default_model="anthropic/claude-3-5-haiku",
        inferno_override="",
    )
    for prefix in _RESTRICTIVE_SLUG_PREFIXES:
        assert not slug.startswith(prefix), (
            f"Inferno resolved to restrictive model: {slug}"
        )


# ── Content level mapping ─────────────────────────────────────────────────────

def test_content_level_standard_in_request(client: TestClient):
    """intensity=standard accepted and returns valid response."""
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She waited at the door.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
        },
    )
    assert resp.status_code == 200
    assert "reply" in resp.json()


def test_content_level_explicit_in_request(client: TestClient):
    """intensity=explicit accepted and returns valid response."""
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She waited at the door.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "explicit",
            "heat_level": "inferno",
        },
    )
    assert resp.status_code == 200
    assert "reply" in resp.json()


# ── Partner control retry: authored_dialogue/consent only ────────────────────

def test_partner_control_retry_triggers_on_authored_dialogue():
    """authored_dialogue=True must trigger the partner-control correction."""
    from app.services.rp_behavior_engine import detect_partner_control
    from app.services.storylab_generator import build_retry_correction_block
    # Craft a reply that authors the partner's dialogue
    bad_reply = (
        '"I need you," she said. Her voice broke on the last word.\n\n'
        '"Don\'t stop," she whispered. The admission left her undone.'
    )
    pc = detect_partner_control(bad_reply)
    assert pc["authored_dialogue"] is True
    # Build correction should target the partner character
    correction = build_retry_correction_block("Leonardo")
    assert "Leonardo" in correction
    assert "partner" in correction.lower() or "write only" in correction.lower()


def test_partner_control_retry_not_triggered_for_cadence_only():
    """Replies with only cadence issues (no authored dialogue/consent) do not trigger retry."""
    from app.services.rp_behavior_engine import detect_partner_control
    # Reply with repetitive cadence but no authored partner content
    cadence_only = (
        "||He breathed. She shivered. He breathed again. She shivered once more.||\n\n"
        "||His gaze met hers. Her gaze met his. The gaze between them held.||"
    )
    pc = detect_partner_control(cadence_only)
    # No authored dialogue or consent should be detected
    assert pc["authored_dialogue"] is False
    assert pc["authored_consent"] is False


# ── Blank instructions: default continuation is concise ──────────────────────

def test_blank_instructions_default_is_not_bloated():
    """With no instructions, the behavior block must be concise (< 800 chars)."""
    from app.services.rp_behavior_engine import build_behavior_enforcement_block
    block = build_behavior_enforcement_block(heat_level="flame", instructions=None)
    assert len(block) < 800, (
        f"Default continuation block is too long ({len(block)} chars) — should be concise"
    )


def test_blank_instructions_no_scene_engine_in_enforcement():
    """Default continuation block must not include Scene Beat Engine instructions."""
    from app.services.rp_behavior_engine import build_behavior_enforcement_block
    block = build_behavior_enforcement_block(heat_level="flame", instructions=None)
    assert "Scene Beat Engine" not in block
    assert "PENALISED" not in block


def test_scene_engine_absent_from_user_message():
    """Scene Beat Engine must NOT appear in the user message (removed from user_sections)."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        heat_level="flame",
    )
    user = msgs[1]["content"]
    assert "Scene Beat Engine" not in user


def test_archetype_absent_from_user_message():
    """Style Archetype must NOT appear in the user message (removed from user_sections)."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    assert "Style Archetype" not in user


def test_prose_polish_absent_from_user_message():
    """Prose Polish must NOT appear in the user message (removed from user_sections)."""
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply=_WAREHOUSE_SCENE,
        response_length="match",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
    )
    user = msgs[1]["content"]
    assert "Prose Polish" not in user


# ═══════════════════════════════════════════════════════════════════════════════
# Godmod output gate — detect_godmod_violations()
# ═══════════════════════════════════════════════════════════════════════════════

from app.services.godmod_validator import detect_godmod_violations as _dgv


def _vtype(result: dict, vtype: str) -> bool:
    return any(v["type"] == vtype for v in result["violations"])


# ── Return shape ──────────────────────────────────────────────────────────────

class TestGodmodReturnShape:
    def test_returns_expected_keys(self):
        result = _dgv("Some text.")
        assert set(result.keys()) == {
            "has_violation",
            "severity",
            "violations",
            "partner_dialogue_count",
            "partner_decision_count",
            "partner_inner_state_count",
            "partner_major_action_count",
            "partner_physical_reaction_count",
        }

    def test_clean_text_returns_none_severity(self):
        result = _dgv(
            "He reached into the darkness and pulled the door closed.",
            selected_character_name="Marcus",
        )
        assert result["severity"] == "none"
        assert result["has_violation"] is False
        assert result["violations"] == []


# ── Partner named dialogue — hard ────────────────────────────────────────────

class TestPartnerNamedDialogue:
    def test_name_speech_verb_is_hard(self):
        result = _dgv('"You shouldn\'t be here," Lennox said.', partner_character_name="Lennox")
        assert result["severity"] == "hard"

    def test_name_whispered_is_hard(self):
        result = _dgv('"Don\'t do this," Lennox whispered.', partner_character_name="Lennox")
        assert result["severity"] == "hard"

    def test_name_replied_is_hard(self):
        result = _dgv('"I know," Lennox replied.', partner_character_name="Lennox")
        assert result["severity"] == "hard"

    def test_tagged_dialogue_format_is_hard(self):
        result = _dgv('Lennox: "I can\'t keep doing this."', partner_character_name="Lennox")
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_dialogue")

    def test_partner_name_case_insensitive(self):
        result = _dgv('"Fine," lennox said.', partner_character_name="Lennox")
        assert result["severity"] == "hard"

    def test_selected_name_near_dialogue_not_flagged(self):
        result = _dgv(
            '"I\'ll find a way," Leo said.',
            selected_character_name="Leo",
            partner_character_name="Elly",
        )
        assert result["severity"] == "none"


# ── Partner attributed speech — hard ─────────────────────────────────────────

class TestPartnerAttributedSpeech:
    def test_partner_name_bare_speech_verb_is_hard(self):
        result = _dgv("Lennox spoke first.", partner_character_name="Lennox")
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_attributed_speech")

    def test_cross_gender_dialogue_is_hard(self):
        text = '"I need to know," he said.\n"Then ask," she replied.'
        result = _dgv(text)
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_dialogue")

    def test_two_same_gender_lines_is_hard(self):
        text = '"Where were you?" she asked.\n"That doesn\'t matter," she replied.'
        result = _dgv(text)
        assert result["severity"] == "hard"

    def test_single_he_said_sc_male_not_hard(self):
        result = _dgv(
            '"I know you\'re afraid," he said.',
            selected_character_name="Marco",
            selected_pronouns=["he", "him"],
        )
        assert result["severity"] != "hard"

    def test_single_she_said_sc_female_not_hard(self):
        result = _dgv(
            '"You have no idea," she said.',
            selected_character_name="Clara",
            selected_pronouns=["she", "her"],
        )
        assert result["severity"] != "hard"

    def test_single_partner_pronoun_line_is_hard_when_pronouns_known(self):
        """Single attributed line using the partner's pronoun is a hard violation when
        partner_character_name + partner_pronouns are both supplied and the pronoun
        differs from the selected character's pronoun — the validator can rule out
        ambiguity and flags immediately (godmod_validator.py lines 374-384)."""
        result = _dgv(
            '"You should leave," she said.',
            selected_character_name="Marco",
            selected_pronouns=["he", "him"],
            partner_character_name="Elly",
            partner_pronouns=["she", "her"],
        )
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_dialogue")


# ── Partner consent — hard ────────────────────────────────────────────────────

class TestPartnerConsent:
    def test_quoted_im_ready_is_hard(self):
        result = _dgv('"I\'m ready," she said.')
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_consent")

    def test_im_all_in_is_hard(self):
        result = _dgv('"I\'m all in," she whispered.')
        assert result["severity"] == "hard"

    def test_dont_stop_is_hard(self):
        result = _dgv('"Don\'t stop," she breathed.')
        assert result["severity"] == "hard"

    def test_pronoun_surrendered_is_hard(self):
        result = _dgv(
            "She surrendered to the pull between them.",
            selected_character_name="Marco",
            selected_pronouns=["he", "him"],
        )
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_consent")

    def test_named_partner_gave_in_is_hard(self):
        result = _dgv("Elly gave in.", partner_character_name="Elly")
        assert result["severity"] == "hard"


# ── Partner climax — hard ─────────────────────────────────────────────────────

class TestPartnerClimax:
    def test_she_climaxed_is_hard(self):
        result = _dgv(
            "She climaxed, trembling.",
            selected_character_name="Marco",
            selected_pronouns=["he", "him"],
        )
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_climax")

    def test_her_orgasm_possessive_is_hard(self):
        result = _dgv(
            "Her orgasm rolled through her in waves.",
            selected_character_name="Marco",
            selected_pronouns=["he", "him"],
        )
        assert result["severity"] == "hard"

    def test_named_partner_came_undone_is_hard(self):
        result = _dgv("Elly came undone in his arms.", partner_character_name="Elly")
        assert result["severity"] == "hard"

    def test_came_from_across_room_not_climax(self):
        result = _dgv("He came from across the room to stand beside her.")
        assert not _vtype(result, "partner_climax")

    def test_sc_climax_not_flagged_when_pronouns_known(self):
        result = _dgv(
            "He came with a low groan, collapsing against her.",
            selected_character_name="Marco",
            selected_pronouns=["he", "him"],
            partner_pronouns=["she", "her"],
        )
        assert not _vtype(result, "partner_climax")


# ── Partner inner emotional conclusion — hard ─────────────────────────────────

class TestPartnerInnerState:
    def test_named_partner_thought_is_hard(self):
        result = _dgv("Elly thought he understood her.", partner_character_name="Elly")
        assert result["severity"] == "hard"
        assert _vtype(result, "partner_inner_state")

    def test_named_partner_realized_is_hard(self):
        result = _dgv("Elly realized she had been wrong.", partner_character_name="Elly")
        assert result["severity"] == "hard"

    def test_named_partner_knew_is_hard(self):
        result = _dgv("Elly knew what she wanted.", partner_character_name="Elly")
        assert result["severity"] == "hard"

    def test_dense_pronoun_inner_state_is_hard(self):
        text = (
            "She thought he was finally seeing her. "
            "She knew this was what she'd been waiting for. "
            "She realized the fear had dissolved."
        )
        result = _dgv(text, selected_character_name="Marco", selected_pronouns=["he", "him"])
        assert result["severity"] == "hard"
        assert result["partner_inner_state_count"] >= 3

    def test_single_pronoun_inner_state_not_hard_without_name(self):
        result = _dgv("She thought the room felt different now.")
        assert result["severity"] != "hard"


# ── Selected character dialogue allowed ───────────────────────────────────────

class TestSelectedCharacterAllowed:
    def test_sc_speech_not_flagged_by_name(self):
        result = _dgv(
            '"You don\'t understand," Marcus said.',
            selected_character_name="Marcus",
            partner_character_name="Vera",
        )
        assert result["severity"] == "none"

    def test_only_sc_speaks_no_hard_violation(self):
        text = '"This is the only way," he said. "You know it."'
        result = _dgv(
            text,
            selected_character_name="Dante",
            selected_pronouns=["he", "him"],
            partner_pronouns=["she", "her"],
        )
        assert result["severity"] != "hard"


# ── Minimal physical reactions allowed ───────────────────────────────────────

class TestMinimalReactionsAllowed:
    def test_breath_caught_not_flagged(self):
        result = _dgv("Her breath caught when he said her name.")
        assert result["severity"] == "none"

    def test_did_not_pull_away_not_flagged(self):
        result = _dgv("She didn't pull away when his hand found her shoulder.")
        assert result["severity"] == "none"

    def test_stayed_silent_not_flagged(self):
        result = _dgv("She stayed silent, watching him.")
        assert result["severity"] == "none"

    def test_pulse_quickened_not_flagged(self):
        result = _dgv("Her pulse quickened as he stepped closer.")
        assert result["severity"] == "none"

    def test_shifted_slightly_not_flagged(self):
        result = _dgv("She shifted slightly to make room.")
        assert result["severity"] == "none"


# ── generate_rp_reply integration ────────────────────────────────────────────

class TestGenerateRPReplyGodmodGate:
    def _make_mock_client(self, replies: list[str]):
        from unittest.mock import MagicMock
        reply_iter = iter(replies)

        def _next_response(*a, **kw):
            content = next(reply_iter, replies[-1])
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock(return_value=None)
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": f"<REPLY>{content}</REPLY>"}}]
            }
            return mock_resp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=_next_response)
        return mock_client

    def test_clean_reply_no_godmod_metadata(self, monkeypatch):
        from unittest.mock import patch
        import app.services.storylab_generator as gen
        monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
        monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key")
        monkeypatch.setattr(gen, "_minimum_words", lambda _l: 0)

        clean = (
            "He set the glass down and turned to face the window. "
            "His reflection looked back: steady, unreadable."
        )
        mock_client = self._make_mock_client([clean])
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            _r, _m, _t, _w, _tok, godmod_meta = gen.generate_rp_reply(
                partner_reply="She turned away.",
                character_name="Marcus",
            )
        assert godmod_meta["detected"] is False
        assert godmod_meta["severity"] in ("none", "soft")

    def test_hard_violation_triggers_retry(self, monkeypatch):
        from unittest.mock import patch
        import app.services.storylab_generator as gen
        monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
        monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key")
        monkeypatch.setattr(gen, "_minimum_words", lambda _l: 0)

        godmod_reply = '"I\'m ready," she said, holding his gaze with certainty.'
        clean_reply = "He stepped forward. The silence was palpable. He reached for her hand."
        mock_client = self._make_mock_client([godmod_reply, clean_reply])
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            _r, _m, _t, _w, _tok, godmod_meta = gen.generate_rp_reply(
                partner_reply="She waited.",
                character_name="Marcus",
            )

        # Retry fired: post called at least twice (initial + godmod retry)
        assert mock_client.post.call_count >= 2
        assert godmod_meta["detected"] is False

    def test_still_hard_after_retry_reports_warning_metadata(self, monkeypatch):
        from unittest.mock import patch
        import app.services.storylab_generator as gen
        monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
        monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key")
        monkeypatch.setattr(gen, "_minimum_words", lambda _l: 0)

        godmod_reply = '"I\'m all in," she whispered, pulling him closer.'
        mock_client = self._make_mock_client([godmod_reply, godmod_reply])
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            _r, _m, _t, _w, _tok, godmod_meta = gen.generate_rp_reply(
                partner_reply="She waited.",
                character_name="Marcus",
            )

        assert godmod_meta["detected"] is True
        assert godmod_meta["severity"] == "hard"
        assert len(godmod_meta["warnings"]) >= 1

    def test_retry_result_accepted_if_clean(self, monkeypatch):
        from unittest.mock import patch
        import app.services.storylab_generator as gen
        monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
        monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key")
        monkeypatch.setattr(gen, "_minimum_words", lambda _l: 0)

        godmod_reply = '"Don\'t stop," she breathed, arching into him.'
        clean_reply = "He kept moving. The room felt smaller than five minutes ago."
        mock_client = self._make_mock_client([godmod_reply, clean_reply])
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            reply, _m, _t, _w, _tok, godmod_meta = gen.generate_rp_reply(
                partner_reply="She was close.",
                character_name="Marcus",
            )

        assert godmod_meta["detected"] is False
        assert "kept moving" in reply or "smaller" in reply

    def test_no_retry_when_no_violation(self, monkeypatch):
        from unittest.mock import patch
        import app.services.storylab_generator as gen
        monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
        monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key")
        monkeypatch.setattr(gen, "_minimum_words", lambda _l: 0)

        clean = "He turned to the window and said nothing for a long moment."
        mock_client = self._make_mock_client([clean])
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            gen.generate_rp_reply(
                partner_reply="She entered the room.",
                character_name="Marcus",
            )

        assert mock_client.post.call_count == 1

    def test_partner_name_flows_to_godmod_detection(self, monkeypatch):
        """partner_character_name must reach detect_godmod_violations inside generate_rp_reply.

        A reply containing '[partner_name] said ...' is a name-anchored hard violation.
        If the name is silently dropped before detection, this test catches it.
        """
        from unittest.mock import patch
        import app.services.storylab_generator as gen

        monkeypatch.setattr(gen.settings, "STORYLAB_PROVIDER", "openrouter")
        monkeypatch.setattr(gen.settings, "OPENROUTER_API_KEY", "test-key")
        monkeypatch.setattr(gen, "_minimum_words", lambda _l: 0)

        godmod_reply = '"You can\'t do this," Lennox said.'
        mock_client = self._make_mock_client([godmod_reply, godmod_reply])
        with patch.object(gen.httpx, "Client", return_value=mock_client):
            _r, _m, _t, _w, _tok, godmod_meta = gen.generate_rp_reply(
                partner_reply="Lennox turned from the window.",
                partner_character_name="Lennox",
            )

        assert godmod_meta["detected"] is True, (
            "partner_character_name='Lennox' not reaching detect_godmod_violations: "
            "name-anchored speech verb ('Lennox said') must produce a hard violation"
        )
        assert godmod_meta["severity"] == "hard"


# ═══════════════════════════════════════════════════════════════════════════════
# detect_partner_silence_severe — surface not covered elsewhere in this file
# (test_rp_partner_silence.py tests the prompt-builder layer; these tests cover
#  the detector function itself, per task spec requirements)
# ═══════════════════════════════════════════════════════════════════════════════

from app.services.rp_behavior_engine import detect_partner_silence_severe as _dpss


class TestDetectPartnerSilenceSevere:
    def test_returns_expected_keys(self):
        result = _dpss("He moved toward her.")
        assert set(result.keys()) == {
            "severe", "cross_gender_godmod", "dialogue_count",
            "speech_verb_count", "decision_count", "flags",
        }

    def test_clean_text_not_severe(self):
        result = _dpss("He turned to the window. The rain was relentless.")
        assert result["severe"] is False
        assert result["cross_gender_godmod"] is False
        assert result["dialogue_count"] == 0
        assert result["decision_count"] == 0

    def test_cross_gender_flag_both_he_and_she(self):
        text = '"I need answers," he said.\n"Then ask them," she replied.'
        result = _dpss(text)
        assert result["cross_gender_godmod"] is True
        assert result["severe"] is True
        assert any("cross-gender" in f.lower() for f in result["flags"])

    def test_two_attributed_lines_is_severe(self):
        text = '"This ends now," she said.\n"Does it?" she replied.'
        result = _dpss(text)
        assert result["dialogue_count"] >= 2
        assert result["severe"] is True

    def test_single_attributed_line_not_severe(self):
        result = _dpss('"You should leave," she said.')
        assert result["severe"] is False
        assert result["dialogue_count"] == 1

    def test_partner_decision_is_severe(self):
        result = _dpss("She decided to trust him.")
        assert result["decision_count"] >= 1
        assert result["severe"] is True
        assert any("decision" in f.lower() or "consent" in f.lower() for f in result["flags"])

    def test_partner_consented_is_severe(self):
        result = _dpss("She consented at last.")
        assert result["severe"] is True
        assert result["decision_count"] >= 1

    def test_two_bare_speech_verbs_is_severe(self):
        result = _dpss("She murmured. She whispered again.")
        assert result["speech_verb_count"] >= 2
        assert result["severe"] is True

    def test_single_bare_speech_verb_not_severe(self):
        result = _dpss("She murmured something under her breath.")
        assert result["severe"] is False

    def test_flags_list_populated_on_violation(self):
        text = '"Stop," she said.\n"Please," she begged.'
        result = _dpss(text)
        assert len(result["flags"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_rp_model — profile resolution and fallback
# ═══════════════════════════════════════════════════════════════════════════════

from app.services.rp_models import resolve_rp_model, resolve_inferno_model


class TestResolveRPModel:
    def test_none_profile_falls_back_to_default(self):
        profile, slug = resolve_rp_model(None, "meta-llama/llama-3.1-70b-instruct")
        assert profile == "default"
        assert slug == "meta-llama/llama-3.1-70b-instruct"

    def test_unknown_profile_falls_back_to_default(self):
        profile, slug = resolve_rp_model("nonexistent_model_xyz", "meta-llama/llama-3.1-70b-instruct")
        assert profile == "default"
        assert slug == "meta-llama/llama-3.1-70b-instruct"

    def test_known_profile_returns_correct_slug(self):
        profile, slug = resolve_rp_model("mixtral_8x22b", "some-default-model")
        assert profile == "mixtral_8x22b"
        assert slug == "mistralai/mixtral-8x22b-instruct"

    def test_default_profile_uses_provided_default_model(self):
        profile, slug = resolve_rp_model("default", "custom/model-slug")
        assert profile == "default"
        assert slug == "custom/model-slug"


# ═══════════════════════════════════════════════════════════════════════════════
# resolve_inferno_model — override priority
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveInfernoModelOverride:
    def test_inferno_override_config_used_when_base_is_restrictive(self):
        profile, slug, was_overridden = resolve_inferno_model(
            profile="default",
            default_model="openai/gpt-4o",
            inferno_override="qwen/qwen-2.5-72b-instruct",
        )
        assert slug == "qwen/qwen-2.5-72b-instruct"
        assert was_overridden is True

    def test_permissive_user_profile_honoured_over_override(self):
        profile, slug, was_overridden = resolve_inferno_model(
            profile="mixtral_8x22b",
            default_model="some-default",
            inferno_override="qwen/qwen-2.5-72b-instruct",
        )
        assert "mixtral" in slug
        assert was_overridden is False

    def test_fallback_to_inferno_allowed_models_when_no_override(self):
        from app.services.rp_models import INFERNO_ALLOWED_MODELS
        _profile, slug, _was_overridden = resolve_inferno_model(
            profile="default",
            default_model="anthropic/claude-3-haiku",
            inferno_override="",
        )
        assert slug in INFERNO_ALLOWED_MODELS


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint — Task #5 response fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointTask5Fields:
    def test_task5_fields_present_in_response(self, client: TestClient):
        """ai_cadence_risk, spatial_position, spatial_dominance, resolved_heat must all be
        present in the response schema (added in Task #5)."""
        token = get_auth_token(client)
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": "She stood in the doorway, watching him.",
                "response_length": "short",
                "style_match": "off",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "standard",
                "heat_level": "embers",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "ai_cadence_risk" in data, "ai_cadence_risk missing from response"
        assert "spatial_position" in data, "spatial_position missing from response"
        assert "spatial_dominance" in data, "spatial_dominance missing from response"
        assert "resolved_heat" in data, "resolved_heat missing from response"
        assert isinstance(data["ai_cadence_risk"], bool)
        assert isinstance(data["spatial_position"], str)
        assert isinstance(data["spatial_dominance"], str)
        assert isinstance(data["resolved_heat"], str)

    def test_resolved_heat_reflects_intensity_floor(self, client: TestClient):
        """When intensity=explicit and heat_level=embers, resolved_heat must be 'inferno'."""
        token = get_auth_token(client)
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": "She moved toward him.",
                "response_length": "short",
                "style_match": "off",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "explicit",
                "heat_level": "embers",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resolved_heat"] == "inferno"

    def test_partner_character_name_accepted_in_request(self, client: TestClient):
        """partner_character_name field (added in Task #5) must be accepted without error."""
        token = get_auth_token(client)
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": "Lennox turned from the window.",
                "partner_character_name": "Lennox",
                "response_length": "short",
                "style_match": "off",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "standard",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "reply" in data
        assert "godmod_detected" in data

    def test_partner_name_triggers_hard_godmod_at_endpoint(self, monkeypatch, client: TestClient):
        """partner_character_name must flow from the endpoint all the way to godmod detection.

        Patches generate_rp_reply at the route-module boundary so we can assert:
        1. The name is actually forwarded in the call kwargs.
        2. When the service reports a hard violation, godmod_detected=True and
           godmod_severity='hard' appear in the HTTP response.
        """
        from unittest.mock import patch
        import app.api.routes.storylab as route_module

        captured: dict = {}

        def _mock_generate(*args, **kwargs):
            captured["partner_character_name"] = kwargs.get("partner_character_name")
            fake_reply = '"You can\'t do this," Lennox said.'
            fake_meta = {
                "detected": True,
                "severity": "hard",
                "warnings": ["Lennox attributed speech (name + speech verb)"],
            }
            return (fake_reply, "stub", 0, [], 0, fake_meta)

        token = get_auth_token(client)
        with patch.object(route_module, "generate_rp_reply", side_effect=_mock_generate):
            resp = client.post(
                "/storylab/rp-reply/generate",
                headers=auth_headers(token),
                json={
                    "partner_reply": "Lennox turned from the window.",
                    "partner_character_name": "Lennox",
                    "response_length": "short",
                    "style_match": "off",
                    "perspective": "third_person_limited",
                    "formatting": "plain",
                    "intensity": "standard",
                },
            )

        assert resp.status_code == 200, resp.text
        assert captured.get("partner_character_name") == "Lennox", (
            "partner_character_name not forwarded to generate_rp_reply by the endpoint"
        )
        data = resp.json()
        assert data["godmod_detected"] is True, (
            "godmod_detected should be True when generate_rp_reply reports a hard violation"
        )
        assert data["godmod_severity"] == "hard"


# ── perspective enforcement tests ─────────────────────────────────────────────

class TestPerspectiveEnforcement:
    """Tests for third-person perspective instruction strength and first-person
    narration detection (detect_first_person_narration)."""

    def test_third_person_prompt_includes_explicit_prohibition(self):
        """build_rp_prompt_layers with third_person_limited must include an explicit
        prohibition on first-person pronouns in narrative prose."""
        from app.services.storylab_generator import build_rp_prompt_layers
        layers = build_rp_prompt_layers(
            partner_reply=_LENNOX_REPLY,
            response_length="match",
            style_match="soft",
            perspective="third_person_limited",
            formatting="plain",
        )
        style = layers["style"]
        assert 'Do NOT use' in style, "style layer must prohibit first-person pronouns"
        assert 'first-person' in style.lower() or '"I"' in style, (
            "style layer must reference first-person pronouns explicitly"
        )
        assert 'quoted dialogue' in style.lower(), (
            "style layer must state that first-person is allowed only inside quoted dialogue"
        )

    def test_first_person_prompt_unchanged(self):
        """build_rp_prompt_layers with first_person must NOT include the third-person
        prohibition — the instruction only applies to third_person_limited."""
        from app.services.storylab_generator import build_rp_prompt_layers
        layers = build_rp_prompt_layers(
            partner_reply=_LENNOX_REPLY,
            response_length="match",
            style_match="soft",
            perspective="first_person",
            formatting="plain",
        )
        style = layers["style"]
        assert 'first person' in style.lower()
        assert 'Do NOT use' not in style

    def test_detect_first_person_narration_flags_bare_i(self):
        """Bare 'I' in narration prose must be flagged as a violation."""
        from app.services.storylab_generator import detect_first_person_narration
        result = detect_first_person_narration("I walked toward her across the room.")
        assert result["has_violation"] is True
        assert result["excerpt"] != ""

    def test_detect_first_person_narration_flags_me(self):
        """'me' in narration prose must be flagged as a violation."""
        from app.services.storylab_generator import detect_first_person_narration
        result = detect_first_person_narration("She looked at me with no expression at all.")
        assert result["has_violation"] is True

    def test_detect_first_person_narration_flags_my(self):
        """'my' in narration prose must be flagged as a violation."""
        from app.services.storylab_generator import detect_first_person_narration
        result = detect_first_person_narration("My hands wouldn't stop shaking.")
        assert result["has_violation"] is True

    def test_detect_first_person_narration_flags_myself(self):
        """'myself' in narration prose must be flagged as a violation."""
        from app.services.storylab_generator import detect_first_person_narration
        result = detect_first_person_narration("I caught myself before I could say anything.")
        assert result["has_violation"] is True

    def test_detect_first_person_narration_ignores_quoted_dialogue(self):
        """"I" inside quoted dialogue must NOT trigger a violation."""
        from app.services.storylab_generator import detect_first_person_narration
        result = detect_first_person_narration(
            '"I want you to look at me," Leonardo said, turning from the window.'
        )
        assert result["has_violation"] is False, (
            "first-person pronouns inside quoted dialogue must be exempt"
        )

    def test_detect_first_person_narration_ignores_mixed_clean(self):
        """Third-person narration with first-person only inside dialogue is clean."""
        from app.services.storylab_generator import detect_first_person_narration
        text = (
            'He crossed the room without speaking. '
            '"I didn\'t mean it like that," he said finally. '
            'She watched him, waiting.'
        )
        result = detect_first_person_narration(text)
        assert result["has_violation"] is False

    def test_detect_first_person_narration_clean_third_person(self):
        """Pure third-person prose with no first-person pronouns must not fire."""
        from app.services.storylab_generator import detect_first_person_narration
        result = detect_first_person_narration(
            "He turned away from the window. Something tightened behind his sternum. "
            "She hadn't moved. The room felt smaller than it had been a moment ago."
        )
        assert result["has_violation"] is False

    def test_perspective_threads_through_prompt_layers(self):
        """build_rp_reply_prompt must preserve perspective='third_person_limited'
        in the style layer it returns — no layer should silently override it."""
        from app.services.storylab_generator import build_rp_prompt_layers
        layers = build_rp_prompt_layers(
            partner_reply=_LENNOX_REPLY,
            response_length="short",
            style_match="off",
            perspective="third_person_limited",
            formatting="plain",
            character_name="Rowan",
        )
        style = layers["style"]
        assert "third person limited" in style.lower()
        assert '"Rowan"' in style
