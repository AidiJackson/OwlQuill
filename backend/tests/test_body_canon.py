"""Tests for body canon — persistent anatomical markings (tattoos, scars, burns, birthmarks)."""
import pytest
from tests.conftest import auth_headers, get_auth_token


# ── Helpers ────────────────────────────────────────────────────────────

def _create_character(client, headers, name="CanonChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


_TATTOO_PAYLOAD = {
    "type": "tattoo",
    "placement": "left_upper_arm",
    "style": "black ink wolf head",
    "size": "large",
    "description": "A large black ink wolf head tattoo covering the left upper arm",
}

_SCAR_PAYLOAD = {
    "type": "scar",
    "placement": "right_cheek",
    "style": "diagonal slash scar",
    "size": "medium",
    "description": "A medium diagonal slash scar across the right cheek",
}


# ── Service unit tests (no HTTP) ──────────────────────────────────────

def test_build_compact_token_tattoo():
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_compact_token
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_UPPER_ARM,
        style="black ink serpent",
        size=MarkingSize.LARGE,
        description="large black ink serpent tattoo on left upper arm",
    )
    token = build_compact_token(m)
    assert "large" in token
    assert "black ink serpent" in token
    assert "left upper arm" in token


def test_build_compact_token_scar():
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_compact_token
    m = BodyMarking(
        type=MarkingType.SCAR,
        placement=MarkingPlacement.RIGHT_CHEEK,
        style="diagonal slash scar",
        size=MarkingSize.MEDIUM,
        description="diagonal scar on right cheek",
    )
    token = build_compact_token(m)
    assert "medium" in token
    assert "diagonal slash scar" in token
    assert "right cheek" in token


def test_build_compact_token_full_sleeve():
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_compact_token
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="black serpent sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="full sleeve serpent covering full left arm",
    )
    token = build_compact_token(m)
    assert "full sleeve" in token
    assert "covering full left arm" in token


def test_build_body_canon_lock_string_empty():
    from app.services.body_canon import build_body_canon_lock_string
    assert build_body_canon_lock_string([]) == ""


def test_build_body_canon_lock_string_single():
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_body_canon_lock_string
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.RIGHT_FOREARM,
        style="gothic script inscription",
        size=MarkingSize.MEDIUM,
        description="gothic script on right forearm",
    )
    result = build_body_canon_lock_string([m])
    assert result.startswith("BODY MARKINGS:")
    assert "gothic script inscription" in result
    assert "right forearm" in result


def test_build_body_canon_lock_string_multiple():
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_body_canon_lock_string
    m1 = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_UPPER_ARM,
        style="wolf head",
        size=MarkingSize.LARGE,
        description="wolf head on left arm",
    )
    m2 = BodyMarking(
        type=MarkingType.SCAR,
        placement=MarkingPlacement.RIGHT_CHEEK,
        style="diagonal scar",
        size=MarkingSize.SMALL,
        description="scar on cheek",
    )
    result = build_body_canon_lock_string([m1, m2])
    assert result.startswith("BODY MARKINGS:")
    assert "; " in result  # separator between tokens
    assert "wolf head" in result
    assert "diagonal scar" in result


def test_load_markings_empty_character():
    from app.services.body_canon import load_markings
    from unittest.mock import MagicMock
    char = MagicMock()
    char.body_canon_json = None
    assert load_markings(char) == []


def test_load_markings_invalid_json():
    from app.services.body_canon import load_markings
    from unittest.mock import MagicMock
    char = MagicMock()
    char.id = 1
    char.body_canon_json = "not-valid-json"
    assert load_markings(char) == []


# ── API tests ──────────────────────────────────────────────────────────

def test_list_empty_body_markings(client):
    token = get_auth_token(client, email="bc1@test.com", username="bcuser1")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    resp = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
    assert resp.status_code == 200
    data = resp.json()
    assert data["character_id"] == char_id
    assert data["markings"] == []


def test_add_tattoo_marking(client):
    token = get_auth_token(client, email="bc2@test.com", username="bcuser2")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    resp = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data["markings"]) == 1
    m = data["markings"][0]
    assert m["type"] == "tattoo"
    assert m["placement"] == "left_upper_arm"
    assert m["style"] == "black ink wolf head"
    assert m["size"] == "large"
    assert "id" in m and m["id"].startswith("bm_")
    assert "compact_token" in m


def test_add_scar_marking(client):
    token = get_auth_token(client, email="bc3@test.com", username="bcuser3")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    resp = client.post(f"/characters/{char_id}/body-markings", json=_SCAR_PAYLOAD, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    m = data["markings"][0]
    assert m["type"] == "scar"
    assert m["placement"] == "right_cheek"


def test_compact_token_in_api_response(client):
    token = get_auth_token(client, email="bc4@test.com", username="bcuser4")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    resp = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    assert resp.status_code == 201
    m = resp.json()["markings"][0]
    ct = m["compact_token"]
    assert "large" in ct
    assert "black ink wolf head" in ct
    assert "left upper arm" in ct


def test_add_multiple_markings(client):
    token = get_auth_token(client, email="bc5@test.com", username="bcuser5")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    resp = client.post(f"/characters/{char_id}/body-markings", json=_SCAR_PAYLOAD, headers=hdrs)
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["markings"]) == 2
    types = {m["type"] for m in data["markings"]}
    assert types == {"tattoo", "scar"}


