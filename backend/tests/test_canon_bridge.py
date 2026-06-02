"""Tests for the pack → canon bridge (seed + lock canon at identity-pack accept).

Verifies that locking an identity pack makes a self-serve character immediately
usable by the canon-routed scene generator, with no manual admin upload.
"""
from fastapi.testclient import TestClient


def _register_and_login(client: TestClient, email: str = "bridge@example.com") -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "testpassword123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Ash Valkyr", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


def _generate_and_accept(client: TestClient, token: str, cid: int) -> None:
    h = {"Authorization": f"Bearer {token}"}
    resp = client.post(f"/characters/{cid}/identity-pack/generate", json={}, headers=h)
    pack_id = resp.json()["pack_id"]
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept", json={"pack_id": pack_id}, headers=h
    )
    assert resp.status_code == 200, resp.text


def test_accept_seeds_and_locks_canon(client: TestClient):
    """Accepting a pack must populate + lock the identity canon from the anchors."""
    token = _register_and_login(client)
    cid = _create_character(client, token)
    h = {"Authorization": f"Bearer {token}"}

    _generate_and_accept(client, token, cid)

    resp = client.get(f"/characters/{cid}/identity-canon", headers=h)
    assert resp.status_code == 200, resp.text
    canon = resp.json()

    assert canon["face_canon"] is not None
    assert canon["face_canon"]["face_front_image_url"], "face_front must be seeded"
    assert canon["body_canon"] is not None
    assert canon["body_canon"]["body_front_image_url"], "body_front must be seeded"
    assert canon["face_locked"] is True
    assert canon["body_locked"] is True
    assert canon["status"] == "locked"


def test_scene_generation_works_immediately_after_lock(client: TestClient):
    """The payoff: include_character generation must not 409 after a normal lock."""
    token = _register_and_login(client, email="bridge2@example.com")
    cid = _create_character(client, token)
    h = {"Authorization": f"Bearer {token}"}

    _generate_and_accept(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/image-generator/generate",
        json={"prompt": "standing in a neon-lit alley", "include_character": True},
        headers=h,
    )
    # Stub provider yields a placeholder, but the canon contract is satisfied:
    # the request must succeed rather than 409 "Character canon incomplete".
    assert resp.status_code == 200, resp.text


def test_accept_migrates_legacy_markings_to_canon(client: TestClient):
    """Legacy body_canon_json markings must migrate into canon permanent_body_marks."""
    token = _register_and_login(client, email="bridge3@example.com")
    cid = _create_character(client, token)
    h = {"Authorization": f"Bearer {token}"}

    # Add a legacy body marking (left full-arm sleeve) before locking.
    resp = client.post(
        f"/characters/{cid}/body-markings/",
        json={
            "type": "tattoo",
            "placement": "left_full_arm",
            "style": "black serpent sleeve",
            "size": "full_sleeve",
            "description": "black ink serpent coiling the full left arm",
        },
        headers=h,
    )
    assert resp.status_code in (200, 201), resp.text

    _generate_and_accept(client, token, cid)

    resp = client.get(f"/characters/{cid}/identity-canon", headers=h)
    assert resp.status_code == 200, resp.text
    marks = resp.json()["body_canon"]["permanent_body_marks"]
    assert len(marks) == 1
    mark = marks[0]
    assert mark["body_region"] == "left_full_arm"
    assert mark["side"] == "left"
    assert mark["type"] == "tattoo"


def test_bridge_is_idempotent_and_non_destructive(client: TestClient, db_session):
    """Re-seeding never clobbers an existing canon slot."""
    from app.services.canon_bridge import seed_canon_from_pack
    from app.models.character import Character as CharacterModel

    token = _register_and_login(client, email="bridge4@example.com")
    cid = _create_character(client, token)
    _generate_and_accept(client, token, cid)

    h = {"Authorization": f"Bearer {token}"}
    before = client.get(f"/characters/{cid}/identity-canon", headers=h).json()
    front_before = before["face_canon"]["face_front_image_url"]

    # Re-run the bridge directly on the test DB — a no-op on already-filled slots.
    char = db_session.query(CharacterModel).filter(CharacterModel.id == cid).first()
    summary = seed_canon_from_pack(char, db_session)
    assert summary["error"] is None
    assert summary["face_front_set"] is False  # already set → not re-set

    after = client.get(f"/characters/{cid}/identity-canon", headers=h).json()
    assert after["face_canon"]["face_front_image_url"] == front_before
