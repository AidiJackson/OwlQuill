"""Tests for discovery and search endpoints."""
import pytest
from fastapi.testclient import TestClient


def test_search_users(client: TestClient):
    """Test searching for users."""
    # Register some users
    client.post(
        "/auth/register",
        json={
            "email": "alice@example.com",
            "username": "alice",
            "password": "testpassword123"
        }
    )
    client.post(
        "/auth/register",
        json={
            "email": "bob@example.com",
            "username": "bob",
            "password": "testpassword123"
        }
    )

    # Search for users
    response = client.get("/discovery/search?q=alice&type=user")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0
    assert data["results"][0]["username"] == "alice"


def test_search_all(client: TestClient, auth_headers: dict):
    """Test searching across all resource types."""
    # Create a user
    client.post(
        "/auth/register",
        json={
            "email": "testuser@example.com",
            "username": "testuser",
            "password": "testpassword123"
        }
    )

    # Create a character
    client.post(
        "/characters/",
        headers=auth_headers,
        json={
            "name": "Test Character",
            "short_bio": "A test character",
            "visibility": "public"
        }
    )

    # Create a realm
    client.post(
        "/realms/",
        headers=auth_headers,
        json={
            "name": "Test Realm",
            "slug": "test-realm",
            "description": "A test realm"
        }
    )

    # Search for "test"
    response = client.get("/discovery/search?q=test&type=all")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0


def test_search_characters(client: TestClient, auth_headers: dict):
    """Test searching for characters."""
    # Create a character
    client.post(
        "/characters/",
        headers=auth_headers,
        json={
            "name": "Dragon Warrior",
            "short_bio": "A brave warrior",
            "visibility": "public"
        }
    )

    # Search for characters
    response = client.get("/discovery/search?q=dragon&type=character")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0


def test_search_realms(client: TestClient, auth_headers: dict):
    """Test searching for realms."""
    # Create a realm
    client.post(
        "/realms/",
        headers=auth_headers,
        json={
            "name": "Fantasy World",
            "slug": "fantasy-world",
            "tagline": "A magical realm"
        }
    )

    # Search for realms
    response = client.get("/discovery/search?q=fantasy&type=realm")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0


def test_search_empty_query(client: TestClient):
    """Test search with empty query."""
    response = client.get("/discovery/search?q=&type=all")
    assert response.status_code == 422  # Validation error
