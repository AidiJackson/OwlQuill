"""Tests for the RP Reply bake-off system: model routing, quality evaluator, anti-godmodding."""
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


# ── rp_models unit tests ──────────────────────────────────────────────────────

def test_resolve_rp_model_default():
    from app.services.rp_models import resolve_rp_model
    profile, slug = resolve_rp_model("default", "some/default-model")
    assert profile == "default"
    assert slug == "some/default-model"


def test_resolve_rp_model_known_profile():
    from app.services.rp_models import resolve_rp_model, RP_REPLY_MODELS
    profile, slug = resolve_rp_model("mixtral_8x22b", "fallback/model")
    assert profile == "mixtral_8x22b"
    assert slug == RP_REPLY_MODELS["mixtral_8x22b"]
    assert "mixtral" in slug.lower()


def test_resolve_rp_model_unknown_falls_back():
    from app.services.rp_models import resolve_rp_model
    profile, slug = resolve_rp_model("nonexistent_model_xyz", "fallback/model")
    assert profile == "default"
    assert slug == "fallback/model"


def test_resolve_rp_model_none_falls_back():
    from app.services.rp_models import resolve_rp_model
    profile, slug = resolve_rp_model(None, "fallback/model")
    assert profile == "default"
    assert slug == "fallback/model"


def test_all_named_profiles_have_slugs():
    from app.services.rp_models import RP_REPLY_MODELS
    for profile, slug in RP_REPLY_MODELS.items():
        if profile != "default":
            assert slug, f"Profile '{profile}' has empty model slug"
            assert "/" in slug, f"Profile '{profile}' slug looks malformed: {slug!r}"


# ── quality evaluator unit tests ──────────────────────────────────────────────

def test_evaluate_rp_reply_quality_returns_expected_keys():
    from app.services.rp_models import evaluate_rp_reply_quality
    result = evaluate_rp_reply_quality("He turned away. Not yet ready to admit what she already knew.")
    expected_keys = {"length_score", "dialogue_score", "repetition_score", "godmodding_risk", "format_score"}
    assert set(result.keys()) == expected_keys


def test_evaluate_rp_reply_quality_scores_in_range():
    from app.services.rp_models import evaluate_rp_reply_quality
    result = evaluate_rp_reply_quality(_LENNOX_REPLY)
    for key, val in result.items():
        assert 0.0 <= val <= 1.0, f"{key}={val} out of [0,1]"


def test_evaluate_rp_reply_quality_short_reply_low_length_score():
    from app.services.rp_models import evaluate_rp_reply_quality
    result = evaluate_rp_reply_quality("He nodded.")
    assert result["length_score"] < 0.5


def test_evaluate_rp_reply_quality_long_reply_high_length_score():
    from app.services.rp_models import evaluate_rp_reply_quality
    long_reply = " ".join(["word"] * 150)
    result = evaluate_rp_reply_quality(long_reply)
    assert result["length_score"] == 1.0


def test_evaluate_rp_reply_quality_balanced_reply_good_dialogue_score():
    from app.services.rp_models import evaluate_rp_reply_quality
    balanced = (
        '||He stood at the window, watching the rain trace lines down the glass.||\n\n'
        '"You already knew," he said.\n\n'
        '||He didn\'t look away from the window even as he heard her move.||\n\n'
        '"Then why ask." Not a question.'
    )
    result = evaluate_rp_reply_quality(balanced)
    assert result["dialogue_score"] >= 0.7


def test_evaluate_rp_reply_quality_no_godmodding_risk_clean_reply():
    from app.services.rp_models import evaluate_rp_reply_quality
    clean = (
        "||He turned away from the window, something tightening behind his sternum.||\n\n"
        '"I heard you," he said. His voice was quiet.\n\n'
        "||He moved to the table. Put some distance between them.||"
    )
    result = evaluate_rp_reply_quality(clean)
    assert result["godmodding_risk"] < 0.3


def test_evaluate_rp_reply_quality_godmodding_risk_elevated_for_partner_reactions():
    from app.services.rp_models import evaluate_rp_reply_quality
    godmodded = (
        "||He stepped toward her. She gasped. She trembled. She flinched back. "
        "She felt her heart race. She thought he was terrifying.||\n\n"
        '"You know what I want," he said.\n\n'
        "||She recoiled. She stepped back. She stiffened.||"
    )
    result = evaluate_rp_reply_quality(godmodded)
    assert result["godmodding_risk"] > 0.3


def test_evaluate_format_score_balanced_bars():
    from app.services.rp_models import evaluate_rp_reply_quality
    good_bars = "||Narrative paragraph one.||\n\n\"Dialogue.\"\n\n||Narrative paragraph two.||"
    result = evaluate_rp_reply_quality(good_bars)
    assert result["format_score"] == 1.0


