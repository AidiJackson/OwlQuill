"""Tests for Style Shops system."""
import json
import pytest
from tests.conftest import auth_headers, get_auth_token


@pytest.fixture(autouse=True)
def seed_presets(db_session):
    """Seed style presets into the test DB before each test."""
    from app.core.style_shop_seed import seed_style_presets
    seed_style_presets(db_session)


# ── Helpers ────────────────────────────────────────────────────────────

def _create_character(client, headers, name="TestChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _get_presets(client, shop_type=None):
    url = "/style-shops/presets"
    if shop_type:
        url += f"?shop_type={shop_type}"
    resp = client.get(url)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get_preset_by_slug(client, slug):
    presets = _get_presets(client)
    return next((p for p in presets if p["slug"] == slug), None)


def _apply(client, headers, char_id, preset_id, placement=None):
    body = {"preset_id": preset_id}
    if placement:
        body["placement"] = placement
    return client.post(f"/characters/{char_id}/style-elements", json=body, headers=headers)


def _list_elements(client, headers, char_id):
    resp = client.get(f"/characters/{char_id}/style-elements", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["elements"]


def _delete_element(client, headers, char_id, element_id):
    return client.delete(f"/characters/{char_id}/style-elements/{element_id}", headers=headers)


# ── Preset list tests ──────────────────────────────────────────────────

def test_presets_list_all(client):
    presets = _get_presets(client)
    assert len(presets) >= 18  # all seeds loaded
    slugs = {p["slug"] for p in presets}
    assert "barber-short-spiked-blond" in slugs
    assert "weapon-katana" in slugs


def test_presets_filter_by_shop_type(client):
    presets = _get_presets(client, shop_type="barber")
    assert all(p["shop_type"] == "barber" for p in presets)
    assert len(presets) == 5


def test_presets_have_prompt_token(client):
    presets = _get_presets(client)
    for p in presets:
        assert p["prompt_token"], f"Preset {p['slug']} missing prompt_token"


def test_presets_attachment_modes(client):
    presets = _get_presets(client)
    perm = [p for p in presets if p["attachment_mode"] == "permanent"]
    remov = [p for p in presets if p["attachment_mode"] == "removable"]
    # barber (5) + tattoo (4) = 9 permanent
    assert len(perm) == 9
    # mask (3) + jewellery (3) + weapon (4) = 10 removable
    assert len(remov) == 10


# ── Apply / list tests ────────────────────────────────────────────────

def test_apply_hair_replaces_previous(client):
    token = get_auth_token(client)
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    blond = _get_preset_by_slug(client, "barber-short-spiked-blond")
    dark = _get_preset_by_slug(client, "barber-slicked-back-dark")

    resp1 = _apply(client, hdrs, char_id, blond["id"])
    assert resp1.status_code == 200

    resp2 = _apply(client, hdrs, char_id, dark["id"])
    assert resp2.status_code == 200

    elements = _list_elements(client, hdrs, char_id)
    hair_elements = [e for e in elements if e["preset"]["shop_type"] == "barber"]
    assert len(hair_elements) == 1, "Only one hair active at a time"
    assert hair_elements[0]["preset"]["slug"] == "barber-slicked-back-dark"


def test_apply_tattoo_placement_uniqueness(client):
    token = get_auth_token(client)
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    serpent = _get_preset_by_slug(client, "tattoo-right-arm-serpent-sleeve")
    wolf = _get_preset_by_slug(client, "tattoo-right-arm-tribal-wolf")

    _apply(client, hdrs, char_id, serpent["id"])
    _apply(client, hdrs, char_id, wolf["id"])

    elements = _list_elements(client, hdrs, char_id)
    right_arm = [e for e in elements if e["placement"] == "right_arm" and e["preset"]["shop_type"] == "tattoo"]
    assert len(right_arm) == 1, "Only one tattoo per placement"
    assert right_arm[0]["preset"]["slug"] == "tattoo-right-arm-tribal-wolf"


def test_removable_max_3_enforced(client):
    token = get_auth_token(client)
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    mask = _get_preset_by_slug(client, "mask-matte-black-demon-wolf")
    chain = _get_preset_by_slug(client, "jewellery-silver-chain")
    ring = _get_preset_by_slug(client, "jewellery-black-signet-ring")
    katana = _get_preset_by_slug(client, "weapon-katana")

    assert _apply(client, hdrs, char_id, mask["id"]).status_code == 200
    assert _apply(client, hdrs, char_id, chain["id"]).status_code == 200
    assert _apply(client, hdrs, char_id, ring["id"]).status_code == 200
    # 4th removable should be rejected
    resp = _apply(client, hdrs, char_id, katana["id"])
    assert resp.status_code == 409
    assert "3" in resp.json()["detail"]


def test_non_owner_cannot_apply(client):
    token1 = get_auth_token(client, email="owner@test.com", username="owner1")
    hdrs1 = auth_headers(token1)
    char_id = _create_character(client, hdrs1)

    token2 = get_auth_token(client, email="other@test.com", username="other1")
    hdrs2 = auth_headers(token2)

    preset = _get_preset_by_slug(client, "barber-short-spiked-blond")
    resp = _apply(client, hdrs2, char_id, preset["id"])
    assert resp.status_code == 403


def test_non_owner_cannot_list(client):
    token1 = get_auth_token(client, email="owner2@test.com", username="owner2")
    hdrs1 = auth_headers(token1)
    char_id = _create_character(client, hdrs1)

    token2 = get_auth_token(client, email="other2@test.com", username="other2")
    hdrs2 = auth_headers(token2)

    resp = client.get(f"/characters/{char_id}/style-elements", headers=hdrs2)
    assert resp.status_code == 403


# ── Identity spec patch ────────────────────────────────────────────────

def test_hair_updates_identity_spec(client, db_session):
    token = get_auth_token(client)
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    # Give the character a minimal identity spec
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    char.identity_spec_json = json.dumps({
        "style": "realistic",
        "gender": "male",
        "age_band": "18-25",
        "identity": {"hair_color": "black", "hair_length": "short"},
    })
    db_session.commit()

    preset = _get_preset_by_slug(client, "barber-short-spiked-blond")
    resp = _apply(client, hdrs, char_id, preset["id"])
    assert resp.status_code == 200

    db_session.refresh(char)
    spec = json.loads(char.identity_spec_json)
    assert spec["identity"]["hair_color"] == "blond"
    assert spec["identity"]["hair_length"] == "short"
    assert spec["hair_style"] == "short_cut"


# ── Prompt injection / token tests ────────────────────────────────────

def _setup_char_with_preset(client, db_session, email, username, preset_slug, char_name="TestChar"):
    from app.models.character import Character
    token = get_auth_token(client, email=email, username=username)
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs, name=char_name)
    preset = _get_preset_by_slug(client, preset_slug)
    _apply(client, hdrs, char_id, preset["id"])
    char = db_session.query(Character).filter(Character.id == char_id).first()
    return char


def test_portrait_injects_necklace(client, db_session):
    from app.services.style_elements import apply_style_elements_to_image_prompt
    char = _setup_char_with_preset(client, db_session, "neck@test.com", "neckuser",
                                   "jewellery-silver-chain")
    # Neck exposed → should inject
    result_yes = apply_style_elements_to_image_prompt(char, "close-up upper body shot", db_session)
    assert "silver chain" in result_yes.lower() or "chain necklace" in result_yes.lower(), \
        "Silver chain must auto-inject when neck/collarbone is exposed (close-up / upper body)"
    # Jacket covers neck → must NOT inject
    result_no = apply_style_elements_to_image_prompt(char, "portrait in a black jacket", db_session)
    assert "silver chain" not in result_no.lower() and "chain necklace" not in result_no.lower(), \
        "Silver chain must not inject when neck is covered (portrait + jacket)"


def test_necklace_neck_enforcement(client, db_session):
    from app.services.style_elements import apply_style_elements_to_image_prompt
    char = _setup_char_with_preset(client, db_session, "neck2@test.com", "neckuser2",
                                   "jewellery-silver-chain")
    result = apply_style_elements_to_image_prompt(char, "close-up upper body", db_session)
    assert "neck" in result.lower() or "collar" in result.lower(), \
        "Neck placement enforcement must be in token"


def test_mask_only_injected_when_referenced(client, db_session):
    from app.services.style_elements import apply_style_elements_to_image_prompt
    char = _setup_char_with_preset(client, db_session, "mask@test.com", "maskuser",
                                   "mask-matte-black-demon-wolf")
    result_no = apply_style_elements_to_image_prompt(char, "portrait in a black jacket", db_session)
    assert "wolf mask" not in result_no.lower(), "Mask must not inject without reference"
    result_yes = apply_style_elements_to_image_prompt(char, "wearing his mask, dramatic pose", db_session)
    assert "wolf mask" in result_yes.lower() or "demon wolf" in result_yes.lower()


def test_weapon_only_injected_when_referenced(client, db_session):
    from app.services.style_elements import apply_style_elements_to_image_prompt
    char = _setup_char_with_preset(client, db_session, "wep@test.com", "wepuser",
                                   "weapon-katana")
    result_no = apply_style_elements_to_image_prompt(char, "portrait in a park", db_session)
    assert "katana" not in result_no.lower()
    result_yes = apply_style_elements_to_image_prompt(
        char, "character holding a weapon, ready for battle", db_session)
    assert "katana" in result_yes.lower()


def test_hair_always_injected(client, db_session):
    from app.services.style_elements import apply_style_elements_to_image_prompt
    char = _setup_char_with_preset(client, db_session, "hair@test.com", "hairuser",
                                   "barber-short-spiked-blond")
    result = apply_style_elements_to_image_prompt(char, "portrait in a black jacket", db_session)
    assert "spiked blond" in result.lower(), "Hair always injected regardless of prompt"


def test_hair_injected_with_no_other_elements(client, db_session):
    from app.services.style_elements import apply_style_elements_to_image_prompt
    char = _setup_char_with_preset(client, db_session, "hair2@test.com", "hairuser2",
                                   "barber-slicked-back-dark")
    result = apply_style_elements_to_image_prompt(char, "sleeveless outfit showing arms", db_session)
    assert "slicked back" in result.lower()


def test_scene_comes_before_style_tokens(client, db_session):
    """User scene must appear BEFORE style modifier tokens in the final string."""
    from app.services.style_elements import apply_style_elements_to_image_prompt
    char = _setup_char_with_preset(client, db_session, "order@test.com", "orderuser",
                                   "barber-short-spiked-blond")
    user_prompt = "portrait of Leonardo in a black jacket"
    result = apply_style_elements_to_image_prompt(char, user_prompt, db_session)
    user_pos = result.lower().find("portrait of leonardo")
    hair_pos = result.lower().find("spiked blond")
    assert user_pos < hair_pos, "User scene must appear before style tokens — style tokens must not dominate composition"


# ── Archive / delete ──────────────────────────────────────────────────

def test_archive_element(client):
    token = get_auth_token(client, email="arch@test.com", username="archuser")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    preset = _get_preset_by_slug(client, "jewellery-silver-chain")
    _apply(client, hdrs, char_id, preset["id"])

    elements = _list_elements(client, hdrs, char_id)
    assert len(elements) == 1
    element_id = elements[0]["id"]

    resp = _delete_element(client, hdrs, char_id, element_id)
    assert resp.status_code == 200

    elements_after = _list_elements(client, hdrs, char_id)
    assert len(elements_after) == 0


def test_idempotent_apply_same_preset(client):
    token = get_auth_token(client, email="idem@test.com", username="idemuser")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    preset = _get_preset_by_slug(client, "barber-short-spiked-blond")
    _apply(client, hdrs, char_id, preset["id"])
    _apply(client, hdrs, char_id, preset["id"])

    elements = _list_elements(client, hdrs, char_id)
    assert len(elements) == 1, "Idempotent — same preset applied twice = one element"