def test_list_shows_all_markings(client):
    token = get_auth_token(client, email="bc6@test.com", username="bcuser6")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    client.post(f"/characters/{char_id}/body-markings", json=_SCAR_PAYLOAD, headers=hdrs)

    resp = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
    assert resp.status_code == 200
    assert len(resp.json()["markings"]) == 2


def test_delete_marking(client):
    token = get_auth_token(client, email="bc7@test.com", username="bcuser7")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    add_resp = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    marking_id = add_resp.json()["markings"][0]["id"]

    del_resp = client.delete(f"/characters/{char_id}/body-markings/{marking_id}", headers=hdrs)
    assert del_resp.status_code == 200
    assert del_resp.json()["markings"] == []


def test_delete_nonexistent_marking_404(client):
    token = get_auth_token(client, email="bc8@test.com", username="bcuser8")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    resp = client.delete(f"/characters/{char_id}/body-markings/bm_doesnotexist", headers=hdrs)
    assert resp.status_code == 404


def test_delete_one_marking_leaves_others(client):
    token = get_auth_token(client, email="bc9@test.com", username="bcuser9")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    r1 = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    r2 = client.post(f"/characters/{char_id}/body-markings", json=_SCAR_PAYLOAD, headers=hdrs)
    tattoo_id = r1.json()["markings"][0]["id"]

    resp = client.delete(f"/characters/{char_id}/body-markings/{tattoo_id}", headers=hdrs)
    assert resp.status_code == 200
    remaining = resp.json()["markings"]
    assert len(remaining) == 1
    assert remaining[0]["type"] == "scar"


# ── Auth / ownership tests ─────────────────────────────────────────────

def test_non_owner_cannot_list_body_markings(client):
    token1 = get_auth_token(client, email="bcown1@test.com", username="bcouser1")
    hdrs1 = auth_headers(token1)
    char_id = _create_character(client, hdrs1)

    token2 = get_auth_token(client, email="bcoth1@test.com", username="bcother1")
    hdrs2 = auth_headers(token2)

    resp = client.get(f"/characters/{char_id}/body-markings", headers=hdrs2)
    assert resp.status_code == 403


def test_non_owner_cannot_add_body_marking(client):
    token1 = get_auth_token(client, email="bcown2@test.com", username="bcouser2")
    hdrs1 = auth_headers(token1)
    char_id = _create_character(client, hdrs1)

    token2 = get_auth_token(client, email="bcoth2@test.com", username="bcother2")
    hdrs2 = auth_headers(token2)

    resp = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs2)
    assert resp.status_code == 403


def test_non_owner_cannot_delete_body_marking(client):
    token1 = get_auth_token(client, email="bcown3@test.com", username="bcouser3")
    hdrs1 = auth_headers(token1)
    char_id = _create_character(client, hdrs1)
    add_resp = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs1)
    marking_id = add_resp.json()["markings"][0]["id"]

    token2 = get_auth_token(client, email="bcoth3@test.com", username="bcother3")
    hdrs2 = auth_headers(token2)
    resp = client.delete(f"/characters/{char_id}/body-markings/{marking_id}", headers=hdrs2)
    assert resp.status_code == 403


def test_character_not_found_returns_404(client):
    token = get_auth_token(client, email="bc404@test.com", username="bc404user")
    hdrs = auth_headers(token)
    resp = client.get("/characters/99999/body-markings", headers=hdrs)
    assert resp.status_code == 404


# ── Anchor schema defaults ─────────────────────────────────────────────

def test_body_marking_anchor_fields_default():
    """New BodyMarking has anchor_status=missing and null anchor fields."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.RIGHT_FULL_ARM,
        style="black serpent sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="full sleeve serpent",
    )
    assert m.anchor_status == "missing"
    assert m.anchor_image_url is None
    assert m.anchor_prompt is None


def test_body_marking_anchor_status_roundtrip():
    """Anchor fields survive model_dump / rehydration cycle."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="gothic script",
        size=MarkingSize.FULL_SLEEVE,
        description="gothic script sleeve",
        anchor_image_url="https://cdn.example.com/anchor.png",
        anchor_status="locked",
        anchor_prompt="close-up left arm reference",
    )
    d = m.model_dump()
    m2 = BodyMarking(**d)
    assert m2.anchor_status == "locked"
    assert m2.anchor_image_url == "https://cdn.example.com/anchor.png"
    assert m2.anchor_prompt == "close-up left arm reference"


def test_build_anchor_generation_prompt_right_arm():
    """Anchor prompt for right arm includes region and side note."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_anchor_generation_prompt
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.RIGHT_FULL_ARM,
        style="black serpent sleeve tattoo",
        size=MarkingSize.FULL_SLEEVE,
        description="full sleeve serpent",
    )
    prompt = build_anchor_generation_prompt(m, character_name="Leo")
    assert "Leo" in prompt
    assert "right" in prompt.lower()
    assert "not the left" in prompt.lower()
    assert "black serpent sleeve tattoo" in prompt
    assert "reference" in prompt.lower()


def test_build_anchor_generation_prompt_left_arm():
    """Anchor prompt for left arm references left side only."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_anchor_generation_prompt
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="gothic script sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="gothic script sleeve",
    )
    prompt = build_anchor_generation_prompt(m, character_name="Leo")
    assert "left" in prompt.lower()
    assert "not the right" in prompt.lower()
    assert "gothic script sleeve" in prompt


# ── update_marking service ─────────────────────────────────────────────

