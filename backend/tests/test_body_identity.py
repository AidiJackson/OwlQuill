"""Tests for body identity pack — body morphology and tattoo layout anchor slots."""
import pytest
from unittest.mock import MagicMock, patch
from tests.conftest import auth_headers, get_auth_token

# Minimal 1x1 PNG bytes returned by mock provider
_STUB_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
    b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _mock_provider():
    p = MagicMock()
    p.generate_image.return_value = _STUB_PNG
    p.generate_with_anchors.return_value = _STUB_PNG
    p.supports_multi_image_input = False
    p.provider_name = "stub"
    return p


# ── Helpers ────────────────────────────────────────────────────────────

def _create_character(client, headers, name="BIChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── ImageKindEnum values ────────────────────────────────────────────────

def test_body_identity_image_kind_values_exist():
    from app.models.character_image import ImageKindEnum
    values = {e.value for e in ImageKindEnum}
    assert "identity_body_front" in values
    assert "identity_body_three_quarter" in values
    assert "identity_body_back" in values
    assert "identity_tattoo_layout" in values


# ── Prompt builder unit tests ───────────────────────────────────────────

def test_body_slot_prompt_body_front_includes_front_pose():
    from app.api.routes.body_identity import build_body_slot_prompt
    prompt = build_body_slot_prompt("body_front", character_name="Aria")
    assert "front" in prompt.lower()
    assert "Aria" in prompt


def test_body_slot_prompt_body_three_quarter_includes_angle():
    from app.api.routes.body_identity import build_body_slot_prompt
    prompt = build_body_slot_prompt("body_three_quarter", character_name="Aria")
    assert "3/4" in prompt or "three" in prompt.lower()


def test_body_slot_prompt_body_back_includes_back_view():
    from app.api.routes.body_identity import build_body_slot_prompt
    prompt = build_body_slot_prompt("body_back", character_name="Aria")
    assert "back" in prompt.lower()


def test_body_slot_prompt_tattoo_layout_requires_both_arms_visible():
    from app.api.routes.body_identity import build_body_slot_prompt
    prompt = build_body_slot_prompt("tattoo_layout", character_name="Aria")
    assert "arm" in prompt.lower()
    assert "no crossed arms" in prompt.lower() or "both arms" in prompt.lower()


def test_body_slot_prompt_tattoo_layout_includes_body_canon_markings():
    from app.api.routes.body_identity import build_body_slot_prompt
    prompt = build_body_slot_prompt(
        "tattoo_layout",
        character_name="Aria",
        body_canon_str="wolf head tattoo on left upper arm",
    )
    assert "wolf head" in prompt


def test_body_slot_prompt_includes_identity_lock_string():
    from app.api.routes.body_identity import build_body_slot_prompt
    prompt = build_body_slot_prompt(
        "body_front",
        character_name="Aria",
        identity_lock_string="tall athletic female elf silver hair",
    )
    assert "tall athletic" in prompt


def test_body_slot_prompt_capped_at_800_chars():
    from app.api.routes.body_identity import build_body_slot_prompt
    # Provide very long strings that would overflow
    long_lock = "A" * 400
    long_canon = "B" * 400
    for slot in ("body_front", "body_three_quarter", "body_back", "tattoo_layout"):
        prompt = build_body_slot_prompt(slot, "X", identity_lock_string=long_lock, body_canon_str=long_canon)
        assert len(prompt) <= 800


def test_body_slot_prompt_unknown_slot_returns_fallback():
    from app.api.routes.body_identity import build_body_slot_prompt
    prompt = build_body_slot_prompt("unknown_slot", character_name="Aria")
    assert len(prompt) > 0


# ── JSON helpers unit tests ─────────────────────────────────────────────

def test_load_body_slots_returns_empty_dict_when_no_json():
    from app.api.routes.body_identity import _load_body_slots
    from app.models.character import Character as CharacterModel
    char = CharacterModel()
    char.identity_anchor_json = None
    assert _load_body_slots(char) == {}


def test_load_body_slots_returns_empty_when_no_body_slots_key():
    import json
    from app.api.routes.body_identity import _load_body_slots
    from app.models.character import Character as CharacterModel
    char = CharacterModel()
    char.identity_anchor_json = json.dumps({"anchors": {}})
    assert _load_body_slots(char) == {}


def test_save_and_load_body_slot_roundtrip():
    import json
    from app.api.routes.body_identity import _load_body_slots, _save_body_slot
    from app.models.character import Character as CharacterModel
    char = CharacterModel()
    char.identity_anchor_json = None
    _save_body_slot(char, "body_front", {"url": "/static/generated/test.png", "status": "generated", "prompt": "test"})
    slots = _load_body_slots(char)
    assert slots["body_front"]["url"] == "/static/generated/test.png"
    assert slots["body_front"]["status"] == "generated"


def test_save_body_slot_preserves_other_slots():
    from app.api.routes.body_identity import _load_body_slots, _save_body_slot
    from app.models.character import Character as CharacterModel
    char = CharacterModel()
    char.identity_anchor_json = None
    _save_body_slot(char, "body_front", {"url": "/a.png", "status": "locked", "prompt": "p1"})
    _save_body_slot(char, "tattoo_layout", {"url": "/b.png", "status": "generated", "prompt": "p2"})
    slots = _load_body_slots(char)
    assert "body_front" in slots
    assert "tattoo_layout" in slots
    assert slots["body_front"]["url"] == "/a.png"
    assert slots["tattoo_layout"]["url"] == "/b.png"


# ── API endpoint tests ─────────────────────────────────────────────────

def test_list_body_slots_returns_four_keys(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    resp = client.get(f"/characters/{char_id}/identity/body-slots", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["character_id"] == char_id
    keys = {s["key"] for s in data["slots"]}
    assert keys == {"body_front", "body_three_quarter", "body_back", "tattoo_layout"}


def test_list_body_slots_all_missing_initially(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    resp = client.get(f"/characters/{char_id}/identity/body-slots", headers=headers)
    assert resp.status_code == 200
    for slot in resp.json()["slots"]:
        assert slot["status"] == "missing"
        assert slot["url"] is None


def test_list_body_slots_requires_auth(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    resp = client.get(f"/characters/{char_id}/identity/body-slots")
    assert resp.status_code in (401, 403)


def test_generate_body_slot_creates_image(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    with patch("app.api.routes.body_identity.get_provider_for_option", return_value=_mock_provider()):
        resp = client.post(f"/characters/{char_id}/identity/body-slots/body_front/generate", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    front = next(s for s in data["slots"] if s["key"] == "body_front")
    assert front["status"] == "generated"
    assert front["url"] is not None


def test_generate_body_slot_all_four_slots(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    for slot_key in ("body_front", "body_three_quarter", "body_back", "tattoo_layout"):
        with patch("app.api.routes.body_identity.get_provider_for_option", return_value=_mock_provider()):
            resp = client.post(f"/characters/{char_id}/identity/body-slots/{slot_key}/generate", headers=headers)
        assert resp.status_code == 200, f"slot={slot_key}: {resp.text}"
        entry = next(s for s in resp.json()["slots"] if s["key"] == slot_key)
        assert entry["status"] == "generated"


def test_generate_body_slot_unknown_slot_returns_422(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    resp = client.post(f"/characters/{char_id}/identity/body-slots/nonexistent_slot/generate", headers=headers)
    assert resp.status_code == 422


def test_lock_body_slot_transitions_status(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    with patch("app.api.routes.body_identity.get_provider_for_option", return_value=_mock_provider()):
        client.post(f"/characters/{char_id}/identity/body-slots/body_front/generate", headers=headers)
    resp = client.post(f"/characters/{char_id}/identity/body-slots/body_front/lock", headers=headers)
    assert resp.status_code == 200
    front = next(s for s in resp.json()["slots"] if s["key"] == "body_front")
    assert front["status"] == "locked"


def test_lock_body_slot_without_generate_returns_409(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    resp = client.post(f"/characters/{char_id}/identity/body-slots/tattoo_layout/lock", headers=headers)
    assert resp.status_code == 409


def test_replace_body_slot_regenerates(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    with patch("app.api.routes.body_identity.get_provider_for_option", return_value=_mock_provider()):
        client.post(f"/characters/{char_id}/identity/body-slots/body_back/generate", headers=headers)
        client.post(f"/characters/{char_id}/identity/body-slots/body_back/lock", headers=headers)
        resp = client.post(f"/characters/{char_id}/identity/body-slots/body_back/replace", headers=headers)
    assert resp.status_code == 200
    back = next(s for s in resp.json()["slots"] if s["key"] == "body_back")
    assert back["status"] == "generated"


def test_generate_body_slot_requires_ownership(client):
    token1 = get_auth_token(client, email="bi_owner@test.com", username="bi_owner")
    token2 = get_auth_token(client, email="bi_other@test.com", username="bi_other")
    char_id = _create_character(client, auth_headers(token1))
    resp = client.post(
        f"/characters/{char_id}/identity/body-slots/body_front/generate",
        headers=auth_headers(token2),
    )
    assert resp.status_code == 403


def test_list_body_slots_requires_ownership(client):
    token1 = get_auth_token(client, email="bi_own2@test.com", username="bi_own2")
    token2 = get_auth_token(client, email="bi_oth2@test.com", username="bi_oth2")
    char_id = _create_character(client, auth_headers(token1))
    resp = client.get(
        f"/characters/{char_id}/identity/body-slots",
        headers=auth_headers(token2),
    )
    assert resp.status_code == 403


def test_generate_body_slot_stores_prompt(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    with patch("app.api.routes.body_identity.get_provider_for_option", return_value=_mock_provider()):
        resp = client.post(f"/characters/{char_id}/identity/body-slots/tattoo_layout/generate", headers=headers)
    assert resp.status_code == 200
    slot = next(s for s in resp.json()["slots"] if s["key"] == "tattoo_layout")
    assert slot["prompt"] is not None
    assert len(slot["prompt"]) > 0
    assert "tattoo" in slot["prompt"].lower() or "marking" in slot["prompt"].lower()


def test_lock_body_slot_unknown_slot_returns_422(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    resp = client.post(f"/characters/{char_id}/identity/body-slots/bad_slot/lock", headers=headers)
    assert resp.status_code == 422


# ── Image generation body identity injection ────────────────────────────

def test_body_identity_visibility_signals_include_shirtless():
    from app.api.routes.image_generator import _BODY_VISIBLE_SIGNALS
    assert "shirtless" in _BODY_VISIBLE_SIGNALS


def test_body_identity_visibility_signals_include_full_body():
    from app.api.routes.image_generator import _BODY_VISIBLE_SIGNALS
    assert "full body" in _BODY_VISIBLE_SIGNALS


def test_body_identity_visibility_signals_not_triggered_by_plain_portrait():
    from app.api.routes.image_generator import _BODY_VISIBLE_SIGNALS
    prompt = "portrait of a woman with silver hair"
    assert not any(sig in prompt.lower() for sig in _BODY_VISIBLE_SIGNALS)


def test_max_provider_refs_constant():
    from app.api.routes.image_generator import _MAX_PROVIDER_REFS
    assert _MAX_PROVIDER_REFS == 6


def test_load_body_slots_importable_from_body_identity():
    from app.api.routes.body_identity import _load_body_slots
    assert callable(_load_body_slots)
