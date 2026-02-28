"""Tests for image library generation (Gate 4A).

All tests run with IMAGE_PROVIDER=stub (set in conftest.py) so no network
calls are made. Provider-config error tests use unittest.mock to temporarily
override the settings singleton.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(client: TestClient, email: str, username: str) -> dict:
    r = client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "Password123!"},
    )
    assert r.status_code == 201, r.json()
    r2 = client.post("/auth/login", json={"email": email, "password": "Password123!"})
    assert r2.status_code == 200, r2.json()
    return {"id": r.json()["id"], "token": r2.json()["access_token"]}


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_character(client: TestClient, token: str, name: str = "TestChar") -> int:
    r = client.post("/characters/", json={"name": name}, headers=_h(token))
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _seed_library_images(
    db_session,
    character_id: int,
    count: int,
    *,
    days_ago: float = 0,
) -> None:
    """Directly insert library CharacterImage rows (no provider call)."""
    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )

    ts = datetime.utcnow() - timedelta(days=days_ago)
    for i in range(count):
        img = CharacterImage(
            character_id=character_id,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            provider="stub",
            file_path=f"static/generated/seed_{days_ago}_{i}.png",
            metadata_json={"library": True, "prompt": f"seed {i}"},
            created_at=ts,
        )
        db_session.add(img)
    db_session.commit()


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_generate_requires_auth(client: TestClient):
    """POST /images/generate without a token returns 401 or 403."""
    r = client.post("/images/generate", json={"prompt": "a red dragon"})
    assert r.status_code in (401, 403)


def test_list_requires_auth(client: TestClient):
    """GET /images/ without a token returns 401 or 403."""
    r = client.get("/images/")
    assert r.status_code in (401, 403)


# ── Stub provider (IMAGE_PROVIDER=stub set in conftest) ───────────────────────

def test_generate_stub_returns_image(client: TestClient):
    """With stub provider, generation succeeds and returns a local static URL."""
    user = _register(client, "stub@t.com", "stub_user")
    _create_character(client, user["token"])

    r = client.post(
        "/images/generate",
        json={"prompt": "a red dragon breathing fire"},
        headers=_h(user["token"]),
    )
    assert r.status_code == 200, r.json()
    data = r.json()
    assert data["provider"] == "stub"
    assert data["url"].startswith("/static/generated/")
    assert data["metadata_json"]["library"] is True
    assert data["metadata_json"]["prompt"] == "a red dragon breathing fire"


def test_generate_no_character_returns_400(client: TestClient):
    """Generating without any character returns 400."""
    user = _register(client, "nochar@t.com", "nochar_user")

    r = client.post(
        "/images/generate",
        json={"prompt": "test prompt"},
        headers=_h(user["token"]),
    )
    assert r.status_code == 400


def test_generate_image_appears_in_list(client: TestClient):
    """After generating, the image appears in GET /images/."""
    user = _register(client, "list@t.com", "list_user")
    _create_character(client, user["token"])

    client.post(
        "/images/generate",
        json={"prompt": "misty forest at dawn"},
        headers=_h(user["token"]),
    )

    r = client.get("/images/", headers=_h(user["token"]))
    assert r.status_code == 200
    urls = [img["url"] for img in r.json()]
    assert any("/static/generated/" in u for u in urls)


# ── Weekly quota ──────────────────────────────────────────────────────────────

def test_weekly_quota_enforced(client: TestClient, db_session):
    """Once the weekly limit is reached, further requests return 429."""
    from app.core.config import settings
    from app.models.character import Character

    user = _register(client, "quota@t.com", "quota_user")
    char_id = _create_character(client, user["token"])

    # Seed the DB directly with exactly `limit` library images (current week)
    limit = settings.IMAGE_WEEKLY_LIMIT
    _seed_library_images(db_session, char_id, limit, days_ago=0)

    r = client.post(
        "/images/generate",
        json={"prompt": "one too many"},
        headers=_h(user["token"]),
    )
    assert r.status_code == 429, r.json()
    detail = r.json()["detail"]
    assert detail["error"] == "quota_exceeded"
    assert detail["limit"] == limit
    assert detail["used"] >= limit
    assert "hint" in detail


def test_images_outside_7_day_window_not_counted(client: TestClient, db_session):
    """Images older than 7 days do not count toward the weekly quota."""
    from app.core.config import settings

    user = _register(client, "old@t.com", "old_user")
    char_id = _create_character(client, user["token"])

    limit = settings.IMAGE_WEEKLY_LIMIT
    # Seed `limit` images that are 8 days old — outside the rolling window
    _seed_library_images(db_session, char_id, limit, days_ago=8)

    # Current window is empty, so this generation must succeed
    r = client.post(
        "/images/generate",
        json={"prompt": "fresh start"},
        headers=_h(user["token"]),
    )
    assert r.status_code == 200, r.json()
    assert r.json()["provider"] == "stub"


def test_quota_resets_after_window(client: TestClient, db_session):
    """Mix of old (8 d) and recent (0 d) images: only recent ones count."""
    from app.core.config import settings

    user = _register(client, "mixed@t.com", "mixed_user")
    char_id = _create_character(client, user["token"])

    limit = settings.IMAGE_WEEKLY_LIMIT
    # Half the quota used in old window, half in new
    half = limit // 2
    _seed_library_images(db_session, char_id, half, days_ago=8)
    _seed_library_images(db_session, char_id, half, days_ago=1)

    # Still under limit — one more should succeed
    r = client.post(
        "/images/generate",
        json={"prompt": "still have quota"},
        headers=_h(user["token"]),
    )
    assert r.status_code == 200, r.json()


# ── Provider config errors ────────────────────────────────────────────────────

def test_openai_provider_no_key_returns_503(client: TestClient):
    """When IMAGE_PROVIDER=openai but OPENAI_API_KEY is absent, return 503 JSON error."""
    from app.core.config import settings as app_settings

    user = _register(client, "nokey@t.com", "nokey_user")
    _create_character(client, user["token"])

    with (
        patch.object(app_settings, "IMAGE_PROVIDER", "openai"),
        patch.object(app_settings, "OPENAI_API_KEY", None),
        patch.object(app_settings, "FAL_KEY", None),
    ):
        r = client.post(
            "/images/generate",
            json={"prompt": "will not reach provider"},
            headers=_h(user["token"]),
        )

    assert r.status_code == 503, r.json()
    detail = r.json()["detail"]
    assert detail["error"] == "image_failed"
    assert detail["provider"] == "openai"
    assert "model" in detail
    assert "hint" in detail
    assert "OPENAI_API_KEY" in detail["hint"]


def test_503_response_shape(client: TestClient):
    """Verify the 503 JSON shape exactly matches the documented error contract."""
    from app.core.config import settings as app_settings

    user = _register(client, "shape@t.com", "shape_user")
    _create_character(client, user["token"])

    with (
        patch.object(app_settings, "IMAGE_PROVIDER", "openai"),
        patch.object(app_settings, "OPENAI_API_KEY", None),
        patch.object(app_settings, "FAL_KEY", None),
    ):
        r = client.post(
            "/images/generate",
            json={"prompt": "shape test"},
            headers=_h(user["token"]),
        )

    detail = r.json()["detail"]
    # All required keys must be present
    for key in ("error", "detail", "hint", "provider", "model"):
        assert key in detail, f"Missing key: {key}"
    assert detail["error"] == "image_failed"
    # model must be a non-empty string
    assert isinstance(detail["model"], str) and detail["model"]
