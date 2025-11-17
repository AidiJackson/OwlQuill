"""Tests for realm endpoints."""
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
        params={
            "email": "test@example.com",
            "password": "testpassword123"
        }
    )
    return response.json()["access_token"]


def test_create_realm(client: TestClient):
    """Test creating a realm."""
    token = get_auth_token(client)

    response = client.post(
        "/realms/",
        json={
            "name": "Fantasy Realm",
            "slug": "fantasy-realm",
            "tagline": "A magical world of wonder",
            "description": "Welcome to our fantasy roleplay realm",
            "genre": "fantasy",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Fantasy Realm"
    assert data["slug"] == "fantasy-realm"
    assert data["tagline"] == "A magical world of wonder"
    assert data["is_public"] is True


def test_create_realm_duplicate_slug(client: TestClient):
    """Test creating realm with duplicate slug."""
    token = get_auth_token(client)

    # Create first realm
    client.post(
        "/realms/",
        json={
            "name": "Fantasy Realm",
            "slug": "fantasy-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # Try to create realm with same slug
    response = client.post(
        "/realms/",
        json={
            "name": "Another Realm",
            "slug": "fantasy-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 400


def test_list_realms(client: TestClient):
    """Test listing realms."""
    token = get_auth_token(client)

    # Create a realm
    client.post(
        "/realms/",
        json={
            "name": "Fantasy Realm",
            "slug": "fantasy-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # List realms
    response = client.get("/realms/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Fantasy Realm"


def test_list_realms_public_only(client: TestClient):
    """Test listing only public realms."""
    token = get_auth_token(client)

    # Create public realm
    client.post(
        "/realms/",
        json={
            "name": "Public Realm",
            "slug": "public-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # Create private realm
    client.post(
        "/realms/",
        json={
            "name": "Private Realm",
            "slug": "private-realm",
            "is_public": False
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # List only public realms
    response = client.get("/realms/?public_only=true")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Public Realm"


def test_get_realm(client: TestClient):
    """Test getting a single realm."""
    token = get_auth_token(client)

    # Create realm
    create_response = client.post(
        "/realms/",
        json={
            "name": "Fantasy Realm",
            "slug": "fantasy-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    realm_id = create_response.json()["id"]

    # Get realm
    response = client.get(f"/realms/{realm_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Fantasy Realm"


def test_join_realm(client: TestClient):
    """Test joining a realm."""
    token = get_auth_token(client)

    # Create realm
    create_response = client.post(
        "/realms/",
        json={
            "name": "Fantasy Realm",
            "slug": "fantasy-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    realm_id = create_response.json()["id"]

    # Join realm (creator is already a member, but this should be idempotent)
    response = client.post(
        f"/realms/{realm_id}/join",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201


def test_join_private_realm_fails(client: TestClient):
    """Test that joining a private realm fails."""
    # Create first user and private realm
    client.post(
        "/auth/register",
        json={
            "email": "owner@example.com",
            "username": "owner",
            "password": "password123"
        }
    )
    owner_login = client.post(
        "/auth/login",
        params={
            "email": "owner@example.com",
            "password": "password123"
        }
    )
    owner_token = owner_login.json()["access_token"]

    create_response = client.post(
        "/realms/",
        json={
            "name": "Private Realm",
            "slug": "private-realm",
            "is_public": False
        },
        headers={"Authorization": f"Bearer {owner_token}"}
    )
    realm_id = create_response.json()["id"]

    # Create second user
    client.post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "username": "user",
            "password": "password123"
        }
    )
    user_login = client.post(
        "/auth/login",
        params={
            "email": "user@example.com",
            "password": "password123"
        }
    )
    user_token = user_login.json()["access_token"]

    # Try to join private realm
    response = client.post(
        f"/realms/{realm_id}/join",
        headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403


def test_list_realm_members(client: TestClient):
    """Test listing realm members."""
    token = get_auth_token(client)

    # Create realm
    create_response = client.post(
        "/realms/",
        json={
            "name": "Fantasy Realm",
            "slug": "fantasy-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    realm_id = create_response.json()["id"]

    # List members
    response = client.get(f"/realms/{realm_id}/members")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1  # Creator is automatically a member
    assert data[0]["role"] == "owner"
