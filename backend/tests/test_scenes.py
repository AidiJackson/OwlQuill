"""Tests for scene endpoints."""
from fastapi.testclient import TestClient


def setup_realm_and_token(client: TestClient) -> tuple[str, int]:
    """Helper to create user, realm, and return token + realm_id."""
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

    return token, realm_id


def test_create_scene(client: TestClient):
    """Test creating a scene in a realm."""
    token, realm_id = setup_realm_and_token(client)

    response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "The Dark Forest",
            "description": "A mysterious forest shrouded in darkness"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "The Dark Forest"
    assert data["description"] == "A mysterious forest shrouded in darkness"
    assert data["realm_id"] == realm_id


def test_create_scene_not_member(client: TestClient):
    """Test that non-members cannot create scenes."""
    # Create first user and realm
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
            "name": "Private Realm",
            "slug": "private-realm",
            "is_public": True
        },
        headers={"Authorization": f"Bearer {owner_token}"}
    )
    realm_id = realm_response.json()["id"]

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

    # Try to create scene as non-member
    response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "Test Scene",
            "description": "Test"
        },
        headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403


def test_list_realm_scenes(client: TestClient):
    """Test listing scenes in a realm."""
    token, realm_id = setup_realm_and_token(client)

    # Create multiple scenes
    client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "Scene 1",
            "description": "First scene"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "Scene 2",
            "description": "Second scene"
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # List scenes
    response = client.get(f"/scenes/realms/{realm_id}/scenes")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Ordered by created_at desc, so Scene 2 should be first
    assert data[0]["title"] == "Scene 2"
    assert data[1]["title"] == "Scene 1"


def test_get_scene(client: TestClient):
    """Test getting a single scene."""
    token, realm_id = setup_realm_and_token(client)

    # Create scene
    create_response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "The Dark Forest",
            "description": "A mysterious forest"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    scene_id = create_response.json()["id"]

    # Get scene
    response = client.get(f"/scenes/{scene_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "The Dark Forest"
    assert data["description"] == "A mysterious forest"


def test_update_scene_by_creator(client: TestClient):
    """Test updating a scene by its creator."""
    token, realm_id = setup_realm_and_token(client)

    # Create scene
    create_response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "Original Title",
            "description": "Original description"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    scene_id = create_response.json()["id"]

    # Update scene
    response = client.patch(
        f"/scenes/{scene_id}",
        json={
            "title": "Updated Title",
            "description": "Updated description"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["description"] == "Updated description"


def test_update_scene_unauthorized(client: TestClient):
    """Test that non-creators/non-admins cannot update scenes."""
    # Create first user and scene
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

    # Try to update scene as member (not creator)
    response = client.patch(
        f"/scenes/{scene_id}",
        json={
            "title": "Hacked Title"
        },
        headers={"Authorization": f"Bearer {member_token}"}
    )
    assert response.status_code == 403


def test_delete_scene(client: TestClient):
    """Test deleting a scene."""
    token, realm_id = setup_realm_and_token(client)

    # Create scene
    create_response = client.post(
        f"/scenes/realms/{realm_id}/scenes",
        json={
            "title": "Test Scene",
            "description": "To be deleted"
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    scene_id = create_response.json()["id"]

    # Delete scene
    response = client.delete(
        f"/scenes/{scene_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204

    # Verify scene is deleted
    get_response = client.get(f"/scenes/{scene_id}")
    assert get_response.status_code == 404
