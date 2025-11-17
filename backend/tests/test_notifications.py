"""Tests for notification endpoints and triggers."""
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


def create_test_user(client: TestClient, username: str, email: str) -> dict:
    """Helper to create a test user."""
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "testpassword123"
        }
    )
    return response.json()


def test_get_notifications_empty(client: TestClient):
    """Test getting notifications when there are none."""
    user = create_test_user(client, "testuser", "test@example.com")
    headers = get_auth_headers(client, "test@example.com", "testpassword123")

    response = client.get("/notifications/", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_get_unread_count_zero(client: TestClient):
    """Test unread count when there are no notifications."""
    user = create_test_user(client, "testuser", "test@example.com")
    headers = get_auth_headers(client, "test@example.com", "testpassword123")

    response = client.get("/notifications/unread-count", headers=headers)
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_reaction_creates_notification(client: TestClient):
    """Test that reacting to a post creates a notification."""
    # Create two users
    user1 = create_test_user(client, "user1", "user1@example.com")
    user2 = create_test_user(client, "user2", "user2@example.com")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")
    headers2 = get_auth_headers(client, "user2@example.com", "testpassword123")

    # User1 creates a realm
    realm_response = client.post(
        "/realms/",
        json={"name": "Test Realm", "slug": "test-realm"},
        headers=headers1
    )
    realm_id = realm_response.json()["id"]

    # User1 creates a post in the realm
    post_response = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": "Test post"},
        headers=headers1
    )
    post_id = post_response.json()["id"]

    # User2 joins the realm
    client.post(f"/realms/{realm_id}/join", headers=headers2)

    # User2 reacts to user1's post
    client.post(
        f"/reactions/posts/{post_id}/reactions",
        json={"type": "like"},
        headers=headers2
    )

    # Check user1's notifications
    response = client.get("/notifications/", headers=headers1)
    assert response.status_code == 200
    notifications = response.json()
    assert len(notifications) >= 1  # At least the reaction notification

    # Find the reaction notification
    reaction_notif = next((n for n in notifications if n["type"] == "reaction"), None)
    assert reaction_notif is not None
    assert reaction_notif["is_read"] is False


def test_own_reaction_no_notification(client: TestClient):
    """Test that reacting to own post doesn't create a notification."""
    user = create_test_user(client, "testuser", "test@example.com")
    headers = get_auth_headers(client, "test@example.com", "testpassword123")

    # Create a realm and post
    realm_response = client.post(
        "/realms/",
        json={"name": "Test Realm", "slug": "test-realm"},
        headers=headers
    )
    realm_id = realm_response.json()["id"]

    post_response = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": "Test post"},
        headers=headers
    )
    post_id = post_response.json()["id"]

    # React to own post
    client.post(
        f"/reactions/posts/{post_id}/reactions",
        json={"type": "like"},
        headers=headers
    )

    # Check notifications - should not have reaction notification
    response = client.get("/notifications/", headers=headers)
    notifications = response.json()
    reaction_notifs = [n for n in notifications if n["type"] == "reaction"]
    assert len(reaction_notifs) == 0


def test_connection_creates_notification(client: TestClient):
    """Test that following a user creates a notification."""
    # Create two users
    user1 = create_test_user(client, "user1", "user1@example.com")
    user2 = create_test_user(client, "user2", "user2@example.com")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")
    headers2 = get_auth_headers(client, "user2@example.com", "testpassword123")

    # User1 follows user2
    client.post(
        "/connections/",
        json={"following_id": user2["id"]},
        headers=headers1
    )

    # Check user2's notifications
    response = client.get("/notifications/", headers=headers2)
    assert response.status_code == 200
    notifications = response.json()
    assert len(notifications) == 1
    assert notifications[0]["type"] == "connection"
    assert notifications[0]["is_read"] is False


