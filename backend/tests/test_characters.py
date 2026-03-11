"""Tests for character endpoints."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.models.user import User as UserModel


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


def _grant_admin(db_session, email: str) -> None:
    """Directly set is_admin=True for a user via the test DB session."""
    user = db_session.query(UserModel).filter(UserModel.email == email).first()
    assert user is not None, f"User {email} not found"
    user.is_admin = True
    db_session.commit()


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


def test_admin_can_create_multiple_characters(client: TestClient, db_session):
    """Admin user is not subject to the beta 1-character limit."""
    email = "admin@test.com"
    token = _register_and_login(client, email, "adminuser")
    _grant_admin(db_session, email)
    headers = {"Authorization": f"Bearer {token}"}

    r1 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "First"}, headers=headers)
    assert r1.status_code == 201, r1.text

    r2 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "Second"}, headers=headers)
    assert r2.status_code == 201, r2.text

    r3 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "Third"}, headers=headers)
    assert r3.status_code == 201, r3.text


def test_non_admin_delete_sets_cooldown(client: TestClient, db_session):
    """Deleting a character sets a 24-hour creation cooldown for non-admin users."""
    email = "cooldown@test.com"
    token = _register_and_login(client, email, "cooldownuser")
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post("/characters/", json=_CHAR_PAYLOAD, headers=headers)
    assert create_resp.status_code == 201, create_resp.text
    char_id = create_resp.json()["id"]

    del_resp = client.delete(f"/characters/{char_id}", headers=headers)
    assert del_resp.status_code == 204

    # User should now have a cooldown set
    from sqlalchemy.orm import Session
    user = db_session.query(UserModel).filter(UserModel.email == email).first()
    db_session.refresh(user)
    assert user.next_character_allowed_at is not None
    assert user.next_character_allowed_at > datetime.utcnow()


def test_admin_delete_does_not_set_cooldown(client: TestClient, db_session):
    """Deleting a character does not impose a cooldown on admin users."""
    email = "admindel@test.com"
    token = _register_and_login(client, email, "admindeluser")
    _grant_admin(db_session, email)
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = client.post("/characters/", json=_CHAR_PAYLOAD, headers=headers)
    assert create_resp.status_code == 201, create_resp.text
    char_id = create_resp.json()["id"]

    del_resp = client.delete(f"/characters/{char_id}", headers=headers)
    assert del_resp.status_code == 204

    # Admin should have no cooldown set
    user = db_session.query(UserModel).filter(UserModel.email == email).first()
    db_session.refresh(user)
    assert user.next_character_allowed_at is None

    # Admin can immediately create another character
    r2 = client.post("/characters/", json={**_CHAR_PAYLOAD, "name": "Reborn"}, headers=headers)
    assert r2.status_code == 201, r2.text