def test_evaluate_format_score_mismatched_bars():
    from app.services.rp_models import evaluate_rp_reply_quality
    bad_bars = "||Narrative paragraph one.\n\n\"Dialogue.\"\n\n||Narrative paragraph two.||"
    result = evaluate_rp_reply_quality(bad_bars)
    assert result["format_score"] < 1.0


# ── anti-godmodding tightening tests ─────────────────────────────────────────

def test_anti_godmod_warns_on_partner_reactions():
    from app.services.storylab_generator import _check_rp_reply_output
    from app.services.godmod_validator import detect_godmod_violations
    godmodded = (
        "He moved toward her. She gasped. She flinched and stepped back from him. "
        "She trembled. He watched her reaction carefully."
    )
    # Task #6: _check_rp_reply_output no longer emits physical-reaction warnings —
    # that check was removed because detect_godmod_violations handles it with retry support.
    warnings = _check_rp_reply_output(godmodded)
    assert not any("physical reaction" in w.lower() or "partner" in w.lower() for w in warnings)
    # detect_godmod_violations must still catch involuntary physical reactions as a hard violation.
    result = detect_godmod_violations(godmodded, selected_pronouns=["he", "him"])
    assert result["has_violation"] is True
    assert result["severity"] == "hard"


def test_anti_godmod_warns_on_consent_resolution():
    from app.services.storylab_generator import _check_rp_reply_output
    from app.services.godmod_validator import detect_godmod_violations
    consent_text = (
        "He reached for her and she let him. She allowed him to take her hand. "
        "She permitted him to step closer. She accepted his presence in the room."
    )
    # Task #6: _check_rp_reply_output no longer emits consent/agency warnings —
    # that check was removed because detect_godmod_violations handles it with retry support.
    warnings = _check_rp_reply_output(consent_text)
    assert not any("consent" in w.lower() or "agency" in w.lower() for w in warnings)
    # detect_godmod_violations must still catch consent/agency resolution as a hard violation.
    result = detect_godmod_violations(consent_text, selected_pronouns=["he", "him"])
    assert result["has_violation"] is True
    assert result["severity"] == "hard"


def test_anti_godmod_no_warnings_for_clean_reply():
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

def test_rp_reply_returns_model_used(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _LENNOX_REPLY,
            "response_length": "match",
            "style_match": "strong",
            "perspective": "third_person_limited",
            "formatting": "roleplay_bars",
            "intensity": "mature",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "model_used" in data
    assert isinstance(data["model_used"], str)
    assert len(data["model_used"]) > 0


def test_rp_reply_returns_generation_time(client: TestClient):
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
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "generation_time_ms" in data
    assert isinstance(data["generation_time_ms"], int)
    assert data["generation_time_ms"] >= 0


def test_rp_reply_default_model_profile(client: TestClient):
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
            "model_profile": "default",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reply"]


def test_rp_reply_invalid_model_profile_falls_back(client: TestClient):
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She stepped back.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
            "model_profile": "not_a_real_model_xyz",
        },
    )
    # Should not 400/500 — falls back gracefully to default
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reply"]


def test_rp_reply_known_profile_accepted(client: TestClient):
    token = get_auth_token(client)
    for profile in ("mixtral_8x22b", "mixtral_8x7b", "llama_70b", "qwen_72b"):
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": "She looked at him.",
                "response_length": "short",
                "style_match": "off",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "standard",
                "model_profile": profile,
            },
        )
        assert resp.status_code == 200, f"Failed for profile={profile}: {resp.text}"
        data = resp.json()
        assert data["reply"], f"Empty reply for profile={profile}"


# ── Phase 8: Benchmarking — archetypes × heat × quality ──────────────────────
# These tests run the style engine against all archetypes and heat levels in stub
# mode, asserting dimensional parity and valid scores rather than LLM quality.

_BENCH_SCENE = (
    "||Lennox turned away from the rain-streaked window, her shoulder brushing the cold stone. "
    "The candle on the sill barely held against the draught.||\n\n"
    '"I know what you came here for," she said. "The question is whether you do."\n\n'
    "||She did not move. She watched him the way the storm watched the coast — "
    "without hurry, without mercy.||"
)

_ALL_ARCHETYPES = [
    "cinematic_dark_romance",
    "gothic_obsession",
    "slow_burn_tension",
    "dangerous_devotion",
    "primal_restraint",
]

_ALL_HEAT_LEVELS = ["embers", "flame", "inferno"]


def test_benchmark_all_archetypes_endpoint_200(client: TestClient):
    """All archetypes should return 200 and a non-empty reply."""
    token = get_auth_token(client)
    for archetype in _ALL_ARCHETYPES:
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": _BENCH_SCENE,
                "response_length": "match",
                "style_match": "soft",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "mature",
                "heat_level": "flame",
                "style_archetype": archetype,
            },
        )
        assert resp.status_code == 200, f"archetype={archetype}: {resp.text}"
        data = resp.json()
        assert data["reply"], f"Empty reply for archetype={archetype}"


