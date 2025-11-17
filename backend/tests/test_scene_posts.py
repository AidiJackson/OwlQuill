"""Tests for scene post endpoints."""
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


def create_test_scene(client: TestClient, token: str) -> int:
    """Helper to create a test scene, return scene_id."""
    response = client.post(
        "/scenes/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Test Scene",
            "description": "A test scene",
            "visibility": "public"
        }
    )
    return response.json()["id"]


def test_create_scene_post(client: TestClient):
    """Test creating a post in a scene."""
    token = get_auth_token(client)
    scene_id = create_test_scene(client, token)

    response = client.post(
        f"/scenes/{scene_id}/posts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": "This is my first post in the scene!",
            "character_id": None
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "This is my first post in the scene!"
    assert data["scene_id"] == scene_id
    assert "id" in data
    assert "author_user_id" in data
    assert "created_at" in data


def test_create_scene_post_without_auth(client: TestClient):
    """Test that unauthenticated users cannot post in scenes."""
    token = get_auth_token(client)
    scene_id = create_test_scene(client, token)

    response = client.post(
        f"/scenes/{scene_id}/posts",
        json={
            "content": "This should fail",
            "character_id": None
        }
    )

    assert response.status_code == 401


def test_list_scene_posts(client: TestClient):
    """Test listing posts in a scene."""
    token = get_auth_token(client)
    scene_id = create_test_scene(client, token)

    # Create multiple posts
    for i in range(3):
        client.post(
            f"/scenes/{scene_id}/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "content": f"Post number {i}",
                "character_id": None
            }
        )

    # List posts
    response = client.get(
        f"/scenes/{scene_id}/posts",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # Posts should be ordered by creation time (ascending)
    assert data[0]["content"] == "Post number 0"
    assert data[1]["content"] == "Post number 1"
    assert data[2]["content"] == "Post number 2"


def test_list_posts_for_nonexistent_scene(client: TestClient):
    """Test listing posts for a scene that doesn't exist."""
    token = get_auth_token(client)

    response = client.get(
        "/scenes/99999/posts",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_post_in_nonexistent_scene(client: TestClient):
    """Test posting in a scene that doesn't exist."""
    token = get_auth_token(client)

    response = client.post(
        "/scenes/99999/posts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": "This should fail",
            "character_id": None
        }
    )

    assert response.status_code == 404


def test_post_with_reply_to(client: TestClient):
    """Test creating a post that replies to another post."""
    token = get_auth_token(client)
    scene_id = create_test_scene(client, token)

    # Create first post
    first_post_response = client.post(
        f"/scenes/{scene_id}/posts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": "Original post",
            "character_id": None
        }
    )
    first_post_id = first_post_response.json()["id"]

    # Create reply
    response = client.post(
        f"/scenes/{scene_id}/posts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": "This is a reply!",
            "character_id": None,
            "reply_to_id": first_post_id
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["reply_to_id"] == first_post_id
    assert data["content"] == "This is a reply!"


def test_private_scene_post_access(client: TestClient):
    """Test that users cannot post in private scenes they don't own."""
    # User 1 creates private scene
    token1 = get_auth_token(client, "user1@example.com", "user1")

    scene_response = client.post(
        "/scenes/",
        headers={"Authorization": f"Bearer {token1}"},
        json={
            "title": "Private Scene",
            "description": "Private",
            "visibility": "private"
        }
    )
    scene_id = scene_response.json()["id"]

    # User 2 tries to post
    token2 = get_auth_token(client, "user2@example.com", "user2")

    response = client.post(
        f"/scenes/{scene_id}/posts",
        headers={"Authorization": f"Bearer {token2}"},
        json={
            "content": "Should not be allowed",
            "character_id": None
        }
    )

    assert response.status_code == 403
