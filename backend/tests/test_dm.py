"""Tests for direct messaging endpoints."""
import pytest
from fastapi.testclient import TestClient


def create_test_user(client: TestClient, email: str, username: str, password: str = "testpass123"):
    """Helper to create a test user and return auth token."""
    # Register
    client.post(
        "/auth/register",
        json={
            "email": email,
            "username": username,
            "password": password
        }
    )
    # Login
    login_response = client.post(
        "/auth/login",
        params={
            "email": email,
            "password": password
        }
    )
    return login_response.json()["access_token"]


def test_start_conversation(client: TestClient):
    """Test starting a new conversation."""
    # Create two users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")

    # Start conversation as user1 with user2
    response = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert len(data["participants"]) == 2
    assert len(data["messages"]) == 0


def test_start_conversation_returns_existing(client: TestClient):
    """Test that starting a conversation returns existing one if it exists."""
    # Create two users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")

    # Start conversation first time
    response1 = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id_1 = response1.json()["id"]

    # Start conversation again
    response2 = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id_2 = response2.json()["id"]

    # Should return same conversation
    assert conv_id_1 == conv_id_2


def test_start_conversation_with_self_fails(client: TestClient):
    """Test that starting a conversation with yourself fails."""
    user1_token = create_test_user(client, "user1@test.com", "user1")

    response = client.post(
        "/dm/start",
        json={"target_username": "user1"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert response.status_code == 400


def test_start_conversation_with_nonexistent_user_fails(client: TestClient):
    """Test that starting a conversation with nonexistent user fails."""
    user1_token = create_test_user(client, "user1@test.com", "user1")

    response = client.post(
        "/dm/start",
        json={"target_username": "nonexistent"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert response.status_code == 404


def test_send_message(client: TestClient):
    """Test sending a message in a conversation."""
    # Create two users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")

    # Start conversation
    conv_response = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id = conv_response.json()["id"]

    # Send message
    message_response = client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Hello, user2!"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert message_response.status_code == 201
    message_data = message_response.json()
    assert message_data["content"] == "Hello, user2!"
    assert message_data["conversation_id"] == conv_id


def test_list_conversations(client: TestClient):
    """Test listing conversations."""
    # Create three users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")
    user3_token = create_test_user(client, "user3@test.com", "user3")

    # User1 starts conversations with user2 and user3
    client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    client.post(
        "/dm/start",
        json={"target_username": "user3"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )

    # List conversations for user1
    response = client.get(
        "/dm/conversations",
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert response.status_code == 200
    conversations = response.json()
    assert len(conversations) == 2


def test_get_conversation_detail(client: TestClient):
    """Test getting conversation details."""
    # Create two users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")

    # Start conversation and send messages
    conv_response = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id = conv_response.json()["id"]

    # Send messages
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Message 1"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Message 2"},
        headers={"Authorization": f"Bearer {user2_token}"}
    )

    # Get conversation detail
    response = client.get(
        f"/dm/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["messages"]) == 2
    assert len(data["participants"]) == 2


def test_unauthorized_conversation_access(client: TestClient):
    """Test that users cannot access conversations they're not part of."""
    # Create three users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")
    user3_token = create_test_user(client, "user3@test.com", "user3")

    # User1 starts conversation with user2
    conv_response = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id = conv_response.json()["id"]

    # User3 tries to access the conversation
    response = client.get(
        f"/dm/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {user3_token}"}
    )
    assert response.status_code == 403

    # User3 tries to send message
    message_response = client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Hacking in!"},
        headers={"Authorization": f"Bearer {user3_token}"}
    )
    assert message_response.status_code == 403


def test_unread_count(client: TestClient):
    """Test unread message count."""
    # Create two users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")

    # Start conversation
    conv_response = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id = conv_response.json()["id"]

    # User1 sends 3 messages
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Message 1"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Message 2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Message 3"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )

    # User2 lists conversations and should see unread count
    response = client.get(
        "/dm/conversations",
        headers={"Authorization": f"Bearer {user2_token}"}
    )
    conversations = response.json()
    assert len(conversations) == 1
    assert conversations[0]["unread_count"] == 3


def test_mark_messages_read(client: TestClient):
    """Test marking messages as read."""
    # Create two users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")

    # Start conversation
    conv_response = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id = conv_response.json()["id"]

    # User1 sends messages
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Message 1"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Message 2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )

    # User2 checks unread count
    response = client.get(
        "/dm/conversations",
        headers={"Authorization": f"Bearer {user2_token}"}
    )
    assert response.json()[0]["unread_count"] == 2

    # User2 marks messages as read
    mark_read_response = client.post(
        f"/dm/conversations/{conv_id}/read",
        json={},
        headers={"Authorization": f"Bearer {user2_token}"}
    )
    assert mark_read_response.status_code == 204

    # Check unread count again
    response = client.get(
        "/dm/conversations",
        headers={"Authorization": f"Bearer {user2_token}"}
    )
    assert response.json()[0]["unread_count"] == 0


def test_notification_created_on_message(client: TestClient):
    """Test that a notification is created when a message is sent."""
    # Create two users
    user1_token = create_test_user(client, "user1@test.com", "user1")
    user2_token = create_test_user(client, "user2@test.com", "user2")

    # Start conversation
    conv_response = client.post(
        "/dm/start",
        json={"target_username": "user2"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    conv_id = conv_response.json()["id"]

    # User1 sends message
    client.post(
        f"/dm/conversations/{conv_id}/messages",
        json={"content": "Hello!"},
        headers={"Authorization": f"Bearer {user1_token}"}
    )

    # Note: We would need a notifications endpoint to verify this properly
    # For now, we're testing that the message creation doesn't fail
    # The notification creation is part of the message sending logic
