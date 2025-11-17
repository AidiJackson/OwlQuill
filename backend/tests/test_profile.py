"""Tests for profile endpoints."""
import pytest
from fastapi.testclient import TestClient


def test_get_user_profile(client: TestClient, auth_headers: dict):
    """Test getting a user profile."""
    # Register a user
    client.post(
        "/auth/register",
        json={
            "email": "testuser@example.com",
            "username": "testuser",
            "password": "testpassword123"
        }
    )

    # Get the user profile
    response = client.get("/profile/users/testuser")
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert "total_posts" in data
    assert "joined_realms_count" in data
    assert "recent_posts" in data


def test_get_user_profile_not_found(client: TestClient):
    """Test getting a non-existent user profile."""
    response = client.get("/profile/users/nonexistent")
    assert response.status_code == 404


def test_get_current_user_profile(client: TestClient, auth_headers: dict):
    """Test getting current user's own profile."""
    response = client.get("/profile/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "username" in data
    assert "total_posts" in data
    assert "joined_realms_count" in data


def test_get_character_profile(client: TestClient, auth_headers: dict):
    """Test getting a character profile."""
    # Create a character
    char_response = client.post(
        "/characters/",
        headers=auth_headers,
        json={
            "name": "Test Character",
            "short_bio": "A test character",
            "visibility": "public"
        }
    )
    assert char_response.status_code == 201
    character_id = char_response.json()["id"]

    # Get the character profile
    response = client.get(f"/profile/characters/{character_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Character"
    assert "owner" in data
    assert "posts_count" in data
    assert "realms_count" in data
    assert "recent_posts" in data


def test_get_character_profile_not_found(client: TestClient):
    """Test getting a non-existent character profile."""
    response = client.get("/profile/characters/99999")
    assert response.status_code == 404


def test_get_private_character_profile_unauthorized(client: TestClient, auth_headers: dict):
    """Test getting a private character profile without permission."""
    # Create a private character
    char_response = client.post(
        "/characters/",
        headers=auth_headers,
        json={
            "name": "Private Character",
            "short_bio": "A private character",
            "visibility": "private"
        }
    )
    assert char_response.status_code == 201
    character_id = char_response.json()["id"]

    # Try to get the profile without auth
    response = client.get(f"/profile/characters/{character_id}")
    assert response.status_code == 403