def test_update_marking_sets_anchor_fields():
    """update_marking patches anchor fields without touching other fields."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import _save_markings, update_marking, load_markings
    from unittest.mock import MagicMock

    char = MagicMock()
    char.id = 1
    char.body_canon_json = None

    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.RIGHT_FULL_ARM,
        style="serpent sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="serpent sleeve right arm",
    )
    _save_markings(char, [m])

    updated = update_marking(char, m.id, {
        "anchor_image_url": "https://cdn.example.com/anchor.png",
        "anchor_status": "generated",
    })
    assert updated is not None
    assert updated.anchor_status == "generated"
    assert updated.anchor_image_url == "https://cdn.example.com/anchor.png"
    assert updated.style == "serpent sleeve"  # unchanged


def test_update_marking_nonexistent_returns_none():
    from app.services.body_canon import update_marking
    from unittest.mock import MagicMock
    char = MagicMock()
    char.id = 1
    char.body_canon_json = None
    result = update_marking(char, "bm_doesnotexist", {"anchor_status": "locked"})
    assert result is None


# ── Anchor API endpoint tests ──────────────────────────────────────────

def test_generate_anchor_validates_owner(client):
    """generate-anchor returns 403 for non-owner."""
    token1 = get_auth_token(client, email="bca_own@test.com", username="bca_owner")
    hdrs1 = auth_headers(token1)
    char_id = _create_character(client, hdrs1)
    add_resp = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs1)
    marking_id = add_resp.json()["markings"][0]["id"]

    token2 = get_auth_token(client, email="bca_oth@test.com", username="bca_other")
    hdrs2 = auth_headers(token2)
    resp = client.post(f"/characters/{char_id}/body-markings/{marking_id}/generate-anchor", headers=hdrs2)
    assert resp.status_code == 403


def test_generate_anchor_404_on_missing_marking(client):
    """generate-anchor returns 404 for nonexistent marking_id."""
    token = get_auth_token(client, email="bca_404@test.com", username="bca_404user")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)
    resp = client.post(f"/characters/{char_id}/body-markings/bm_doesnotexist/generate-anchor", headers=hdrs)
    assert resp.status_code == 404


def test_lock_anchor_requires_generated_first(client):
    """lock-anchor returns 409 when no anchor image exists yet."""
    token = get_auth_token(client, email="bca_lock@test.com", username="bca_lockuser")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)
    add_resp = client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    marking_id = add_resp.json()["markings"][0]["id"]

    resp = client.post(f"/characters/{char_id}/body-markings/{marking_id}/lock-anchor", headers=hdrs)
    assert resp.status_code == 409


# ── upsert_marking_from_preset ─────────────────────────────────────────

def test_upsert_marking_from_preset_creates_marking():
    """upsert_marking_from_preset creates a new body marking with slug tag."""
    from app.services.body_canon import upsert_marking_from_preset, load_markings, _save_markings
    from unittest.mock import MagicMock

    char = MagicMock()
    char.id = 1
    char.body_canon_json = None

    result = upsert_marking_from_preset(
        char,
        preset_slug="black-serpent-sleeve",
        placement="right_full_arm",
        prompt_token="black serpent sleeve tattoo on right arm, detailed scales",
    )
    assert result is not None
    assert result.placement == "right_full_arm"
    assert "#slug:black-serpent-sleeve" in result.description
    assert result.anchor_status == "missing"


def test_upsert_marking_from_preset_idempotent():
    """Calling upsert_marking_from_preset twice for same slug updates, not duplicates."""
    from app.services.body_canon import upsert_marking_from_preset, load_markings
    from unittest.mock import MagicMock

    char = MagicMock()
    char.id = 1
    char.body_canon_json = None

    upsert_marking_from_preset(char, "gothic-script-sleeve", "left_full_arm", "gothic script sleeve")
    upsert_marking_from_preset(char, "gothic-script-sleeve", "left_full_arm", "gothic script v2")
    markings = load_markings(char)
    assert len(markings) == 1  # still only one
    assert "gothic script v2" in markings[0].description


# ── Visibility detection ───────────────────────────────────────────────

def test_detect_visible_regions_shirtless():
    """'shirtless' triggers both arms."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("leonardo shirtless in a pool")
    assert "right_arm" in regions
    assert "left_arm" in regions


def test_detect_visible_regions_right_arm_only():
    """Explicit right arm mention triggers only right."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("reaching out his right arm")
    assert "right_arm" in regions
    assert "left_arm" not in regions


def test_detect_visible_regions_left_arm_only():
    """Explicit left arm mention triggers only left."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("holding a drink in his left hand")
    assert "left_arm" in regions
    assert "right_arm" not in regions


def test_detect_visible_regions_no_signal():
    """No body signals → empty set."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("a portrait in a dark alley")
    assert "right_arm" not in regions
    assert "left_arm" not in regions


def test_detect_visible_regions_tattoos_keyword():
    """'tattoos visible' triggers both arms."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("showing off his tattoos visible in the light")
    assert "right_arm" in regions
    assert "left_arm" in regions


def test_detect_visible_regions_sleeveless():
    """'sleeveless' explicitly exposes both arms."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("leonardo in a sleeveless shirt on a rooftop")
    assert "right_arm" in regions
    assert "left_arm" in regions


# ── Visibility discipline — clothing / costume protection ─────────────


def test_detect_visible_regions_superman_costume():
    """Superman costume has no explicit bare-arm signal; no visible arm regions returned."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("leonardo wearing a superman costume on a rooftop")
    assert "right_arm" not in regions
    assert "left_arm" not in regions


