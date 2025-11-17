"""Tests for AI endpoints."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.ai.factory import reset_ai_client


@pytest.fixture(autouse=True)
def reset_ai_client_fixture():
    """Reset AI client between tests."""
    reset_ai_client()
    yield
    reset_ai_client()


@pytest.fixture
def auth_headers(client: TestClient):
    """Create a user and return auth headers."""
    # Register user
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
        "/auth/login?email=test@example.com&password=testpassword123",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_generate_character_bio_success(client: TestClient, auth_headers):
    """Test character bio generation with valid data."""
    response = client.post(
        "/ai/character-bio",
        json={
            "name": "Aria Shadowheart",
            "species": "vampire",
            "role": "assassin",
            "era": "Victorian",
            "tags": ["gothic", "mysterious", "dangerous"]
        },
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "short_bio" in data
    assert "long_bio" in data
    assert "Aria Shadowheart" in data["short_bio"]
    assert "vampire" in data["short_bio"]
    assert len(data["long_bio"]) > len(data["short_bio"])


def test_generate_character_bio_minimal(client: TestClient, auth_headers):
    """Test character bio generation with minimal data."""
    response = client.post(
        "/ai/character-bio",
        json={"name": "John"},
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "short_bio" in data
    assert "long_bio" in data
    assert "John" in data["short_bio"]


def test_generate_character_bio_unauthorized(client: TestClient):
    """Test character bio generation without authentication."""
    response = client.post(
        "/ai/character-bio",
        json={"name": "Test"}
    )
    assert response.status_code == 401


def test_suggest_post_reply_success(client: TestClient, auth_headers):
    """Test post suggestion with valid data."""
    response = client.post(
        "/ai/posts/suggest",
        json={
            "realm_name": "Dark Castle",
            "character_name": "Aria",
            "recent_posts": [
                "The gates creaked open slowly.",
                "A figure emerged from the shadows."
            ],
            "tone_hint": "dramatic"
        },
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "suggested_text" in data
    assert len(data["suggested_text"]) > 0
    assert isinstance(data["suggested_text"], str)


def test_suggest_post_reply_minimal(client: TestClient, auth_headers):
    """Test post suggestion with minimal data."""
    response = client.post(
        "/ai/posts/suggest",
        json={},
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "suggested_text" in data


def test_summarize_scene_success(client: TestClient, auth_headers):
    """Test scene summary with posts."""
    response = client.post(
        "/ai/scenes/summary",
        json={
            "realm_name": "Dark Castle",
            "posts": [
                "The hero enters the castle.",
                "A vampire appears from the shadows.",
                "They engage in combat.",
                "The hero is wounded but escapes."
            ]
        },
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert len(data["summary"]) > 0
    assert "Dark Castle" in data["summary"]


def test_summarize_scene_empty(client: TestClient, auth_headers):
    """Test scene summary with no posts."""
    response = client.post(
        "/ai/scenes/summary",
        json={
            "realm_name": "Empty Realm",
            "posts": []
        },
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "no posts" in data["summary"].lower() or "yet to" in data["summary"].lower()


def test_legacy_generate_scene(client: TestClient, auth_headers):
    """Test legacy scene generation endpoint."""
    response = client.post(
        "/ai/scene",
        json={
            "characters": ["Aria", "Viktor"],
            "setting": "abandoned cathedral",
            "mood": "tense",
            "prompt": "The confrontation begins"
        },
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "scene" in data
    assert "dialogue" in data
    assert "abandoned cathedral" in data["scene"]
    assert "The confrontation begins" in data["dialogue"]


def test_ai_disabled(client: TestClient, auth_headers, monkeypatch):
    """Test AI endpoints when AI_ENABLED is False."""
    # Temporarily disable AI
    monkeypatch.setattr(settings, "AI_ENABLED", False)

    response = client.post(
        "/ai/character-bio",
        json={"name": "Test"},
        headers=auth_headers
    )
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()
