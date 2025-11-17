"""Tests for block endpoints."""
import pytest
from fastapi.testclient import TestClient


def get_auth_token(client: TestClient, email="test@example.com", username="testuser") -> str:
    """Helper to register and login a user, return token."""
    # Register
    client.post(
        "/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "testpassword123"
        }
    )

    # Login
    response = client.post(
        "/auth/login",
        params={
            "email": email,
            "password": "testpassword123"
        }
    )
    return response.json()["access_token"]


def test_block_user(client: TestClient):
    """Test blocking a user."""
    # Create two users
    token1 = get_auth_token(client, "user1@example.com", "user1")
    token2 = get_auth_token(client, "user2@example.com", "user2")

    # User 1 blocks User 2 (need to get user2's ID)
    user2_response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token2}"}
    )
    user2_id = user2_response.json()["id"]

    # Block user2
    response = client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"},
        json={"blocked_id": user2_id}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["blocked_id"] == user2_id
    assert "id" in data
    assert "blocker_id" in data


def test_block_yourself(client: TestClient):
    """Test that you cannot block yourself."""
    token = get_auth_token(client)

    # Get current user's ID
    user_response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    user_id = user_response.json()["id"]

    # Try to block yourself
    response = client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token}"},
        json={"blocked_id": user_id}
    )

    assert response.status_code == 400
    assert "Cannot block yourself" in response.json()["detail"]


def test_block_nonexistent_user(client: TestClient):
    """Test blocking a user that doesn't exist."""
    token = get_auth_token(client)

    response = client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token}"},
        json={"blocked_id": 99999}
    )

    assert response.status_code == 404


def test_duplicate_block(client: TestClient):
    """Test that blocking the same user twice fails."""
    token1 = get_auth_token(client, "user1@example.com", "user1")
    token2 = get_auth_token(client, "user2@example.com", "user2")

    user2_response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token2}"}
    )
    user2_id = user2_response.json()["id"]

    # Block user2
    client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"},
        json={"blocked_id": user2_id}
    )

    # Try to block again
    response = client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"},
        json={"blocked_id": user2_id}
    )

    assert response.status_code == 400
    assert "already blocked" in response.json()["detail"]


def test_list_blocks(client: TestClient):
    """Test listing blocked users."""
    token1 = get_auth_token(client, "user1@example.com", "user1")
    token2 = get_auth_token(client, "user2@example.com", "user2")
    token3 = get_auth_token(client, "user3@example.com", "user3")

    # Get user IDs
    user2_response = client.get("/users/me", headers={"Authorization": f"Bearer {token2}"})
    user2_id = user2_response.json()["id"]

    user3_response = client.get("/users/me", headers={"Authorization": f"Bearer {token3}"})
    user3_id = user3_response.json()["id"]

    # Block both users
    client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"},
        json={"blocked_id": user2_id}
    )
    client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"},
        json={"blocked_id": user3_id}
    )

    # List blocks
    response = client.get(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    blocked_ids = [block["blocked_id"] for block in data]
    assert user2_id in blocked_ids
    assert user3_id in blocked_ids


def test_unblock_user(client: TestClient):
    """Test unblocking a user."""
    token1 = get_auth_token(client, "user1@example.com", "user1")
    token2 = get_auth_token(client, "user2@example.com", "user2")

    user2_response = client.get("/users/me", headers={"Authorization": f"Bearer {token2}"})
    user2_id = user2_response.json()["id"]

    # Block user2
    client.post(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"},
        json={"blocked_id": user2_id}
    )

    # Unblock user2
    response = client.delete(
        f"/blocks/{user2_id}",
        headers={"Authorization": f"Bearer {token1}"}
    )

    assert response.status_code == 204

    # Verify block is gone
    list_response = client.get(
        "/blocks/",
        headers={"Authorization": f"Bearer {token1}"}
    )
    assert len(list_response.json()) == 0


def test_unblock_nonexistent(client: TestClient):
    """Test unblocking a user that was never blocked."""
    token = get_auth_token(client)

    response = client.delete(
        "/blocks/99999",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404