def test_detect_visible_regions_jacket():
    """Jacket prompt has no explicit bare-arm signal."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("leonardo in a black leather jacket on a rooftop")
    assert "right_arm" not in regions
    assert "left_arm" not in regions


def test_detect_visible_regions_suit():
    """Suit prompt has no explicit bare-arm signal."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("leonardo wearing a formal suit at a gala")
    assert "right_arm" not in regions
    assert "left_arm" not in regions


def test_tattoo_visibility_requested_false_costume():
    """Superman costume → tattoo_visibility_requested would be False (no visible regions)."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("superman costume on a rooftop")
    assert not bool(regions)


def test_tattoo_visibility_requested_true_shirtless():
    """Shirtless prompt → tattoo_visibility_requested would be True."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("shirtless on a rooftop")
    assert bool(regions)


def test_tattoo_visibility_requested_true_tattoos_showing():
    """'tattoos showing' prompt → tattoo_visibility_requested would be True."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("his tattoos showing in the sunlight")
    assert bool(regions)


def test_clothing_detected_superman_costume():
    """'costume' is in _CLOTHING_COVER_SIGNALS."""
    from app.api.routes.image_generator import _CLOTHING_COVER_SIGNALS
    assert any(sig in "superman costume on a rooftop" for sig in _CLOTHING_COVER_SIGNALS)


def test_clothing_detected_jacket():
    """'jacket' is in _CLOTHING_COVER_SIGNALS."""
    from app.api.routes.image_generator import _CLOTHING_COVER_SIGNALS
    assert any(sig in "black leather jacket" for sig in _CLOTHING_COVER_SIGNALS)


def test_clothing_detected_suit():
    """'suit' is in _CLOTHING_COVER_SIGNALS."""
    from app.api.routes.image_generator import _CLOTHING_COVER_SIGNALS
    assert any(sig in "wearing a formal suit" for sig in _CLOTHING_COVER_SIGNALS)


def test_clothing_not_detected_shirtless():
    """'shirtless on a rooftop' contains no clothing cover signal."""
    from app.api.routes.image_generator import _CLOTHING_COVER_SIGNALS
    assert not any(sig in "shirtless on a rooftop" for sig in _CLOTHING_COVER_SIGNALS)


def test_tattoo_layout_skipped_without_visibility_signal():
    """Without explicit visibility, visible regions are empty → tattoo_layout not used."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("superman costume on a rooftop")
    tattoo_visibility_requested = bool(regions)
    assert not tattoo_visibility_requested


def test_tattoo_layout_used_with_shirtless():
    """'shirtless' produces visible regions → tattoo_layout would be eligible."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("shirtless on a rooftop")
    tattoo_visibility_requested = bool(regions)
    assert tattoo_visibility_requested


def test_always_visible_placements_includes_neck_and_face():
    """Face/neck/hand placements are in _ALWAYS_VISIBLE_PLACEMENTS."""
    from app.api.routes.image_generator import _ALWAYS_VISIBLE_PLACEMENTS
    for placement in ("neck", "throat", "right_cheek", "left_cheek", "forehead", "chin", "jaw"):
        assert placement in _ALWAYS_VISIBLE_PLACEMENTS, f"{placement} should be always visible"


def test_always_visible_placements_includes_hands():
    """Hand placements are always visible."""
    from app.api.routes.image_generator import _ALWAYS_VISIBLE_PLACEMENTS
    assert "left_hand" in _ALWAYS_VISIBLE_PLACEMENTS
    assert "right_hand" in _ALWAYS_VISIBLE_PLACEMENTS
    assert "knuckles" in _ALWAYS_VISIBLE_PLACEMENTS


def test_arm_placements_not_in_always_visible():
    """Arm and torso placements are NOT always visible (require explicit request)."""
    from app.api.routes.image_generator import _ALWAYS_VISIBLE_PLACEMENTS
    for placement in ("left_upper_arm", "right_full_arm", "left_forearm", "chest", "upper_back"):
        assert placement not in _ALWAYS_VISIBLE_PLACEMENTS, f"{placement} should NOT be always visible"


def test_body_canon_str_filtered_for_costume():
    """Arm tattoo tokens are excluded from body_canon_str when no visibility signal."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.api.routes.image_generator import (
        _detect_visible_body_regions,
        _ALWAYS_VISIBLE_PLACEMENTS,
        _BODY_REGION_PLACEMENTS,
    )
    from app.services.body_canon import build_body_canon_lock_string

    arm_marking = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="black serpent sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="serpent sleeve left arm",
    )
    neck_marking = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.NECK,
        style="geometric neck tattoo",
        size=MarkingSize.MEDIUM,
        description="neck tattoo",
    )
    markings = [arm_marking, neck_marking]
    prompt = "superman costume on a rooftop"
    visible_regions = _detect_visible_body_regions(prompt)

    visible_markings = [
        m for m in markings
        if m.placement in _ALWAYS_VISIBLE_PLACEMENTS
        or any(
            m.placement in placements and region in visible_regions
            for region, placements in _BODY_REGION_PLACEMENTS.items()
        )
    ]
    result = build_body_canon_lock_string(visible_markings)

    # Neck tattoo included (always visible), arm tattoo excluded (no visibility signal)
    assert "geometric neck tattoo" in result
    assert "black serpent sleeve" not in result


