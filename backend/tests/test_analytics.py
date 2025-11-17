"""Tests for analytics event logging endpoints."""
import pytest
from fastapi.testclient import TestClient


def test_log_event_authenticated(client: TestClient, auth_headers: dict):
    """Test logging an analytics event while authenticated."""
    response = client.post(
        "/analytics/events",
        headers=auth_headers,
        json={
            "event_type": "profile_view",
            "payload": {"username": "testuser"}
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["event_type"] == "profile_view"
    assert data["user_id"] is not None


def test_log_event_unauthenticated(client: TestClient):
    """Test logging an analytics event while unauthenticated."""
    response = client.post(
        "/analytics/events",
        json={
            "event_type": "profile_view",
            "payload": {"username": "testuser"}
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["event_type"] == "profile_view"
    assert data["user_id"] is None


def test_log_event_invalid_type(client: TestClient, auth_headers: dict):
    """Test logging an event with invalid type."""
    response = client.post(
        "/analytics/events",
        headers=auth_headers,
        json={
            "event_type": "invalid_event",
            "payload": {}
        }
    )
    assert response.status_code == 400


def test_log_event_without_payload(client: TestClient, auth_headers: dict):
    """Test logging an event without payload."""
    response = client.post(
        "/analytics/events",
        headers=auth_headers,
        json={
            "event_type": "search"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["event_type"] == "search"


def test_log_multiple_event_types(client: TestClient, auth_headers: dict):
    """Test logging different event types."""
    event_types = ["profile_view", "character_view", "realm_view", "post_view", "search"]

    for event_type in event_types:
        response = client.post(
            "/analytics/events",
            headers=auth_headers,
            json={
                "event_type": event_type,
                "payload": {"test": "data"}
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == event_type
