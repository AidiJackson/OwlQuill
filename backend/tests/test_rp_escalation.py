"""Tests for the RP Escalation Engine: heat profiles, stage detection, resolution, continuation."""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import get_auth_token, auth_headers


# ── heat profile tests ────────────────────────────────────────────────────────

def test_heat_profiles_have_required_keys():
    from app.services.rp_escalation import RP_HEAT_PROFILES
    required = {"label", "allow_explicit_anatomy", "allow_explicit_acts", "max_stage", "prompt_block"}
    for name, profile in RP_HEAT_PROFILES.items():
        assert set(profile.keys()) == required, f"Profile '{name}' missing keys"


def test_embers_profile_all_flags_false():
    from app.services.rp_escalation import RP_HEAT_PROFILES
    embers = RP_HEAT_PROFILES["embers"]
    assert embers["allow_explicit_anatomy"] is False
    assert embers["allow_explicit_acts"] is False
    assert embers["max_stage"] == "kissing"


def test_flame_profile_max_stage_undressing():
    from app.services.rp_escalation import RP_HEAT_PROFILES
    flame = RP_HEAT_PROFILES["flame"]
    assert flame["max_stage"] == "undressing"


def test_inferno_profile_allows_anatomy_and_acts():
    from app.services.rp_escalation import RP_HEAT_PROFILES
    inferno = RP_HEAT_PROFILES["inferno"]
    assert inferno["allow_explicit_anatomy"] is True
    assert inferno["allow_explicit_acts"] is True
    assert inferno["max_stage"] == "intercourse"


def test_get_heat_prompt_block_returns_string_for_each_level():
    from app.services.rp_escalation import get_heat_prompt_block
    for level in ("embers", "flame", "inferno"):
        block = get_heat_prompt_block(level)
        assert isinstance(block, str)
        assert len(block) > 20


def test_get_heat_prompt_block_falls_back_to_flame_for_unknown():
    from app.services.rp_escalation import get_heat_prompt_block, RP_HEAT_PROFILES
    result = get_heat_prompt_block("not_a_level")
    assert result == RP_HEAT_PROFILES["flame"]["prompt_block"]


def test_intensity_to_heat_mature_maps_to_flame():
    from app.services.rp_models import intensity_to_heat
    assert intensity_to_heat("mature") == "flame"


def test_intensity_to_heat_standard_maps_to_embers():
    from app.services.rp_models import intensity_to_heat
    assert intensity_to_heat("standard") == "embers"
    assert intensity_to_heat("anything_else") == "embers"


# ── scene stage detection tests ───────────────────────────────────────────────

def test_compute_scene_stage_tension_default():
    from app.services.rp_escalation import compute_scene_stage
    assert compute_scene_stage("She stood in the hallway, watching.") == "tension"


def test_compute_scene_stage_kissing_from_kiss():
    from app.services.rp_escalation import compute_scene_stage
    assert compute_scene_stage("Their lips met softly in the dim light.") == "kissing"


def test_compute_scene_stage_undressing_from_unbutton():
    from app.services.rp_escalation import compute_scene_stage
    assert compute_scene_stage("He began to unbutton his shirt slowly.") == "undressing"


def test_compute_scene_stage_intercourse_detected():
    from app.services.rp_escalation import compute_scene_stage
    assert compute_scene_stage("He thrust forward and she gasped.") == "intercourse"


def test_compute_scene_stage_aftercare_from_afterglow():
    from app.services.rp_escalation import compute_scene_stage
    assert compute_scene_stage("They lay together in the afterglow, pulse slowed.") == "aftercare"


def test_compute_scene_stage_most_advanced_wins():
    from app.services.rp_escalation import compute_scene_stage
    # Text has both kissing and undressing signals — undressing should win (higher rank)
    text = "They kissed deeply as he unbuttoned her dress."
    assert compute_scene_stage(text) == "undressing"


# ── resolution detection tests ────────────────────────────────────────────────

def test_detect_scene_resolution_returns_expected_keys():
    from app.services.rp_escalation import detect_scene_resolution
    result = detect_scene_resolution("She waited.")
    assert "resolved" in result
    assert "reasons" in result
    assert isinstance(result["resolved"], bool)
    assert isinstance(result["reasons"], list)