def test_benchmark_all_heat_levels_endpoint_200(client: TestClient):
    """All heat levels should return 200 and a non-empty reply."""
    token = get_auth_token(client)
    from tests.conftest import make_admin
    # Explicit/inferno heat is admin-only during launch (explicit_admin_only gate).
    make_admin("user@test.com")
    for heat in _ALL_HEAT_LEVELS:
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": _BENCH_SCENE,
                "response_length": "match",
                "style_match": "soft",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "mature",
                "heat_level": heat,
                "style_archetype": "cinematic_dark_romance",
            },
        )
        assert resp.status_code == 200, f"heat={heat}: {resp.text}"
        data = resp.json()
        assert data["reply"], f"Empty reply for heat={heat}"


def test_benchmark_response_has_all_quality_fields(client: TestClient):
    """Response must include all quality + style engine diagnostic fields."""
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _BENCH_SCENE,
            "response_length": "match",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "mature",
            "heat_level": "flame",
            "style_archetype": "gothic_obsession",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    expected_fields = {
        "reply", "warnings", "model_used", "generation_time_ms",
        "detected_stage", "continuation_score", "resolution_detected",
        "pacing_warnings", "style_warnings",
    }
    for field in expected_fields:
        assert field in data, f"Response missing field: {field}"


def test_benchmark_continuation_score_in_range_for_all_archetypes(client: TestClient):
    """continuation_score should be 0–1 for every archetype."""
    token = get_auth_token(client)
    for archetype in _ALL_ARCHETYPES:
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": _BENCH_SCENE,
                "response_length": "match",
                "style_match": "soft",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "mature",
                "heat_level": "flame",
                "style_archetype": archetype,
            },
        )
        assert resp.status_code == 200
        score = resp.json()["continuation_score"]
        assert 0.0 <= score <= 1.0, f"archetype={archetype}: continuation_score={score} out of range"


def test_benchmark_style_warnings_is_list(client: TestClient):
    """style_warnings must always be a list, even when empty."""
    token = get_auth_token(client)
    from tests.conftest import make_admin
    # Explicit/inferno heat is admin-only during launch (explicit_admin_only gate).
    make_admin("user@test.com")
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _BENCH_SCENE,
            "response_length": "match",
            "style_match": "soft",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "mature",
            "heat_level": "inferno",
            "style_archetype": "primal_restraint",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["style_warnings"], list)


def test_benchmark_invalid_archetype_falls_back(client: TestClient):
    """Unknown style_archetype should not 400 — it falls back to default."""
    token = get_auth_token(client)
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": _BENCH_SCENE,
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "standard",
            "heat_level": "embers",
            "style_archetype": "not_a_real_archetype_xyz",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reply"]


def test_benchmark_archetypes_produce_valid_detected_stage(client: TestClient):
    """detected_stage must be one of the known stage values for every archetype."""
    token = get_auth_token(client)
    valid_stages = {"tension", "confession", "first_touch", "kissing", "heavy_makeout", "undressing", "oral", "intercourse", "aftercare"}
    for archetype in _ALL_ARCHETYPES:
        resp = client.post(
            "/storylab/rp-reply/generate",
            headers=auth_headers(token),
            json={
                "partner_reply": _BENCH_SCENE,
                "response_length": "short",
                "style_match": "soft",
                "perspective": "third_person_limited",
                "formatting": "plain",
                "intensity": "standard",
                "heat_level": "embers",
                "style_archetype": archetype,
            },
        )
        assert resp.status_code == 200
        stage = resp.json()["detected_stage"]
        assert stage in valid_stages, f"archetype={archetype}: unexpected stage '{stage}'"


def test_benchmark_cross_matrix_no_errors(client: TestClient):
    """Spot-check a cross-product of archetypes × heat levels — none should 500."""
    token = get_auth_token(client)
    from tests.conftest import make_admin
    # Explicit/inferno heat is admin-only during launch (explicit_admin_only gate).
    make_admin("user@test.com")
    # 3 archetypes × 3 heat = 9 requests
    spot_archetypes = ["cinematic_dark_romance", "slow_burn_tension", "primal_restraint"]
    for archetype in spot_archetypes:
        for heat in _ALL_HEAT_LEVELS:
            resp = client.post(
                "/storylab/rp-reply/generate",
                headers=auth_headers(token),
                json={
                    "partner_reply": _BENCH_SCENE,
                    "response_length": "short",
                    "style_match": "soft",
                    "perspective": "third_person_limited",
                    "formatting": "plain",
                    "intensity": "mature",
                    "heat_level": heat,
                    "style_archetype": archetype,
                },
            )
            assert resp.status_code == 200, (
                f"archetype={archetype}, heat={heat}: HTTP {resp.status_code} — {resp.text}"
            )
            assert resp.json()["reply"]


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration Stabilization V1 — New Tests
# ══════════════════════════════════════════════════════════════════════════════

