"""Tests for discovery endpoints."""
import pytest
from fastapi.testclient import TestClient


def get_auth_headers(client: TestClient, email: str, password: str) -> dict:
    """Helper to get authentication headers."""
    response = client.post(
        "/auth/login",
        params={"email": email, "password": password}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_test_user(client: TestClient, username: str, email: str, display_name: str = None) -> dict:
    """Helper to create a test user."""
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "testpassword123",
            "display_name": display_name
        }
    )
    return response.json()


def test_discover_users_no_search(client: TestClient):
    """Test discovering users without search query."""
    # Create main user
    user1 = create_test_user(client, "user1", "user1@example.com")
    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")

    # Create other users
    user2 = create_test_user(client, "user2", "user2@example.com")
    user3 = create_test_user(client, "user3", "user3@example.com")

    # Discover users
    response = client.get("/discovery/users", headers=headers1)
    assert response.status_code == 200
    users = response.json()

    # Should not include current user
    usernames = [u["username"] for u in users]
    assert "user1" not in usernames
    assert "user2" in usernames
    assert "user3" in usernames


def test_discover_users_search_by_username(client: TestClient):
    """Test discovering users by username search."""
    # Create users
    user1 = create_test_user(client, "alice", "alice@example.com")
    user2 = create_test_user(client, "bob", "bob@example.com")
    user3 = create_test_user(client, "charlie", "charlie@example.com")

    headers1 = get_auth_headers(client, "alice@example.com", "testpassword123")

    # Search for "bob"
    response = client.get("/discovery/users?search=bob", headers=headers1)
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["username"] == "bob"


def test_discover_users_search_by_display_name(client: TestClient):
    """Test discovering users by display name search."""
    # Create users
    user1 = create_test_user(client, "user1", "user1@example.com", "Alice Wonder")
    user2 = create_test_user(client, "user2", "user2@example.com", "Bob Builder")
    user3 = create_test_user(client, "user3", "user3@example.com", "Charlie Day")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")

    # Search for "Builder"
    response = client.get("/discovery/users?search=Builder", headers=headers1)
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["display_name"] == "Bob Builder"


def test_discover_users_excludes_following(client: TestClient):
    """Test that suggested users exclude those already followed."""
    # Create users
    user1 = create_test_user(client, "user1", "user1@example.com")
    user2 = create_test_user(client, "user2", "user2@example.com")
    user3 = create_test_user(client, "user3", "user3@example.com")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")

    # User1 follows user2
    client.post("/connections/", json={"following_id": user2["id"]}, headers=headers1)

    # Get suggested users (no search)
    response = client.get("/discovery/users", headers=headers1)
    users = response.json()
    usernames = [u["username"] for u in users]

    # Should only include user3, not user2 (already following)
    assert "user2" not in usernames
    assert "user3" in usernames


def test_discover_realms_no_search(client: TestClient):
    """Test discovering realms without search query."""
    # Create users
    user1 = create_test_user(client, "user1", "user1@example.com")
    user2 = create_test_user(client, "user2", "user2@example.com")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")
    headers2 = get_auth_headers(client, "user2@example.com", "testpassword123")

    # Create public realms
    client.post(
        "/realms/",
        json={"name": "Fantasy World", "slug": "fantasy-world", "is_public": True},
        headers=headers1
    )
    client.post(
        "/realms/",
        json={"name": "Sci-Fi Universe", "slug": "scifi-universe", "is_public": True},
        headers=headers2
    )

    # Discover realms
    response = client.get("/discovery/realms")
    assert response.status_code == 200
    realms = response.json()
    assert len(realms) == 2
    realm_names = [r["name"] for r in realms]
    assert "Fantasy World" in realm_names
    assert "Sci-Fi Universe" in realm_names


def test_discover_realms_search_by_name(client: TestClient):
    """Test discovering realms by name search."""
    # Create user
    user = create_test_user(client, "user1", "user1@example.com")
    headers = get_auth_headers(client, "user1@example.com", "testpassword123")

    # Create realms
    client.post(
        "/realms/",
        json={"name": "Fantasy World", "slug": "fantasy-world", "is_public": True},
        headers=headers
    )
    client.post(
        "/realms/",
        json={"name": "Sci-Fi Universe", "slug": "scifi-universe", "is_public": True},
        headers=headers
    )

    # Search for "Fantasy"
    response = client.get("/discovery/realms?search=Fantasy")
    assert response.status_code == 200
    realms = response.json()
    assert len(realms) == 1
    assert realms[0]["name"] == "Fantasy World"


def test_discover_realms_search_by_description(client: TestClient):
    """Test discovering realms by description search."""
    # Create user
    user = create_test_user(client, "user1", "user1@example.com")
    headers = get_auth_headers(client, "user1@example.com", "testpassword123")

    # Create realms with descriptions
    client.post(
        "/realms/",
        json={
            "name": "Realm One",
            "slug": "realm-one",
            "description": "A world of magic and dragons",
            "is_public": True
        },
        headers=headers
    )
    client.post(
        "/realms/",
        json={
            "name": "Realm Two",
            "slug": "realm-two",
            "description": "Space exploration and aliens",
            "is_public": True
        },
        headers=headers
    )

    # Search for "dragons"
    response = client.get("/discovery/realms?search=dragons")
    assert response.status_code == 200
    realms = response.json()
    assert len(realms) == 1
    assert realms[0]["name"] == "Realm One"


def test_discover_realms_excludes_private(client: TestClient):
    """Test that discovery only shows public realms."""
    # Create user
    user = create_test_user(client, "user1", "user1@example.com")
    headers = get_auth_headers(client, "user1@example.com", "testpassword123")

    # Create public and private realms
    client.post(
        "/realms/",
        json={"name": "Public Realm", "slug": "public-realm", "is_public": True},
        headers=headers
    )
    client.post(
        "/realms/",
        json={"name": "Private Realm", "slug": "private-realm", "is_public": False},
        headers=headers
    )

    # Discover realms
    response = client.get("/discovery/realms")
    realms = response.json()
    realm_names = [r["name"] for r in realms]

    # Should only show public realm
    assert "Public Realm" in realm_names
    assert "Private Realm" not in realm_names


def test_discover_users_pagination(client: TestClient):
    """Test user discovery pagination."""
    # Create main user
    user1 = create_test_user(client, "user1", "user1@example.com")
    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")

    # Create many users
    for i in range(25):
        create_test_user(client, f"user{i+2}", f"user{i+2}@example.com")

    # Get first page
    response = client.get("/discovery/users?limit=10", headers=headers1)
    assert response.status_code == 200
    users_page1 = response.json()
    assert len(users_page1) == 10

    # Get second page
    response = client.get("/discovery/users?skip=10&limit=10", headers=headers1)
    users_page2 = response.json()
    assert len(users_page2) == 10

    # Ensure different users
    ids_page1 = {u["id"] for u in users_page1}
    ids_page2 = {u["id"] for u in users_page2}
    assert ids_page1.isdisjoint(ids_page2)