def test_detect_scene_resolution_no_resolution_for_clean_text():
    from app.services.rp_escalation import detect_scene_resolution
    clean = "He stood at the window, watching the rain fall."
    result = detect_scene_resolution(clean)
    assert result["resolved"] is False
    assert result["reasons"] == []


def test_detect_scene_resolution_detects_orgasm_pattern():
    from app.services.rp_escalation import detect_scene_resolution
    text = "She fell apart completely, lost control completely, crying out."
    result = detect_scene_resolution(text)
    assert result["resolved"] is True
    assert any("orgasm" in r.lower() for r in result["reasons"])


def test_detect_scene_resolution_detects_emotional_closure():
    from app.services.rp_escalation import detect_scene_resolution
    text = "Everything was right. They were finally together."
    result = detect_scene_resolution(text)
    assert result["resolved"] is True


def test_detect_scene_resolution_detects_aftercare_stage():
    from app.services.rp_escalation import detect_scene_resolution
    text = "They lay together in the afterglow as their breathing steadied."
    result = detect_scene_resolution(text)
    assert result["resolved"] is True
    assert any("aftercare" in r.lower() for r in result["reasons"])


# ── continuation score tests ──────────────────────────────────────────────────

def test_score_collaborative_continuation_returns_float():
    from app.services.rp_escalation import score_collaborative_continuation
    score = score_collaborative_continuation("She waited.")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_score_collaborative_continuation_neutral_baseline():
    from app.services.rp_escalation import score_collaborative_continuation
    # Neutral text with no strong signals in either direction
    score = score_collaborative_continuation("He was there.")
    # Should be near baseline (0.60) — no strong positive or negative signals
    assert 0.40 <= score <= 0.80


def test_score_collaborative_continuation_high_for_open_reply():
    from app.services.rp_escalation import score_collaborative_continuation
    open_reply = (
        "||He hadn't moved from the doorway. Something tightened behind his sternum "
        "that he hadn't been expecting.||\n\n"
        '"You keep saying that," she said. The silence stretched between them.\n\n'
        "||He waited. The question hung open.||"
    )
    score = score_collaborative_continuation(open_reply)
    assert score >= 0.65


def test_score_collaborative_continuation_low_for_resolved_reply():
    from app.services.rp_escalation import score_collaborative_continuation
    resolved = (
        "She climaxed, body gave way entirely. "
        "They lay together in the afterglow, breathing slowed, pulse settled. "
        "Everything was perfect. It was over."
    )
    score = score_collaborative_continuation(resolved)
    assert score < 0.40


# ── pacing warnings tests ─────────────────────────────────────────────────────

def test_get_pacing_warnings_returns_list():
    from app.services.rp_escalation import get_pacing_warnings, detect_scene_resolution
    resolution = detect_scene_resolution("He watched her.")
    warnings = get_pacing_warnings("He watched her.", "flame", 0.65, resolution)
    assert isinstance(warnings, list)


def test_get_pacing_warnings_warns_on_resolved_scene():
    from app.services.rp_escalation import get_pacing_warnings, detect_scene_resolution
    text = "She climaxed. They lay together in the afterglow. It was over."
    resolution = detect_scene_resolution(text)
    warnings = get_pacing_warnings(text, "flame", 0.20, resolution)
    assert any("resolve" in w.lower() for w in warnings)


def test_get_pacing_warnings_warns_on_low_continuation():
    from app.services.rp_escalation import get_pacing_warnings, detect_scene_resolution
    resolution = {"resolved": False, "reasons": []}
    warnings = get_pacing_warnings("She was done.", "flame", 0.20, resolution)
    assert any("continuation" in w.lower() for w in warnings)


def test_get_pacing_warnings_embers_stage_mismatch():
    from app.services.rp_escalation import get_pacing_warnings, detect_scene_resolution
    # Embers heat with escalation-stage text
    text = "He unbuttoned her dress and pressed her against the wall."
    resolution = detect_scene_resolution(text)
    warnings = get_pacing_warnings(text, "embers", 0.60, resolution)
    assert any("embers" in w.lower() for w in warnings)


