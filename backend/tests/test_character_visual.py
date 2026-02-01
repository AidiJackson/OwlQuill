"""Tests for character visual endpoints (DNA, identity pack, moments)."""
from fastapi.testclient import TestClient


def _register_and_login(client: TestClient) -> str:
    """Register a test user and return a bearer token."""
    client.post(
        "/auth/register",
        json={
            "email": "viztest@example.com",
            "username": "vizuser",
            "password": "testpassword123",
        },
    )
    resp = client.post(
        "/auth/login",
        json={"email": "viztest@example.com", "password": "testpassword123"},
    )
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    """Create a character and return its ID."""
    resp = client.post(
        "/characters/",
        json={"name": "Ash Valkyr", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


# ── DNA endpoint ─────────────────────────────────────────────────────

def test_upsert_dna(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/dna",
        json={
            "species": "human",
            "gender_presentation": "feminine",
            "visual_traits_json": {"hair_color": "silver", "eye_color": "amber"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["character_id"] == cid
    assert data["species"] == "human"
    assert data["visual_traits_json"]["hair_color"] == "silver"
    assert data["anchor_version"] == 1


# ── Identity pack generate ───────────────────────────────────────────

def test_generate_identity_pack(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={"tweaks": {"hair": "long silver"}, "prompt_vibe": "ethereal warrior"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "pack_id" in data
    assert len(data["images"]) == 3
    roles = {img["metadata_json"]["pack_role"] for img in data["images"]}
    assert roles == {"anchor_front", "anchor_three_quarter", "anchor_torso"}
    for img in data["images"]:
        assert img["kind"] == "generated"
        assert img["metadata_json"]["is_temp"] is True


def test_generate_pack_blocked_after_lock(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Generate + accept to lock
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]

    client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Now try generating again — should fail
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ── Identity pack accept ─────────────────────────────────────────────

def test_accept_identity_pack(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # First set up DNA
    client.post(
        f"/characters/{cid}/dna",
        json={"species": "elf"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Generate pack
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]

    # Accept pack
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["anchors"]) == 3
    kinds = {a["kind"] for a in data["anchors"]}
    assert kinds == {"anchor_front", "anchor_three_quarter", "anchor_torso"}
    assert data["dna"] is not None
    assert data["dna"]["anchor_version"] == 1

    # Verify character is now locked
    resp = client.get(
        f"/characters/{cid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["visual_locked"] is True


def test_accept_invalid_pack_id(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": "nonexistent"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ── Moment generation (post-lock) ────────────────────────────────────

def test_generate_moment_image(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Lock the character first
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]
    client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Now generate a moment
    resp = client.post(
        f"/characters/{cid}/images/generate",
        json={"outfit": "battle armor", "mood": "determined", "environment": "moonlit forest"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "generated"
    assert data["metadata_json"]["anchor_version"] == 1
    assert data["file_path"].startswith("static/generated/")


def test_moment_blocked_before_lock(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/images/generate",
        json={"mood": "happy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
