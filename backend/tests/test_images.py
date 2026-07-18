"""Tests for image library endpoints — weekly quota + admin bypass."""
from fastapi.testclient import TestClient

from tests.conftest import get_auth_token

_IMAGE_BODY = {"prompt": "A twilight forest clearing."}


def _create_character(client, token: str) -> int:
    """Create a minimal character and return its id."""
    resp = client.post(
        "/characters/",
        json={"name": "Quota Test Character", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Character creation failed: {resp.text}"
    return resp.json()["id"]


# ── Weekly quota enforcement ──────────────────────────────────────────────────

def test_image_weekly_limit_enforced(authed_client, client):
    """Non-admin user is blocked with 429 after IMAGE_WEEKLY_LIMIT generations."""
    from app.core.config import settings as app_settings

    limit = app_settings.IMAGE_WEEKLY_LIMIT
    token = get_auth_token(client)

    # Create a character so /images/generate can pick one
    _create_character(client, token)

    # Generate up to the limit — must all succeed
    for i in range(limit):
        resp = authed_client.post("/api/images/generate", json=_IMAGE_BODY)
        assert resp.status_code == 200, f"Image {i + 1} blocked unexpectedly: {resp.text}"

    # One more — must be blocked
    resp = authed_client.post("/api/images/generate", json=_IMAGE_BODY)
    assert resp.status_code == 429, resp.text
    data = resp.json()
    assert data["error"] == "quota_exceeded"
    assert data["limit"] == limit
    assert "reset_in_seconds" in data
    assert isinstance(data["reset_in_seconds"], int) and data["reset_in_seconds"] > 0


# ── Admin unlimited bypass ────────────────────────────────────────────────────

def test_image_admin_unlimited(authed_client, client, monkeypatch):
    """Admin user (email in ADMIN_EMAILS) bypasses the weekly quota entirely."""
    from app.core.config import settings as app_settings

    # Promote the default test user (user@test.com) to admin via settings patch.
    # settings is a shared singleton — patch it directly (the images route no
    # longer re-imports it at module level).
    monkeypatch.setattr(app_settings, "ADMIN_EMAILS", "user@test.com")

    limit = app_settings.IMAGE_WEEKLY_LIMIT
    over_limit = limit + 3  # generate clearly beyond the standard cap

    token = get_auth_token(client)
    _create_character(client, token)

    for i in range(over_limit):
        resp = authed_client.post("/api/images/generate", json=_IMAGE_BODY)
        assert resp.status_code == 200, (
            f"Admin image {i + 1} was unexpectedly blocked at quota: {resp.text}"
        )
