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


# ── character limit tests ─────────────────────────────────────────────────────

def _char_body(name: str) -> dict:
    return {"name": name, "species": "human", "short_bio": "A test character."}


def _register_login(client: TestClient, email: str, username: str) -> dict:
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass!123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_non_admin_cannot_create_second_character(client: TestClient):
    """Non-admin user (max_characters=1) is blocked on the second character creation."""
    hdrs = _register_login(client, "limit_test@example.com", "limit_tester")

    # First character — must succeed (within default limit of 1)
    r1 = client.post("/characters/", json=_char_body("First"), headers=hdrs)
    assert r1.status_code == 201, r1.text

    # Second character — must be blocked (403 character_limit_reached)
    r2 = client.post("/characters/", json=_char_body("Second"), headers=hdrs)
    assert r2.status_code == 403, r2.text
    detail = r2.json()["detail"]
    assert detail["error"] == "character_limit_reached"
    assert detail["max"] == 1


def test_admin_can_create_multiple_characters_up_to_25(client: TestClient, db_session):
    """Admin user (is_admin=True, max_characters=25) can create more than one character."""
    from app.models.user import User as UserModel

    hdrs = _register_login(client, "admin_char_test@example.com", "admin_char_tester")

    # Elevate the test user to admin directly in the shared test DB
    db_session.expire_all()
    user = db_session.query(UserModel).filter(
        UserModel.email == "admin_char_test@example.com"
    ).first()
    assert user is not None, "User should exist after registration"
    user.is_admin = True
    user.max_characters = 25
    db_session.commit()

    # Create 3 characters (beyond the non-admin limit of 1) — all should succeed
    for i in range(3):
        r = client.post("/characters/", json=_char_body(f"AdminChar{i}"), headers=hdrs)
        assert r.status_code == 201, f"Admin character {i} failed: {r.text}"