def test_body_canon_str_includes_arm_when_shirtless():
    """Arm tattoo tokens ARE included in body_canon_str when shirtless is in prompt."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.api.routes.image_generator import (
        _detect_visible_body_regions,
        _ALWAYS_VISIBLE_PLACEMENTS,
        _BODY_REGION_PLACEMENTS,
    )
    from app.services.body_canon import build_body_canon_lock_string

    arm_marking = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="black serpent sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="serpent sleeve left arm",
    )
    markings = [arm_marking]
    prompt = "leonardo shirtless on a rooftop"
    visible_regions = _detect_visible_body_regions(prompt)

    visible_markings = [
        m for m in markings
        if m.placement in _ALWAYS_VISIBLE_PLACEMENTS
        or any(
            m.placement in placements and region in visible_regions
            for region, placements in _BODY_REGION_PLACEMENTS.items()
        )
    ]
    result = build_body_canon_lock_string(visible_markings)
    assert "black serpent sleeve" in result


# ── Lock string integration ────────────────────────────────────────────

def test_lock_string_included_in_body_canon(client, db_session):
    """Markings saved via API appear in the compiled lock string."""
    from app.models.character import Character
    from app.services.body_canon import load_markings, build_body_canon_lock_string

    token = get_auth_token(client, email="bcls@test.com", username="bclsuser")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    client.post(f"/characters/{char_id}/body-markings", json=_TATTOO_PAYLOAD, headers=hdrs)
    client.post(f"/characters/{char_id}/body-markings", json=_SCAR_PAYLOAD, headers=hdrs)

    char = db_session.query(Character).filter(Character.id == char_id).first()
    markings = load_markings(char)
    lock_str = build_body_canon_lock_string(markings)

    assert lock_str.startswith("BODY MARKINGS:")
    assert "wolf head" in lock_str
    assert "diagonal slash scar" in lock_str


# ── sync_tattoo_style_elements_to_body_canon ──────────────────────────────────

@pytest.fixture(autouse=False)
def seed_presets_for_sync(db_session):
    from app.core.style_shop_seed import seed_style_presets
    seed_style_presets(db_session)


def test_get_body_markings_does_not_backfill_tattoo_elements(client, db_session, seed_presets_for_sync):
    """GET /body-markings no longer backfills style shop tattoos into body_canon_json.
    Auto-sync is disabled. Body canon is managed via /identity-canon routes only.
    """
    from app.models.character import Character
    from app.services.body_canon import load_markings

    token = get_auth_token(client, email="sync1@test.com", username="syncuser1")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    presets_resp = client.get("/style-shops/presets?shop_type=tattoo")
    assert presets_resp.status_code == 200
    tattoo_presets = presets_resp.json()
    assert len(tattoo_presets) > 0, "Need at least one tattoo preset seeded"
    preset = tattoo_presets[0]

    apply_resp = client.post(
        f"/characters/{char_id}/style-elements",
        json={"preset_id": preset["id"]},
        headers=hdrs,
    )
    assert apply_resp.status_code == 200

    # GET /body-markings must NOT auto-populate from style shop
    resp = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
    assert resp.status_code == 200
    markings = resp.json()["markings"]
    assert len(markings) == 0, (
        f"GET /body-markings must NOT auto-sync shop tattoos. Got: {[m['description'] for m in markings]}"
    )


def test_get_body_markings_backfill_is_idempotent(client, db_session, seed_presets_for_sync):
    """Calling GET /body-markings multiple times does not duplicate markings."""
    token = get_auth_token(client, email="sync2@test.com", username="syncuser2")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    presets_resp = client.get("/style-shops/presets?shop_type=tattoo")
    preset = presets_resp.json()[0]
    client.post(f"/characters/{char_id}/style-elements", json={"preset_id": preset["id"]}, headers=hdrs)

    # Call GET three times
    r1 = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
    r2 = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
    r3 = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)

    count1 = len(r1.json()["markings"])
    count2 = len(r2.json()["markings"])
    count3 = len(r3.json()["markings"])
    assert count1 == count2 == count3, f"Idempotent: expected equal counts, got {count1}/{count2}/{count3}"


def test_applying_tattoo_preset_does_not_create_body_canon(client, db_session, seed_presets_for_sync):
    """POST /style-elements with a tattoo preset does NOT auto-sync to body_canon_json.
    Body canon is managed exclusively via /identity-canon routes.
    """
    from app.models.character import Character
    from app.services.body_canon import load_markings

    token = get_auth_token(client, email="sync3@test.com", username="syncuser3")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    presets_resp = client.get("/style-shops/presets?shop_type=tattoo")
    preset = presets_resp.json()[0]

    client.post(f"/characters/{char_id}/style-elements", json={"preset_id": preset["id"]}, headers=hdrs)

    db_session.expire_all()
    char = db_session.query(Character).filter(Character.id == char_id).first()
    markings = load_markings(char)
    assert len(markings) == 0, (
        f"Style shop apply must NOT create body_canon_json entries. Got: {[m.description for m in markings]}"
    )


def test_applying_two_tattoo_presets_does_not_auto_sync_to_body_canon(client, db_session, seed_presets_for_sync):
    """Applying tattoo presets no longer auto-syncs to body_canon_json.
    Body canon is now managed exclusively through /identity-canon routes.
    Style shop tattoos remain as styling records only.
    """
    from app.models.character import Character
    from app.services.body_canon import load_markings

    token = get_auth_token(client, email="sync4@test.com", username="syncuser4")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    presets_resp = client.get("/style-shops/presets?shop_type=tattoo")
    tattoo_presets = presets_resp.json()
    right_presets = [p for p in tattoo_presets if "right" in p["slug"]]
    left_presets = [p for p in tattoo_presets if "left" in p["slug"]]
    if not right_presets or not left_presets:
        pytest.skip("Need at least one right-arm and one left-arm tattoo preset")

    client.post(f"/characters/{char_id}/style-elements",
                json={"preset_id": right_presets[0]["id"]}, headers=hdrs)
    client.post(f"/characters/{char_id}/style-elements",
                json={"preset_id": left_presets[0]["id"]}, headers=hdrs)

    db_session.expire_all()
    char = db_session.query(Character).filter(Character.id == char_id).first()
    # Auto-sync is disabled — body_canon_json stays clean
    markings = load_markings(char)
    assert len(markings) == 0, (
        f"Style shop tattoos must NOT auto-sync to body_canon_json. "
        f"Got {len(markings)} markings: {[m.description for m in markings]}"
    )


def test_anchor_fields_preserved_on_sync_update():
    """update_marking preserves anchor fields when syncing updates placement/style."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import _save_markings, upsert_marking_from_preset, load_markings
    from unittest.mock import MagicMock

    char = MagicMock()
    char.id = 1
    char.body_canon_json = None

    # Initial create
    upsert_marking_from_preset(char, "test-slug", "right_full_arm", "serpent sleeve, black ink")

    # Manually set anchor fields
    markings = load_markings(char)
    markings[0] = BodyMarking(**{
        **markings[0].model_dump(),
        "anchor_image_url": "https://cdn.example.com/anchor.png",
        "anchor_status": "locked",
        "anchor_prompt": "close-up right arm reference",
    })
    _save_markings(char, markings)

    # Sync update (same slug, different prompt_token)
    upsert_marking_from_preset(char, "test-slug", "right_full_arm", "serpent sleeve v2, black ink")

    updated_markings = load_markings(char)
    assert len(updated_markings) == 1
    m = updated_markings[0]
    # Anchor fields must be preserved
    assert m.anchor_image_url == "https://cdn.example.com/anchor.png"
    assert m.anchor_status == "locked"
    assert m.anchor_prompt == "close-up right arm reference"
    # Style updated
    assert "serpent sleeve v2" in m.style


