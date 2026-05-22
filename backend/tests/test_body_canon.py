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