def test_get_pacing_warnings_clean_scene_no_warnings():
    from app.services.rp_escalation import get_pacing_warnings, detect_scene_resolution
    text = (
        "||He turned to the window. The city below was quiet.||\n\n"
        '"Tell me when you know," he said.\n\n'
        "||He let the silence sit.||"
    )
    resolution = detect_scene_resolution(text)
    score = 0.72
    warnings = get_pacing_warnings(text, "flame", score, resolution)
    assert warnings == []


# ── endpoint integration tests ────────────────────────────────────────────────

def test_rp_reply_endpoint_returns_escalation_fields(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She stood at the window, watching him.",
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
    assert "detected_stage" in data
    assert "continuation_score" in data
    assert "resolution_detected" in data
    assert "pacing_warnings" in data
    assert isinstance(data["detected_stage"], str)
    assert isinstance(data["continuation_score"], float)
    assert isinstance(data["resolution_detected"], bool)
    assert isinstance(data["pacing_warnings"], list)


def test_rp_reply_endpoint_heat_level_flame(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She stepped closer, something shifting in her expression.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "mature",
            "heat_level": "flame",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reply"]


def test_rp_reply_endpoint_heat_level_inferno(client: TestClient):
    token = get_auth_token(client)
    from tests.conftest import make_admin
    # Explicit/inferno heat is admin-only during launch (explicit_admin_only gate).
    make_admin("user@test.com")
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She pulled him toward her.",
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
    assert data["reply"]


def test_rp_reply_endpoint_invalid_heat_level_falls_back(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She waited.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
            "heat_level": "not_a_real_level",
        },
    )
    # Should not 400/500 — validator falls back to flame
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reply"]


def test_rp_reply_endpoint_continuation_score_in_range(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "||She hadn't moved. Something in her expression had shifted.||\n\n\"I heard you,\" she said. Her voice was level.\n\n||She waited.||",
            "response_length": "match",
            "style_match": "strong",
            "perspective": "third_person_limited",
            "formatting": "roleplay_bars",
            "intensity": "standard",
            "heat_level": "embers",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert 0.0 <= data["continuation_score"] <= 1.0


# ── prompt layer composition tests ───────────────────────────────────────────

def test_build_rp_prompt_layers_returns_all_keys():
    from app.services.storylab_generator import build_rp_prompt_layers
    layers = build_rp_prompt_layers(
        partner_reply="She waited.",
        response_length="short",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="flame",
    )
    expected_keys = {
        "identity", "style", "heat",
        "behavior_enforcement", "partner_control", "scene_engine",
        "archetype", "prose_polish",
        "prose_style",  # backward-compat alias
        "role_lock", "pacing", "scene_state", "continuation",
    }
    assert expected_keys.issubset(set(layers.keys()))


def test_build_rp_prompt_layers_heat_block_contains_heat_label():
    from app.services.storylab_generator import build_rp_prompt_layers
    for heat in ("embers", "flame", "inferno"):
        layers = build_rp_prompt_layers(
            partner_reply="She waited.",
            response_length="short",
            style_match="soft",
            perspective="third_person_limited",
            formatting="plain",
            heat_level=heat,
        )
        assert heat.upper() in layers["heat"].upper()


def test_build_rp_prompt_layers_partner_reply_in_scene_state():
    from app.services.storylab_generator import build_rp_prompt_layers
    partner = "She crossed the room without speaking."
    layers = build_rp_prompt_layers(
        partner_reply=partner,
        response_length="short",
        style_match="off",
        perspective="third_person_limited",
        formatting="plain",
        heat_level="embers",
    )
    assert partner in layers["scene_state"]


def test_build_rp_reply_prompt_uses_heat_level():
    from app.services.storylab_generator import build_rp_reply_prompt
    msgs = build_rp_reply_prompt(
        partner_reply="She waited.",
        response_length="short",
        style_match="soft",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        heat_level="inferno",
    )
    assert len(msgs) == 2
    user_content = msgs[1]["content"]
    assert "INFERNO" in user_content.upper()