def test_get_body_markings_does_not_trigger_shop_sync(client, db_session, seed_presets_for_sync):
    """GET /body-markings no longer auto-syncs style shop tattoos.
    Auto-sync is removed: body canon is managed via /identity-canon routes only.
    """
    from app.models.character import Character
    from app.services.body_canon import load_markings

    token = get_auth_token(client, email="syncunit@test.com", username="syncunituser")
    hdrs = auth_headers(token)
    char_id = _create_character(client, hdrs)

    # Apply a tattoo preset
    presets = client.get("/style-shops/presets?shop_type=tattoo").json()
    assert len(presets) > 0
    preset = presets[0]
    client.post(f"/characters/{char_id}/style-elements",
                json={"preset_id": preset["id"]}, headers=hdrs)

    # GET /body-markings should NOT auto-populate from shop
    resp = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
    assert resp.status_code == 200

    db_session.expire_all()
    char = db_session.query(Character).filter(Character.id == char_id).first()
    markings = load_markings(char)
    assert len(markings) == 0, (
        f"GET /body-markings must NOT auto-sync shop tattoos. Got: {[m.description for m in markings]}"
    )


# ── Sleeve enforcement ────────────────────────────────────────────────


def test_is_sleeve_marking_full_sleeve_size():
    """MarkingSize.FULL_SLEEVE is identified as a sleeve marking."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import is_sleeve_marking
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="gothic script sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="full gothic script sleeve",
    )
    assert is_sleeve_marking(m)


def test_is_sleeve_marking_from_style_text():
    """'sleeve' in style text triggers is_sleeve_marking even with size=large."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import is_sleeve_marking
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.RIGHT_FULL_ARM,
        style="tribal wolf sleeve tattoo",
        size=MarkingSize.LARGE,
        description="tribal wolf sleeve on right arm",
    )
    assert is_sleeve_marking(m)


def test_is_sleeve_marking_false_for_small():
    """Non-sleeve marking (small scar) is not a sleeve."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import is_sleeve_marking
    m = BodyMarking(
        type=MarkingType.SCAR,
        placement=MarkingPlacement.RIGHT_CHEEK,
        style="diagonal slash scar",
        size=MarkingSize.SMALL,
        description="scar on right cheek",
    )
    assert not is_sleeve_marking(m)


def test_is_sleeve_marking_false_for_large_non_sleeve():
    """Large tattoo with no 'sleeve' in style is not a sleeve."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import is_sleeve_marking
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.RIGHT_UPPER_ARM,
        style="tribal wolf mark",
        size=MarkingSize.LARGE,
        description="tribal wolf upper arm",
    )
    assert not is_sleeve_marking(m)


