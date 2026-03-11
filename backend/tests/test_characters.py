"""Tests for character endpoints."""
from fastapi.testclient import TestClient


def get_auth_token(client: TestClient) -> str:
    """Helper to get auth token."""
    client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "testpassword123"
        }
    )
    response = client.post(
        "/auth/login",
        json={
            "email": "test@example.com",
            "password": "testpassword123"
        }
    )
    return response.json()["access_token"]


_CHAR_PAYLOAD = {
    "name": "Test Hero",
    "species": "human",
    "short_bio": "A test hero.",
}


def _register_and_login(client: TestClient, email: str, username: str) -> str:
    """Register a new user and return their auth token."""
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass!123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _make_admin(monkeypatch, email: str) -> None:
    """Grant admin status to an email via settings monkeypatch (no DB access needed)."""
    from app.core import config as cfg_module
    monkeypatch.setenv("ADMIN_EMAILS", email)
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", email)


def test_create_character(client: TestClient):
    """Test creating a character."""
    token = get_auth_token(client)

    response = client.post(
        "/characters/",
        json={
            "name": "Luna Nightshade",
            "species": "vampire",
            "tags": "gothic, mysterious",
            "short_bio": "A mysterious vampire from the old world"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Luna Nightshade"
    assert data["species"] == "vampire"


def test_list_characters(client: TestClient):
    """Test listing characters."""
    token = get_auth_token(client)

    # Create a character
    client.post(
        "/characters/",
        json={
            "name": "Luna Nightshade",
            "species": "vampire",
            "short_bio": "A mysterious vampire"
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # List characters
    response = client.get(
        "/characters/",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Luna Nightshade"


# ── Admin bypass tests ────────────────────────────────────────────────────────

def test_non_admin_limited_to_one_character(client: TestClient):
    """Non-admin user cannot create a second character (beta 1-character limit)."""
    token = _register_and_login(client, "beta@test.com", "betauser")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "First"}, headers=headers)
    assert r1.status_code == 201, r1.text

    r2 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "Second"}, headers=headers)
    assert r2.status_code == 403
    assert "Beta limit" in r2.json()["detail"]


def test_admin_can_create_multiple_characters(client: TestClient, monkeypatch):
    """Admin user is not subject to the beta 1-character limit."""
    email = "admin@test.com"
    _make_admin(monkeypatch, email)
    token = _register_and_login(client, email, "adminuser")
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "First"}, headers=headers)
    assert r1.status_code == 201, r1.text

    r2 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "Second"}, headers=headers)
    assert r2.status_code == 201, r2.text

    r3 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "Third"}, headers=headers)
    assert r3.status_code == 201, r3.text


def test_non_admin_delete_sets_cooldown(client: TestClient):
    """Deleting a character blocks a non-admin from immediately creating a new one."""
    token = _register_and_login(client, "cooldown@test.com", "cooldownuser")
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post("/characters/", json=_CHAR_PAYLOAD, headers=headers)
    assert create_resp.status_code == 201, create_resp.text
    char_id = create_resp.json()["id"]

    del_resp = client.delete(f"/characters/{char_id}", headers=headers)
    assert del_resp.status_code == 204

    # Cooldown should now block a new character creation
    r2 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "After Delete"}, headers=headers)
    assert r2.status_code == 403
    assert "cooldown" in r2.json()["detail"].lower()


def test_admin_delete_does_not_set_cooldown(client: TestClient, monkeypatch):
    """Admin can delete a character and immediately create a new one (no cooldown)."""
    email = "admindel@test.com"
    _make_admin(monkeypatch, email)
    token = _register_and_login(client, email, "admindeluser")
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post("/characters/", json=_CHAR_PAYLOAD, headers=headers)
    assert create_resp.status_code == 201, create_resp.text
    char_id = create_resp.json()["id"]

    del_resp = client.delete(f"/characters/{char_id}", headers=headers)
    assert del_resp.status_code == 204

    # Admin can immediately create another character (no cooldown)
    r2 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "Reborn"}, headers=headers)
    assert r2.status_code == 201, r2.text
