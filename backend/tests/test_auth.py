"""Tests for authentication endpoints."""
import pytest
from fastapi.testclient import TestClient


def test_register_user(client: TestClient):
    """Test user registration."""
    response = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "testpassword123"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["username"] == "testuser"
    assert "id" in data


def test_register_duplicate_email(client: TestClient):
    """Test registration with duplicate email."""
    user_data = {
        "email": "test@example.com",
        "username": "testuser",
        "password": "testpassword123"
    }
    client.post("/auth/register", json=user_data)

    response = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "anotheruser",
            "password": "testpassword123"
        }
    )
    assert response.status_code == 400


def test_login(client: TestClient):
    """Test user login."""
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
        "/auth/login",
        params={
            "email": "test@example.com",
            "password": "testpassword123"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client: TestClient):
    """Test login with wrong password."""
    # Register user
    client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "testpassword123"
        }
    )

    # Login with wrong password
    response = client.post(
        "/auth/login",
        params={
            "email": "test@example.com",
            "password": "wrongpassword"
        }
    )
    assert response.status_code == 401


def test_get_current_user(client: TestClient):
    """Test getting current user info."""
    # Register and login
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

    # Get current user
    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["username"] == "testuser"