def test_is_sleeve_marking_from_coverage_field():
    """coverage=full_sleeve triggers is_sleeve_marking regardless of size."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize, MarkingCoverage
    from app.services.body_canon import is_sleeve_marking
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="geometric patterns",
        size=MarkingSize.LARGE,
        description="geometric pattern left arm",
        coverage=MarkingCoverage.FULL_SLEEVE,
    )
    assert is_sleeve_marking(m)


def test_get_arm_side_left():
    from app.services.body_canon import get_arm_side
    assert get_arm_side("left_full_arm") == "left"
    assert get_arm_side("left_upper_arm") == "left"
    assert get_arm_side("left_forearm") == "left"
    assert get_arm_side("left_arm") == "left"


def test_get_arm_side_right():
    from app.services.body_canon import get_arm_side
    assert get_arm_side("right_full_arm") == "right"
    assert get_arm_side("right_upper_arm") == "right"
    assert get_arm_side("right_forearm") == "right"
    assert get_arm_side("right_arm") == "right"


def test_get_arm_side_non_arm():
    from app.services.body_canon import get_arm_side
    assert get_arm_side("neck") is None
    assert get_arm_side("chest") is None
    assert get_arm_side("right_cheek") is None


def test_build_sleeve_enforcement_str_left_arm_visible():
    """Left sleeve with left arm visible produces enforcement text."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_sleeve_enforcement_str
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="black gothic script sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="full gothic script sleeve left arm",
    )
    result = build_sleeve_enforcement_str([m], {"left_arm", "right_arm"})
    assert "SLEEVE IDENTITY" in result
    assert "left arm" in result
    assert "black gothic script sleeve" in result
    assert "shoulder to wrist" in result
    assert "must be present" in result


def test_build_sleeve_enforcement_str_right_arm_visible():
    """Right sleeve with right arm visible produces enforcement text."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_sleeve_enforcement_str
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.RIGHT_FULL_ARM,
        style="tribal wolf mark sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="tribal wolf sleeve right arm",
    )
    result = build_sleeve_enforcement_str([m], {"right_arm"})
    assert "SLEEVE IDENTITY" in result
    assert "right arm" in result
    assert "tribal wolf mark sleeve" in result


def test_build_sleeve_enforcement_str_empty_when_arm_not_visible():
    """Sleeve marking on non-visible arm returns empty string."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_sleeve_enforcement_str
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="black gothic script sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="full sleeve left arm",
    )
    result = build_sleeve_enforcement_str([m], set())
    assert result == ""


def test_build_sleeve_enforcement_str_both_arms():
    """Both sleeves visible produces two enforcement clauses."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_sleeve_enforcement_str
    left = BodyMarking(
        type=MarkingType.TATTOO, placement=MarkingPlacement.LEFT_FULL_ARM,
        style="gothic script sleeve", size=MarkingSize.FULL_SLEEVE, description="left sleeve",
    )
    right = BodyMarking(
        type=MarkingType.TATTOO, placement=MarkingPlacement.RIGHT_FULL_ARM,
        style="tribal wolf sleeve", size=MarkingSize.FULL_SLEEVE, description="right sleeve",
    )
    result = build_sleeve_enforcement_str([left, right], {"left_arm", "right_arm"})
    assert "left arm" in result
    assert "right arm" in result
    assert "gothic script sleeve" in result
    assert "tribal wolf sleeve" in result


def test_ice_bath_triggers_both_arms_visible():
    """'ice bath' prompt triggers both-arms visibility detection."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("leonardo sitting in an ice bath")
    assert "left_arm" in regions
    assert "right_arm" in regions


def test_sleeveless_vest_triggers_both_arms():
    """'wet grey sleeveless vest' triggers both-arms visibility."""
    from app.api.routes.image_generator import _detect_visible_body_regions
    regions = _detect_visible_body_regions("wet grey sleeveless vest both arms visible")
    assert "left_arm" in regions
    assert "right_arm" in regions


def test_sleeve_enforcement_injected_in_strict_prompt():
    """Sleeve enforcement string appears in strict identity prompt when provided."""
    from app.api.routes.image_generator import _build_strict_identity_prompt
    enforcement = "SLEEVE IDENTITY: left arm: gothic script from shoulder to wrist — must be present"
    result = _build_strict_identity_prompt(
        base_prompt="sitting in an ice bath",
        anchor_data={"identity_lock_string": "male, dark hair"},
        sleeve_enforcement_str=enforcement,
    )
    assert "SLEEVE IDENTITY" in result
    assert "gothic script" in result


def test_sleeve_enforcement_absent_for_costume():
    """Costume prompt → no visible regions → sleeve enforcement str is empty."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    from app.services.body_canon import build_sleeve_enforcement_str
    from app.api.routes.image_generator import _detect_visible_body_regions
    m = BodyMarking(
        type=MarkingType.TATTOO, placement=MarkingPlacement.LEFT_FULL_ARM,
        style="gothic script sleeve", size=MarkingSize.FULL_SLEEVE, description="left sleeve",
    )
    regions = _detect_visible_body_regions("superman costume on a rooftop")
    result = build_sleeve_enforcement_str([m], regions)
    assert result == ""


def test_coverage_field_stored_and_retrieved():
    """BodyMarking with explicit coverage round-trips through model_dump."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize, MarkingCoverage
    m = BodyMarking(
        type=MarkingType.TATTOO,
        placement=MarkingPlacement.LEFT_FULL_ARM,
        style="gothic script sleeve",
        size=MarkingSize.FULL_SLEEVE,
        description="full sleeve",
        coverage=MarkingCoverage.FULL_SLEEVE,
    )
    d = m.model_dump()
    m2 = BodyMarking(**d)
    assert m2.coverage == MarkingCoverage.FULL_SLEEVE


