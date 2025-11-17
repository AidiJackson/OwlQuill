"""Tests for report endpoints."""
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


def create_test_realm_and_post(client: TestClient, token: str) -> int:
    """Helper to create a test realm and post, return post_id."""
    # Create realm
    realm_response = client.post(
        "/realms/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Test Realm",
            "slug": "test-realm",
            "is_public": True
        }
    )
    realm_id = realm_response.json()["id"]

    # Join realm
    client.post(
        f"/realms/{realm_id}/join",
        headers={"Authorization": f"Bearer {token}"}
    )

    # Create post
    post_response = client.post(
        f"/realms/{realm_id}/posts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "content": "Test post",
            "content_type": "ooc"
        }
    )
    return post_response.json()["id"]


def create_test_scene_and_post(client: TestClient, token: str) -> int:
    """Helper to create a test scene and post, return scene_post_id."""
    # Create scene
    scene_response = client.post(
        "/scenes/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Test Scene",
            "visibility": "public"
        }
    )
    scene_id = scene_response.json()["id"]

    # Create scene post
    post_response = client.post(
        f"/scenes/{scene_id}/posts",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Test scene post"}
    )
    return post_response.json()["id"]


def test_report_post(client: TestClient):
    """Test reporting a post."""
    token = get_auth_token(client)
    post_id = create_test_realm_and_post(client, token)

    response = client.post(
        "/reports/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "post",
            "target_id": post_id,
            "reason": "spam",
            "details": "This is spam content"
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["target_type"] == "post"
    assert data["target_id"] == post_id
    assert data["reason"] == "spam"
    assert data["details"] == "This is spam content"
    assert data["status"] == "open"
    assert "reporter_id" in data


def test_report_scene_post(client: TestClient):
    """Test reporting a scene post."""
    token = get_auth_token(client)
    scene_post_id = create_test_scene_and_post(client, token)

    response = client.post(
        "/reports/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "scene_post",
            "target_id": scene_post_id,
            "reason": "harassment"
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["target_type"] == "scene_post"
    assert data["target_id"] == scene_post_id
    assert data["reason"] == "harassment"


def test_report_nonexistent_post(client: TestClient):
    """Test reporting a post that doesn't exist."""
    token = get_auth_token(client)

    response = client.post(
        "/reports/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "post",
            "target_id": 99999,
            "reason": "spam"
        }
    )

    assert response.status_code == 404


def test_report_invalid_target_type(client: TestClient):
    """Test reporting with an invalid target type."""
    token = get_auth_token(client)

    response = client.post(
        "/reports/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "invalid_type",
            "target_id": 1,
            "reason": "spam"
        }
    )

    assert response.status_code == 422  # Validation error


def test_report_all_reason_types(client: TestClient):
    """Test reporting with all different reason types."""
    token = get_auth_token(client)
    post_id = create_test_realm_and_post(client, token)

    reasons = ["harassment", "nsfw", "spam", "other"]

    for reason in reasons:
        # Create a new post for each report
        response = client.post(
            "/reports/",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "target_type": "post",
                "target_id": post_id,
                "reason": reason
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["reason"] == reason


def test_report_without_details(client: TestClient):
    """Test that details field is optional."""
    token = get_auth_token(client)
    post_id = create_test_realm_and_post(client, token)

    response = client.post(
        "/reports/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "target_type": "post",
            "target_id": post_id,
            "reason": "spam"
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["details"] is None
