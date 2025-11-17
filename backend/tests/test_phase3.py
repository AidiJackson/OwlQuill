"""Tests for Phase 3 features: reactions and connections."""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture
def auth_headers(test_user):
    """Get authentication headers for test user."""
    response = client.post(
        "/auth/login",
        params={"email": test_user["email"], "password": test_user["password"]}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user(db_session):
    """Create a second test user."""
    response = client.post(
        "/auth/register",
        json={
            "email": "user2@example.com",
            "username": "testuser2",
            "password": "testpass123"
        }
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def second_user_headers(second_user):
    """Get authentication headers for second user."""
    response = client.post(
        "/auth/login",
        params={"email": second_user["email"], "password": "testpass123"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_toggle_reaction(auth_headers, test_realm, test_post):
    """Test toggling reaction on a post."""
    # Toggle reaction (add)
    response = client.post(
        f"/reactions/posts/{test_post['id']}/react",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "added"
    assert data["count"] == 1
    assert data["user_reacted"] is True

    # Toggle reaction again (remove)
    response = client.post(
        f"/reactions/posts/{test_post['id']}/react",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "removed"
    assert data["count"] == 0
    assert data["user_reacted"] is False


def test_get_post_reactions(auth_headers, test_post):
    """Test getting reaction status for a post."""
    # Get reactions for post with no reactions
    response = client.get(
        f"/reactions/posts/{test_post['id']}/reactions",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["user_reacted"] is False

    # Add a reaction
    client.post(
        f"/reactions/posts/{test_post['id']}/react",
        headers=auth_headers
    )

    # Get reactions again
    response = client.get(
        f"/reactions/posts/{test_post['id']}/reactions",
        headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["user_reacted"] is True


def test_connect_to_user(auth_headers, second_user):
    """Test connecting to another user."""
    # Connect to second user
    response = client.post(
        f"/users/{second_user['id']}/connect",
        headers=auth_headers
    )
    assert response.status_code == 201
    assert "message" in response.json()


def test_cannot_connect_to_self(auth_headers, test_user):
    """Test that user cannot connect to themselves."""
    response = client.post(
        f"/users/{test_user['id']}/connect",
        headers=auth_headers
    )
    assert response.status_code == 400


def test_get_connections(auth_headers, second_user):
    """Test getting list of connections."""
    # Connect to second user first
    client.post(
        f"/users/{second_user['id']}/connect",
        headers=auth_headers
    )

    # Get connections
    response = client.get(
        "/users/me/connections",
        headers=auth_headers
    )
    assert response.status_code == 200
    connections = response.json()
    assert len(connections) == 1
    assert connections[0]["id"] == second_user["id"]


def test_disconnect_from_user(auth_headers, second_user):
    """Test disconnecting from a user."""
    # Connect first
    client.post(
        f"/users/{second_user['id']}/connect",
        headers=auth_headers
    )

    # Disconnect
    response = client.delete(
        f"/users/{second_user['id']}/connect",
        headers=auth_headers
    )
    assert response.status_code == 204

    # Verify disconnected
    response = client.get(
        "/users/me/connections",
        headers=auth_headers
    )
    connections = response.json()
    assert len(connections) == 0


def test_feed_includes_connected_users_posts(
    auth_headers, second_user_headers, second_user, test_realm
):
    """Test that feed includes posts from connected users."""
    # Second user joins realm and creates a post
    client.post(f"/realms/{test_realm['id']}/join", headers=second_user_headers)
    response = client.post(
        f"/posts/realms/{test_realm['id']}/posts",
        headers=second_user_headers,
        json={"content": "Post from second user", "content_type": "ic"}
    )
    assert response.status_code == 201

    # First user connects to second user
    client.post(f"/users/{second_user['id']}/connect", headers=auth_headers)

    # First user gets feed
    response = client.get("/posts/feed", headers=auth_headers)
    assert response.status_code == 200
    posts = response.json()

    # Should include post from connected user
    post_authors = [post["author_user_id"] for post in posts]
    assert second_user["id"] in post_authors
