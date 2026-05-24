"""Tests for use-existing body identity and body canon anchor endpoints."""
import pytest
from unittest.mock import MagicMock, patch
from tests.conftest import auth_headers, get_auth_token

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


def _create_character(client, headers, name="UEChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_image(client, headers, char_id) -> int:
    """Generate a body slot image and return its CharacterImage id (via body_slots -> use slot generation)."""
    with patch("app.api.routes.body_identity.get_provider_for_option", return_value=_mock_provider()):
        resp = client.post(f"/characters/{char_id}/identity/body-slots/body_front/generate", headers=headers)
    assert resp.status_code == 200, resp.text
    # The CharacterImage row was created. To get its id, query via a direct DB lookup —
    # but since the test only needs the id to call use-existing, use the gallery instead.
    # We can get the image via the gallery endpoint.
    gallery = client.get(f"/characters/{char_id}/images", headers=headers)
    assert gallery.status_code == 200, gallery.text
    images = gallery.json()
    assert len(images) > 0, "No images in gallery after generation"
    return images[0]["id"]


def _add_tattoo(client, headers, char_id) -> str:
    payload = {
        "type": "tattoo", "placement": "left_upper_arm",
        "style": "black ink wolf", "size": "large",
        "description": "Wolf tattoo on left upper arm",
    }
    resp = client.post(f"/characters/{char_id}/body-markings", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["markings"][0]["id"]


# ── use-existing body slot ──────────────────────────────────────────────

def test_use_existing_body_slot_sets_locked_status(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    image_id = _create_image(client, headers, char_id)

    resp = client.post(
        f"/characters/{char_id}/identity/body-slots/body_front/use-existing",
        json={"image_id": image_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    front = next(s for s in resp.json()["slots"] if s["key"] == "body_front")
    assert front["status"] == "locked"
    assert front["url"] is not None


def test_use_existing_body_slot_archives_nothing_but_updates_json(client):
    """use-existing updates identity_anchor_json and returns all four slots."""
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    image_id = _create_image(client, headers, char_id)

    resp = client.post(
        f"/characters/{char_id}/identity/body-slots/tattoo_layout/use-existing",
        json={"image_id": image_id},
        headers=headers,
    )
    assert resp.status_code == 200
    keys = {s["key"] for s in resp.json()["slots"]}
    assert keys == {"body_front", "body_three_quarter", "body_back", "tattoo_layout"}
    tl = next(s for s in resp.json()["slots"] if s["key"] == "tattoo_layout")
    assert tl["status"] == "locked"


def test_use_existing_body_slot_all_four_slot_keys(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    image_id = _create_image(client, headers, char_id)

    for slot_key in ("body_front", "body_three_quarter", "body_back", "tattoo_layout"):
        resp = client.post(
            f"/characters/{char_id}/identity/body-slots/{slot_key}/use-existing",
            json={"image_id": image_id},
            headers=headers,
        )
        assert resp.status_code == 200, f"slot={slot_key}: {resp.text}"
        entry = next(s for s in resp.json()["slots"] if s["key"] == slot_key)
        assert entry["status"] == "locked"


def test_use_existing_body_slot_invalid_slot_returns_422(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    image_id = _create_image(client, headers, char_id)

    resp = client.post(
        f"/characters/{char_id}/identity/body-slots/bad_slot/use-existing",
        json={"image_id": image_id},
        headers=headers,
    )
    assert resp.status_code == 422


def test_use_existing_body_slot_wrong_character_image_returns_404(client):
    """Image must belong to this character."""
    token1 = get_auth_token(client, email="ue_own@test.com", username="ue_owner")
    token2 = get_auth_token(client, email="ue_oth@test.com", username="ue_other")
    char1 = _create_character(client, auth_headers(token1), "Char1")
    char2 = _create_character(client, auth_headers(token2), "Char2")
    image_id = _create_image(client, auth_headers(token1), char1)

    # Try to assign char1's image to char2's slot — should 404
    resp = client.post(
        f"/characters/{char2}/identity/body-slots/body_front/use-existing",
        json={"image_id": image_id},
        headers=auth_headers(token2),
    )
    assert resp.status_code == 404


def test_use_existing_body_slot_non_owner_returns_403(client):
    token1 = get_auth_token(client, email="ue_own2@test.com", username="ue_owner2")
    token2 = get_auth_token(client, email="ue_oth2@test.com", username="ue_other2")
    char_id = _create_character(client, auth_headers(token1))
    image_id = _create_image(client, auth_headers(token1), char_id)

    resp = client.post(
        f"/characters/{char_id}/identity/body-slots/body_front/use-existing",
        json={"image_id": image_id},
        headers=auth_headers(token2),
    )
    assert resp.status_code == 403


def test_use_existing_body_slot_nonexistent_image_returns_404(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)

    resp = client.post(
        f"/characters/{char_id}/identity/body-slots/body_front/use-existing",
        json={"image_id": 999999},
        headers=headers,
    )
    assert resp.status_code == 404


# ── use-existing-anchor body canon ─────────────────────────────────────

def test_use_existing_anchor_sets_locked_status(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    marking_id = _add_tattoo(client, headers, char_id)
    image_id = _create_image(client, headers, char_id)

    resp = client.post(
        f"/characters/{char_id}/body-markings/{marking_id}/use-existing-anchor",
        json={"image_id": image_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    marking = resp.json()["marking"]
    assert marking["anchor_status"] == "locked"
    assert marking["anchor_image_url"] is not None


def test_use_existing_anchor_does_not_require_prior_generation(client):
    """use-existing-anchor should work even when anchor_status is missing."""
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    marking_id = _add_tattoo(client, headers, char_id)
    image_id = _create_image(client, headers, char_id)

    # Verify marking starts as 'missing'
    markings = client.get(f"/characters/{char_id}/body-markings", headers=headers).json()["markings"]
    m = next(m for m in markings if m["id"] == marking_id)
    assert m["anchor_status"] == "missing"

    resp = client.post(
        f"/characters/{char_id}/body-markings/{marking_id}/use-existing-anchor",
        json={"image_id": image_id},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["marking"]["anchor_status"] == "locked"


def test_use_existing_anchor_wrong_character_image_returns_404(client):
    token1 = get_auth_token(client, email="uea_own@test.com", username="uea_owner")
    token2 = get_auth_token(client, email="uea_oth@test.com", username="uea_other")
    char1 = _create_character(client, auth_headers(token1), "AnchorChar1")
    char2 = _create_character(client, auth_headers(token2), "AnchorChar2")
    marking_id = _add_tattoo(client, auth_headers(token2), char2)
    image_id = _create_image(client, auth_headers(token1), char1)

    resp = client.post(
        f"/characters/{char2}/body-markings/{marking_id}/use-existing-anchor",
        json={"image_id": image_id},
        headers=auth_headers(token2),
    )
    assert resp.status_code == 404


def test_use_existing_anchor_non_owner_returns_403(client):
    token1 = get_auth_token(client, email="uea_o@test.com", username="uea_o")
    token2 = get_auth_token(client, email="uea_x@test.com", username="uea_x")
    char_id = _create_character(client, auth_headers(token1))
    marking_id = _add_tattoo(client, auth_headers(token1), char_id)
    image_id = _create_image(client, auth_headers(token1), char_id)

    resp = client.post(
        f"/characters/{char_id}/body-markings/{marking_id}/use-existing-anchor",
        json={"image_id": image_id},
        headers=auth_headers(token2),
    )
    assert resp.status_code == 403


def test_use_existing_anchor_nonexistent_marking_returns_404(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    image_id = _create_image(client, headers, char_id)

    resp = client.post(
        f"/characters/{char_id}/body-markings/bm_doesnotexist/use-existing-anchor",
        json={"image_id": image_id},
        headers=headers,
    )
    assert resp.status_code == 404


def test_use_existing_anchor_nonexistent_image_returns_404(client):
    token = get_auth_token(client)
    headers = auth_headers(token)
    char_id = _create_character(client, headers)
    marking_id = _add_tattoo(client, headers, char_id)

    resp = client.post(
        f"/characters/{char_id}/body-markings/{marking_id}/use-existing-anchor",
        json={"image_id": 999999},
        headers=headers,
    )
    assert resp.status_code == 404