# ── Inferno model routing ─────────────────────────────────────────────────────

def test_is_restrictive_anthropic():
    from app.services.rp_models import _is_restrictive
    assert _is_restrictive("anthropic/claude-3.5-sonnet") is True


def test_is_restrictive_openai():
    from app.services.rp_models import _is_restrictive
    assert _is_restrictive("openai/gpt-4") is True


def test_is_restrictive_google():
    from app.services.rp_models import _is_restrictive
    assert _is_restrictive("google/gemini-pro") is True


def test_is_restrictive_permissive_models():
    from app.services.rp_models import _is_restrictive
    assert _is_restrictive("qwen/qwen-2.5-72b-instruct") is False
    assert _is_restrictive("mistralai/mixtral-8x22b-instruct") is False
    assert _is_restrictive("meta-llama/llama-3.1-70b-instruct") is False


def test_resolve_inferno_model_routes_away_from_restrictive():
    from app.services.rp_models import resolve_inferno_model, INFERNO_ALLOWED_MODELS
    _profile, slug, was_overridden = resolve_inferno_model(
        profile="default",
        default_model="anthropic/claude-3.5-sonnet",
    )
    assert slug in INFERNO_ALLOWED_MODELS
    assert was_overridden is True


def test_resolve_inferno_model_honors_permissive_user_profile():
    from app.services.rp_models import resolve_inferno_model
    _profile, slug, was_overridden = resolve_inferno_model(
        profile="qwen_72b",
        default_model="anthropic/claude-3.5-sonnet",
    )
    assert "qwen" in slug.lower()
    assert was_overridden is False


def test_resolve_inferno_model_uses_config_override():
    from app.services.rp_models import resolve_inferno_model
    override_slug = "mistralai/mixtral-8x22b-instruct"
    _profile, slug, was_overridden = resolve_inferno_model(
        profile="default",
        default_model="anthropic/claude-3.5-sonnet",
        inferno_override=override_slug,
    )
    assert slug == override_slug
    assert was_overridden is True


def test_resolve_inferno_model_skips_restrictive_override():
    from app.services.rp_models import resolve_inferno_model, INFERNO_ALLOWED_MODELS
    # A restrictive override should be ignored and fallback to allowed list
    _profile, slug, _overridden = resolve_inferno_model(
        profile="default",
        default_model="anthropic/claude-3.5-sonnet",
        inferno_override="openai/gpt-4",
    )
    assert slug in INFERNO_ALLOWED_MODELS


def test_inferno_allowed_models_all_permissive():
    from app.services.rp_models import INFERNO_ALLOWED_MODELS, _is_restrictive
    for slug in INFERNO_ALLOWED_MODELS:
        assert not _is_restrictive(slug), f"INFERNO_ALLOWED_MODELS entry {slug!r} is restrictive"


# ── Intensity → heat fallback ─────────────────────────────────────────────────

def test_effective_heat_explicit_overrides_flame():
    from app.services.rp_models import effective_heat_level
    assert effective_heat_level("flame", "explicit") == "inferno"


def test_effective_heat_mature_overrides_embers():
    from app.services.rp_models import effective_heat_level
    assert effective_heat_level("embers", "mature") == "flame"


def test_effective_heat_inferno_not_downgraded_by_standard():
    from app.services.rp_models import effective_heat_level
    assert effective_heat_level("inferno", "standard") == "inferno"


def test_effective_heat_no_downgrade_when_heat_higher():
    from app.services.rp_models import effective_heat_level
    assert effective_heat_level("inferno", "mature") == "inferno"


def test_intensity_explicit_maps_to_inferno():
    from app.services.rp_models import intensity_to_heat
    assert intensity_to_heat("explicit") == "inferno"


def test_rp_reply_explicit_intensity_accepted(client: TestClient):
    """intensity=explicit is a valid value and maps to inferno heat."""
    token = get_auth_token(client)
    from tests.conftest import make_admin
    # Explicit/inferno heat is admin-only during launch (explicit_admin_only gate).
    make_admin("user@test.com")
    resp = client.post(
        "/storylab/rp-reply/generate",
        headers=auth_headers(token),
        json={
            "partner_reply": "She pulled him close.",
            "response_length": "short",
            "style_match": "off",
            "perspective": "third_person_limited",
            "formatting": "plain",
            "intensity": "explicit",
            "heat_level": "inferno",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reply"]