def test_scene_post_creates_notifications(client: TestClient):
    """Test that creating a post in a realm notifies members."""
    # Create owner and member
    owner = create_test_user(client, "owner", "owner@example.com")
    member = create_test_user(client, "member", "member@example.com")

    owner_headers = get_auth_headers(client, "owner@example.com", "testpassword123")
    member_headers = get_auth_headers(client, "member@example.com", "testpassword123")

    # Owner creates realm
    realm_response = client.post(
        "/realms/",
        json={"name": "Test Realm", "slug": "test-realm"},
        headers=owner_headers
    )
    realm_id = realm_response.json()["id"]

    # Member joins realm
    client.post(f"/realms/{realm_id}/join", headers=member_headers)

    # Member creates a post
    client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": "Member's post"},
        headers=member_headers
    )

    # Check owner's notifications
    response = client.get("/notifications/", headers=owner_headers)
    notifications = response.json()
    scene_notifs = [n for n in notifications if n["type"] == "scene_post"]
    assert len(scene_notifs) == 1
    assert scene_notifs[0]["is_read"] is False


def test_mark_notifications_read(client: TestClient):
    """Test marking notifications as read."""
    # Create two users
    user1 = create_test_user(client, "user1", "user1@example.com")
    user2 = create_test_user(client, "user2", "user2@example.com")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")
    headers2 = get_auth_headers(client, "user2@example.com", "testpassword123")

    # User1 follows user2
    client.post(
        "/connections/",
        json={"following_id": user2["id"]},
        headers=headers1
    )

    # Get user2's notifications
    response = client.get("/notifications/", headers=headers2)
    notifications = response.json()
    notification_ids = [n["id"] for n in notifications]

    # Mark as read
    response = client.post(
        "/notifications/mark-read",
        json={"ids": notification_ids},
        headers=headers2
    )
    assert response.status_code == 204

    # Verify they are read
    response = client.get("/notifications/", headers=headers2)
    notifications = response.json()
    for notif in notifications:
        assert notif["is_read"] is True


def test_unread_count(client: TestClient):
    """Test unread notification count."""
    # Create two users
    user1 = create_test_user(client, "user1", "user1@example.com")
    user2 = create_test_user(client, "user2", "user2@example.com")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")
    headers2 = get_auth_headers(client, "user2@example.com", "testpassword123")

    # User1 follows user2
    client.post(
        "/connections/",
        json={"following_id": user2["id"]},
        headers=headers1
    )

    # Check unread count
    response = client.get("/notifications/unread-count", headers=headers2)
    assert response.status_code == 200
    assert response.json()["count"] == 1

    # Mark as read
    notifications = client.get("/notifications/", headers=headers2).json()
    notification_ids = [n["id"] for n in notifications]
    client.post(
        "/notifications/mark-read",
        json={"ids": notification_ids},
        headers=headers2
    )

    # Check unread count again
    response = client.get("/notifications/unread-count", headers=headers2)
    assert response.json()["count"] == 0


def test_only_unread_filter(client: TestClient):
    """Test filtering to only unread notifications."""
    # Create two users
    user1 = create_test_user(client, "user1", "user1@example.com")
    user2 = create_test_user(client, "user2", "user2@example.com")

    headers1 = get_auth_headers(client, "user1@example.com", "testpassword123")
    headers2 = get_auth_headers(client, "user2@example.com", "testpassword123")

    # Create two notifications
    client.post("/connections/", json={"following_id": user2["id"]}, headers=headers1)

    # Get notifications and mark first as read
    notifications = client.get("/notifications/", headers=headers2).json()
    first_id = notifications[0]["id"]
    client.post("/notifications/mark-read", json={"ids": [first_id]}, headers=headers2)

    # Create another notification
    user3 = create_test_user(client, "user3", "user3@example.com")
    headers3 = get_auth_headers(client, "user3@example.com", "testpassword123")
    client.post("/connections/", json={"following_id": user2["id"]}, headers=headers3)

    # Get only unread
    response = client.get("/notifications/?only_unread=true", headers=headers2)
    unread_notifications = response.json()
    assert len(unread_notifications) == 1
    assert all(not n["is_read"] for n in unread_notifications)
