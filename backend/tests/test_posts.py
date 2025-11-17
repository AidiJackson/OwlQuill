"""Tests for post endpoints."""
from fastapi.testclient import TestClient


def setup_scene_and_token(client: TestClient) -> tuple[str, int, int]:
    """Helper to create user, realm, scene, and return token + realm_id + scene_id."""
    client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "testpassword123"
        }
    )
    login_response = client.post(
        "/auth/login",
        params={
            "email": "test@example.com",
            "password": "testpassword123"
        }
    )
    token = login_response.json()["access_token"]

    # Create a realm
    realm_response = client.post(
        "/realms/",
        json={
            "name": "Fantasy Realm",
            "slug": "fantasy-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    realm_id = realm_response.json()["id"]

    # Create a scene
    scene_response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "The Dark Forest",
            "description": "A mysterious forest"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    scene_id = scene_response.json()["id"]

    return token, realm_id, scene_id


def test_create_post_in_scene(client: TestClient):
    """Test creating a post in a scene."""
    token, realm_id, scene_id = setup_scene_and_token(client)

    response = client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "title": "A Dark Encounter",
            "content": "The shadows move in the darkness...",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "A Dark Encounter"
    assert data["content"] == "The shadows move in the darkness..."
    assert data["content_type"] == "ic"
    assert data["scene_id"] == scene_id
    assert data["realm_id"] == realm_id


def test_create_post_scene_not_found(client: TestClient):
    """Test creating post in non-existent scene."""
    token, _, _ = setup_scene_and_token(client)

    response = client.post(
        "/posts/scenes/99999/posts",
        json={
            "content": "Test post",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_create_post_not_realm_member(client: TestClient):
    """Test that non-members cannot create posts."""
    # Create first user, realm, and scene
    client.post(
        "/auth/register",
        json={
            "email": "owner@example.com",
            "username": "owner",
            "password": "password123"
        }
    )
    owner_login = client.post(
        "/auth/login",
        params={
            "email": "owner@example.com",
            "password": "password123"
        }
    )
    owner_token = owner_login.json()["access_token"]

    realm_response = client.post(
        "/realms/",
        json={
            "name": "Test Realm",
            "slug": "test-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {owner_token}"}
    )
    realm_id = realm_response.json()["id"]

    scene_response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "Test Scene",
            "description": "Test"
        },
        headers={"Authorization": f"Bearer {owner_token}"}
    )
    scene_id = scene_response.json()["id"]

    # Create second user (not a member)
    client.post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "username": "user",
            "password": "password123"
        }
    )
    user_login = client.post(
        "/auth/login",
        params={
            "email": "user@example.com",
            "password": "password123"
        }
    )
    user_token = user_login.json()["access_token"]

    # Try to create post as non-member
    response = client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "content": "Unauthorized post",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403


def test_list_scene_posts(client: TestClient):
    """Test listing posts in a scene."""
    token, _, scene_id = setup_scene_and_token(client)

    # Create multiple posts
    client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "title": "Post 1",
            "content": "First post",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "title": "Post 2",
            "content": "Second post",
            "content_type": "ooc"
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # List posts
    response = client.get(f"/posts/scenes/{scene_id}/posts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Ordered by created_at desc, so Post 2 should be first
    assert data[0]["title"] == "Post 2"
    assert data[1]["title"] == "Post 1"


def test_get_post(client: TestClient):
    """Test getting a single post."""
    token, _, scene_id = setup_scene_and_token(client)

    # Create post
    create_response = client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "title": "Test Post",
            "content": "Test content",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    post_id = create_response.json()["id"]

    # Get post
    response = client.get(f"/posts/{post_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Post"
    assert data["content"] == "Test content"


def test_delete_post(client: TestClient):
    """Test deleting a post."""
    token, _, scene_id = setup_scene_and_token(client)

    # Create post
    create_response = client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "content": "To be deleted",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    post_id = create_response.json()["id"]

    # Delete post
    response = client.delete(
        f"/posts/{post_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204

    # Verify post is deleted
    get_response = client.get(f"/posts/{post_id}")
    assert get_response.status_code == 404


def test_delete_post_unauthorized(client: TestClient):
    """Test that users cannot delete others' posts."""
    # Create first user and post
    client.post(
        "/auth/register",
        json={
            "email": "creator@example.com",
            "username": "creator",
            "password": "password123"
        }
    )
    creator_login = client.post(
        "/auth/login",
        params={
            "email": "creator@example.com",
            "password": "password123"
        }
    )
    creator_token = creator_login.json()["access_token"]

    realm_response = client.post(
        "/realms/",
        json={
            "name": "Test Realm",
            "slug": "test-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {creator_token}"}
    )
    realm_id = realm_response.json()["id"]

    scene_response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "Test Scene",
            "description": "Test"
        },
        headers={"Authorization": f"Bearer {creator_token}"}
    )
    scene_id = scene_response.json()["id"]

    post_response = client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "content": "Creator's post",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {creator_token}"}
    )
    post_id = post_response.json()["id"]

    # Create second user and join realm
    client.post(
        "/auth/register",
        json={
            "email": "member@example.com",
            "username": "member",
            "password": "password123"
        }
    )
    member_login = client.post(
        "/auth/login",
        params={
            "email": "member@example.com",
            "password": "password123"
        }
    )
    member_token = member_login.json()["access_token"]

    client.post(
        f"/realms/{realm_id}/join",
        headers={"Authorization": f"Bearer {member_token}"}
    )

    # Try to delete creator's post as member
    response = client.delete(
        f"/posts/{post_id}",
        headers={"Authorization": f"Bearer {member_token}"}
    )
    assert response.status_code == 403


def test_get_feed(client: TestClient):
    """Test getting the feed of posts from realms the user is a member of."""
    token, realm_id, scene_id = setup_scene_and_token(client)

    # Create posts in the scene
    client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "content": "Post 1",
            "content_type": "ic"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    client.post(
        f"/posts/scenes/{scene_id}/posts",
        json={
            "content": "Post 2",
            "content_type": "ooc"
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # Get feed
    response = client.get(
        "/posts/feed",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Verify posts belong to the realm
    assert all(post["realm_id"] == realm_id for post in data)


def test_get_feed_empty_when_not_member(client: TestClient):
    """Test that feed is empty when user is not a member of any realms."""
    # Create user but don't join any realms
    client.post(
        "/auth/register",
        json={
            "email": "lonely@example.com",
            "username": "lonely",
            "password": "password123"
        }
    )
    login_response = client.post(
        "/auth/login",
        params={
            "email": "lonely@example.com",
            "password": "password123"
        }
    )
    token = login_response.json()["access_token"]

    # Get feed
    response = client.get(
        "/posts/feed",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0