def test_coverage_field_optional_defaults_none():
    """BodyMarking without coverage field defaults to None."""
    from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
    m = BodyMarking(
        type=MarkingType.TATTOO, placement=MarkingPlacement.RIGHT_UPPER_ARM,
        style="tribal wolf", size=MarkingSize.LARGE, description="wolf upper arm",
    )
    assert m.coverage is None


# ── Scene-identity balance ────────────────────────────────────────────


def test_detect_scene_complexity_low_portrait():
    """Plain portrait has low complexity — no full_body gate."""
    from app.api.routes.image_generator import _detect_scene_complexity
    complexity, gate = _detect_scene_complexity("a portrait of a man")
    assert complexity == "low"
    assert not gate


def test_detect_scene_complexity_ice_bath_gates_full_body():
    """Ice bath prompt gates full_body anchor."""
    from app.api.routes.image_generator import _detect_scene_complexity
    _, gate = _detect_scene_complexity("sitting in an ice bath")
    assert gate


def test_detect_scene_complexity_rooftop():
    """Rooftop environment gates full_body anchor."""
    from app.api.routes.image_generator import _detect_scene_complexity
    _, gate = _detect_scene_complexity("leonardo standing on a rooftop at night")
    assert gate


def test_detect_scene_complexity_fight():
    """Fight action gates full_body anchor."""
    from app.api.routes.image_generator import _detect_scene_complexity
    _, gate = _detect_scene_complexity("two characters fighting in the rain")
    assert gate


def test_detect_scene_complexity_high_for_rich_scene():
    """Rich scene (pose + environment + clothing) resolves to high."""
    from app.api.routes.image_generator import _detect_scene_complexity
    complexity, gate = _detect_scene_complexity(
        "sitting in an ice bath, leaning forward, exhausted, wet vest, arms visible"
    )
    assert complexity == "high"
    assert gate


def test_detect_scene_complexity_medium_for_single_action():
    """Single action keyword resolves to at least medium."""
    from app.api.routes.image_generator import _detect_scene_complexity
    complexity, _ = _detect_scene_complexity("walking down a street")
    assert complexity in ("medium", "high")


def test_scene_prompt_comes_before_identity_directive():
    """Scene prompt appears before the identity directive in the output."""
    from app.api.routes.image_generator import _build_strict_identity_prompt
    result = _build_strict_identity_prompt(
        base_prompt="sitting in an ice bath, wet vest, leaning forward",
        anchor_data={"identity_lock_string": "dark hair, brown eyes, muscular build"},
        scene_complex=True,
    )
    scene_pos = result.find("sitting in an ice bath")
    # Identity directive contains "same person" or "Reproduce the exact person"
    identity_pos = result.find("same person")
    assert scene_pos != -1, "Scene prompt should be in result"
    assert identity_pos != -1, "Identity directive should be in result"
    assert scene_pos < identity_pos, (
        f"Scene (pos={scene_pos}) must precede identity directive (pos={identity_pos})"
    )


def test_scene_preservation_note_injected_for_complex_scene():
    """Anti-studio note is injected when scene_complex=True."""
    from app.api.routes.image_generator import _build_strict_identity_prompt
    result = _build_strict_identity_prompt(
        base_prompt="sitting in an ice bath",
        anchor_data={},
        scene_complex=True,
    )
    assert "Do not revert to studio portrait" in result
    assert "Preserve the exact scene" in result


def test_scene_preservation_not_injected_for_low_complexity():
    """Anti-studio note is NOT injected when scene_complex=False."""
    from app.api.routes.image_generator import _build_strict_identity_prompt
    result = _build_strict_identity_prompt(
        base_prompt="a portrait of a man",
        anchor_data={},
        scene_complex=False,
    )
    assert "Do not revert to studio portrait" not in result


def test_scene_before_body_canon_and_sleeve():
    """Scene, then body canon, then sleeve enforcement — scene is always first."""
    from app.api.routes.image_generator import _build_strict_identity_prompt
    result = _build_strict_identity_prompt(
        base_prompt="shirtless in an ice bath",
        anchor_data={"identity_lock_string": "dark hair"},
        body_canon_str="BODY MARKINGS: full sleeve left arm",
        sleeve_enforcement_str="SLEEVE IDENTITY: left arm: gothic script",
        scene_complex=True,
    )
    scene_pos = result.find("shirtless in an ice bath")
    canon_pos = result.find("BODY MARKINGS")
    sleeve_pos = result.find("SLEEVE IDENTITY")
    assert scene_pos < canon_pos, "Scene must precede body canon"
    assert scene_pos < sleeve_pos, "Scene must precede sleeve enforcement"


def test_full_body_gate_signals_include_expected_words():
    """Key action/environment words are in _FULL_BODY_GATE_SIGNALS."""
    from app.api.routes.image_generator import _FULL_BODY_GATE_SIGNALS
    for word in ("sitting", "ice bath", "rooftop", "rain", "fighting", "sleeping"):
        assert word in _FULL_BODY_GATE_SIGNALS, f"'{word}' should gate full_body anchor"


def test_scene_complexity_signals_include_expected_words():
    """Key complexity words are in _SCENE_COMPLEXITY_SIGNALS."""
    from app.api.routes.image_generator import _SCENE_COMPLEXITY_SIGNALS
    for word in ("sitting", "leaning", "exhausted", "rain", "vest", "ice bath"):
        assert word in _SCENE_COMPLEXITY_SIGNALS, f"'{word}' should count as scene complexity"
