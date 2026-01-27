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
