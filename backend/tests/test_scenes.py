"""Tests for scene endpoints."""
import pytest
from fastapi.testclient import TestClient


def get_auth_token(client: TestClient) -> str:
    """Helper to register and login a user, return token."""
    # Register
    client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "testpassword123"
        }
    )

    # Login
    response = client.post(
        "/auth/login",
        params={
            "email": "test@example.com",
            "password": "testpassword123"
        }
    )
    return response.json()["access_token"]


def test_create_scene(client: TestClient):
    """Test scene creation."""
    token = get_auth_token(client)

    response = client.post(
        "/scenes/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "The Dark Forest",
            "description": "A mysterious forest filled with ancient magic.",
            "visibility": "public"
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "The Dark Forest"
    assert data["description"] == "A mysterious forest filled with ancient magic."
    assert data["visibility"] == "public"
    assert "id" in data
    assert "created_by_user_id" in data


def test_create_scene_without_auth(client: TestClient):
    """Test that unauthenticated users cannot create scenes."""
    response = client.post(
        "/scenes/",
        json={
            "title": "Test Scene",
            "description": "Should fail",
            "visibility": "public"
        }
    )

    assert response.status_code == 401


def test_list_scenes(client: TestClient):
    """Test listing public scenes."""
    token = get_auth_token(client)

    # Create a public scene
    client.post(
        "/scenes/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Public Scene",
            "description": "A public scene",
            "visibility": "public"
        }
    )

    # List scenes
    response = client.get(
        "/scenes/",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Public Scene"


def test_list_my_scenes(client: TestClient):
    """Test listing scenes created by current user."""
    token = get_auth_token(client)

    # Create multiple scenes
    for i in range(3):
        client.post(
            "/scenes/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": f"Scene {i}",
                "description": f"Description {i}",
                "visibility": "public" if i % 2 == 0 else "private"
            }
        )

    # List my scenes
    response = client.get(
        "/scenes/?created_by_me=true",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_get_scene(client: TestClient):
    """Test getting a specific scene."""
    token = get_auth_token(client)

    # Create a scene
    create_response = client.post(
        "/scenes/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Test Scene",
            "description": "Test description",
            "visibility": "public"
        }
    )
    scene_id = create_response.json()["id"]

    # Get the scene
    response = client.get(
        f"/scenes/{scene_id}",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Scene"
    assert data["id"] == scene_id


def test_private_scene_access(client: TestClient):
    """Test that private scenes are only accessible to creator."""
    # User 1 creates private scene
    token1 = get_auth_token(client)

    create_response = client.post(
        "/scenes/",
        headers={"Authorization": f"Bearer {token1}"},
        json={
            "title": "Private Scene",
            "description": "Only for me",
            "visibility": "private"
        }
    )
    scene_id = create_response.json()["id"]

    # User 2 tries to access
    client.post(
        "/auth/register",
        json={
            "email": "user2@example.com",
            "username": "user2",
            "password": "password123"
        }
    )
    login_response = client.post(
        "/auth/login",
        params={
            "email": "user2@example.com",
            "password": "password123"
        }
    )
    token2 = login_response.json()["access_token"]

    # Should get 403
    response = client.get(
        f"/scenes/{scene_id}",
        headers={"Authorization": f"Bearer {token2}"}
    )

    assert response.status_code == 403
