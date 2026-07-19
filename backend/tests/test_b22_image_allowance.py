"""Tests for B22/B23: image generation weekly allowance.

Covers:
  1. Quota service unit tests (get_quota_status, check_weekly_quota)
  2. /images/quota endpoint
  3. Allowance available → generation proceeds
  4. Allowance exhausted → 429 returned
  5. Admin bypass
  6. No deduction on controlled failure (503)
  7. Single deduction on success (not double-charged through retry)
  B23:
  8. reset_at/reset_in_seconds accuracy
  9. reset_at is null when no images exist
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers
from tests.canon_test_utils import setup_canon


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Deterministic local disk storage (env may default to R2)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


# ── Helpers ───────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0].replace(".", "_"), "password": "testpass!123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Quota Test Char", "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _lock_character(client: TestClient, token: str, cid: int) -> None:
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers=auth_headers(token),
    )
    pack_id = resp.json()["pack_id"]
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _stub_png_bytes() -> bytes:
    from app.services.stub_image_generator import generate_placeholder_png
    fp = generate_placeholder_png(label="test", sublabel="stub")
    from app.core.storage import load_image_bytes
    return load_image_bytes(fp)


def _mock_provider_succeeds() -> MagicMock:
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(return_value=_stub_png_bytes())
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    return mock


def _mock_provider_fails() -> MagicMock:
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(side_effect=RuntimeError("provider fail"))
    mock.generate_grounded_image = MagicMock(side_effect=RuntimeError("provider fail"))
    mock.generate_image = MagicMock(side_effect=RuntimeError("provider fail"))
    return mock


def _generate(client, token, cid, *, include_character=False):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json={"prompt": "A test scene", "include_character": include_character, "provider_option": "option1"},
        headers=auth_headers(token),
    )


def _make_mock_image(created_at: datetime) -> MagicMock:
    """Return a mock CharacterImage with only created_at set."""
    from app.models.character_image import CharacterImage
    img = MagicMock(spec=CharacterImage)
    img.created_at = created_at
    return img


def _db_with_images(images: list) -> MagicMock:
    """Return a mock Session whose window query returns `images`."""
    mock_db = MagicMock()
    (
        mock_db.query.return_value
        .filter.return_value
        .order_by.return_value
        .all.return_value
    ) = images
    return mock_db


# ── 1. Quota service unit tests ───────────────────────────────────────


def test_quota_service_returns_correct_fields():
    """get_quota_status returns the expected keys for a regular user."""
    from app.services.image_quota import get_quota_status
    from app.models.user import User

    now = datetime.utcnow()
    mock_user = MagicMock(spec=User)
    mock_user.email = "normal@example.com"
    # 3 images at various ages within the window
    images = [
        _make_mock_image(now - timedelta(hours=72)),
        _make_mock_image(now - timedelta(hours=48)),
        _make_mock_image(now - timedelta(hours=24)),
    ]
    mock_db = _db_with_images(images)

    from app.core.config import settings
    with patch.object(settings, "IMAGE_WEEKLY_LIMIT", 10):
        with patch.object(settings, "ADMIN_EMAILS", ""):
            status = get_quota_status(mock_user, mock_db)

    assert status["used"] == 3
    assert status["limit"] == 10
    assert status["remaining"] == 7
    assert status["unlimited"] is False
    # reset_in_seconds should be ~(7 days - 72 hours) = ~4 days, not hardcoded 7 days
    assert status["reset_in_seconds"] is not None
    assert 0 < status["reset_in_seconds"] < 7 * 24 * 3600
    assert status["reset_at"] is not None
    assert status["reset_at"].endswith("Z")


def test_quota_service_remaining_never_negative():
    """remaining is clamped to 0 when used > limit."""
    from app.services.image_quota import get_quota_status
    from app.models.user import User

    now = datetime.utcnow()
    mock_user = MagicMock(spec=User)
    mock_user.email = "overused@example.com"
    images = [_make_mock_image(now - timedelta(hours=i)) for i in range(1, 16)]
    mock_db = _db_with_images(images)

    from app.core.config import settings
    with patch.object(settings, "IMAGE_WEEKLY_LIMIT", 10):
        with patch.object(settings, "ADMIN_EMAILS", ""):
            status = get_quota_status(mock_user, mock_db)

    assert status["remaining"] == 0


def test_quota_service_admin_gets_unlimited():
    """Admin users receive unlimited=True regardless of usage."""
    from app.services.image_quota import get_quota_status
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.email = "admin@ficshon.com"
    mock_db = MagicMock()

    from app.core.config import settings
    with patch.object(settings, "ADMIN_EMAILS", "admin@ficshon.com"):
        status = get_quota_status(mock_user, mock_db)

    assert status["unlimited"] is True
    assert status["limit"] is None
    assert status["remaining"] is None
    assert status["reset_at"] is None
    mock_db.query.assert_not_called()  # no DB hit for admin


def test_check_weekly_quota_returns_none_when_available():
    """check_weekly_quota returns None (proceed) when user is under limit."""
    from app.services.image_quota import check_weekly_quota
    from app.models.user import User

    now = datetime.utcnow()
    mock_user = MagicMock(spec=User)
    mock_user.email = "normal@example.com"
    images = [_make_mock_image(now - timedelta(hours=i)) for i in range(1, 6)]  # 5 images
    mock_db = _db_with_images(images)

    from app.core.config import settings
    with patch.object(settings, "IMAGE_WEEKLY_LIMIT", 10):
        with patch.object(settings, "ADMIN_EMAILS", ""):
            result = check_weekly_quota(mock_user, mock_db)

    assert result is None


def test_check_weekly_quota_returns_429_when_exhausted():
    """check_weekly_quota returns a 429 JSONResponse when limit is reached."""
    from app.services.image_quota import check_weekly_quota
    from app.models.user import User

    now = datetime.utcnow()
    mock_user = MagicMock(spec=User)
    mock_user.email = "exhausted@example.com"
    images = [_make_mock_image(now - timedelta(hours=i)) for i in range(1, 11)]  # 10 images
    mock_db = _db_with_images(images)

    from app.core.config import settings
    with patch.object(settings, "IMAGE_WEEKLY_LIMIT", 10):
        with patch.object(settings, "ADMIN_EMAILS", ""):
            result = check_weekly_quota(mock_user, mock_db)

    assert result is not None
    assert result.status_code == 429


def test_check_weekly_quota_admin_bypass():
    """Admin bypass: check_weekly_quota returns None even at/over limit."""
    from app.services.image_quota import check_weekly_quota
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.email = "boss@ficshon.com"
    mock_db = MagicMock()

    from app.core.config import settings
    with patch.object(settings, "ADMIN_EMAILS", "boss@ficshon.com"):
        result = check_weekly_quota(mock_user, mock_db)

    assert result is None
    mock_db.query.assert_not_called()


# ── B23: reset_at accuracy ────────────────────────────────────────────


def test_quota_reset_at_null_when_no_images():
    """Fresh user with no images has reset_at=None (nothing to expire)."""
    from app.services.image_quota import get_quota_status
    from app.models.user import User

    mock_user = MagicMock(spec=User)
    mock_user.email = "fresh@example.com"
    mock_db = _db_with_images([])  # no images in window

    from app.core.config import settings
    with patch.object(settings, "IMAGE_WEEKLY_LIMIT", 10):
        with patch.object(settings, "ADMIN_EMAILS", ""):
            status = get_quota_status(mock_user, mock_db)

    assert status["reset_at"] is None
    assert status["reset_in_seconds"] is None
    assert status["used"] == 0
    assert status["remaining"] == 10


def test_quota_reset_in_seconds_reflects_oldest_image():
    """reset_in_seconds = time until the oldest image in the window expires."""
    from app.services.image_quota import get_quota_status
    from app.models.user import User

    now = datetime.utcnow()
    # Oldest image is 5 days ago; it expires in exactly 2 days from now.
    oldest = now - timedelta(days=5)
    images = [
        _make_mock_image(oldest),
        _make_mock_image(now - timedelta(days=2)),
        _make_mock_image(now - timedelta(days=1)),
    ]
    mock_user = MagicMock(spec=User)
    mock_user.email = "resetcheck@example.com"
    mock_db = _db_with_images(images)

    from app.core.config import settings
    with patch.object(settings, "IMAGE_WEEKLY_LIMIT", 10):
        with patch.object(settings, "ADMIN_EMAILS", ""):
            status = get_quota_status(mock_user, mock_db)

    # reset_in_seconds should be ≈ 2 days (within a few seconds of test execution time)
    expected_secs = int(timedelta(days=2).total_seconds())
    assert status["reset_in_seconds"] is not None
    assert abs(status["reset_in_seconds"] - expected_secs) < 5


def test_quota_429_includes_reset_at():
    """The 429 response body includes reset_at when quota is exhausted."""
    from app.services.image_quota import check_weekly_quota
    from app.models.user import User
    import json

    now = datetime.utcnow()
    mock_user = MagicMock(spec=User)
    mock_user.email = "exhausted2@example.com"
    images = [_make_mock_image(now - timedelta(hours=i)) for i in range(1, 6)]
    mock_db = _db_with_images(images)

    from app.core.config import settings
    with patch.object(settings, "IMAGE_WEEKLY_LIMIT", 5):
        with patch.object(settings, "ADMIN_EMAILS", ""):
            result = check_weekly_quota(mock_user, mock_db)

    assert result is not None
    assert result.status_code == 429
    body = json.loads(result.body)
    assert "reset_at" in body
    assert body["reset_at"] is not None
    assert body["reset_at"].endswith("Z")


# ── 2. /images/quota endpoint ─────────────────────────────────────────


def test_quota_endpoint_returns_status(client: TestClient):
    """GET /images/quota returns quota fields for authenticated user."""
    token = _register_and_login(client, "quota_ep@example.com")
    resp = client.get("/images/quota", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "used" in data
    assert "limit" in data
    assert "remaining" in data
    assert "unlimited" in data
    assert "reset_at" in data  # B23


def test_quota_endpoint_initial_state(client: TestClient):
    """Fresh user starts with used=0 and remaining==limit; reset_at is null."""
    token = _register_and_login(client, "quota_fresh@example.com")
    resp = client.get("/images/quota", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["used"] == 0
    assert data["remaining"] == data["limit"]
    assert data["unlimited"] is False
    assert data["reset_at"] is None  # B23: no images yet, nothing to expire


# ── 3. Allowance available → generation proceeds ──────────────────────


def test_generation_allowed_when_quota_available(client: TestClient, monkeypatch):
    """Generation succeeds when the user is within the weekly limit."""
    token = _register_and_login(client, "quota_ok@example.com")
    cid = _create_character(client, token)

    monkeypatch.setattr(
        "app.api.routes.image_generator.get_provider_for_option",
        lambda _opt: _mock_provider_succeeds(),
    )
    resp = _generate(client, token, cid)
    assert resp.status_code == 200


def test_generation_increments_quota_used(client: TestClient, monkeypatch):
    """Each successful generation increments the used count."""
    token = _register_and_login(client, "quota_incr@example.com")
    cid = _create_character(client, token)

    monkeypatch.setattr(
        "app.api.routes.image_generator.get_provider_for_option",
        lambda _opt: _mock_provider_succeeds(),
    )

    quota_before = client.get("/images/quota", headers=auth_headers(token)).json()
    _generate(client, token, cid)
    quota_after = client.get("/images/quota", headers=auth_headers(token)).json()

    assert quota_after["used"] == quota_before["used"] + 1
    assert quota_after["remaining"] == quota_before["remaining"] - 1
    assert quota_after["reset_at"] is not None  # B23: now has an image in window


# ── 4. Allowance exhausted → 429 ─────────────────────────────────────


def test_generation_blocked_when_quota_exhausted(client: TestClient, monkeypatch):
    """Generation returns 429 when weekly limit is reached."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 2)

    token = _register_and_login(client, "quota_block@example.com")
    cid = _create_character(client, token)

    monkeypatch.setattr(
        "app.api.routes.image_generator.get_provider_for_option",
        lambda _opt: _mock_provider_succeeds(),
    )

    # Use up the limit
    r1 = _generate(client, token, cid)
    r2 = _generate(client, token, cid)
    assert r1.status_code == 200
    assert r2.status_code == 200

    # Next request should be blocked
    r3 = _generate(client, token, cid)
    assert r3.status_code == 429
    data = r3.json()
    assert data["error"] == "quota_exceeded"
    assert "reset_at" in data  # B23


# ── 5. Admin bypass ───────────────────────────────────────────────────


def test_admin_bypass_ignores_quota(client: TestClient, monkeypatch):
    """Admin users can generate past the weekly limit."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 1)

    admin_email = "admin_bypass@ficshon.com"
    monkeypatch.setattr(settings, "ADMIN_EMAILS", admin_email)

    token = _register_and_login(client, admin_email)
    cid = _create_character(client, token)

    monkeypatch.setattr(
        "app.api.routes.image_generator.get_provider_for_option",
        lambda _opt: _mock_provider_succeeds(),
    )

    # Admin should be able to generate more than the limit
    for _ in range(3):
        resp = _generate(client, token, cid)
        assert resp.status_code == 200, resp.text


def test_admin_quota_endpoint_shows_unlimited(client: TestClient, monkeypatch):
    """Admin user's quota endpoint returns unlimited=True."""
    from app.core.config import settings
    admin_email = "admin_quota_ep@ficshon.com"
    monkeypatch.setattr(settings, "ADMIN_EMAILS", admin_email)

    token = _register_and_login(client, admin_email)
    resp = client.get("/images/quota", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["unlimited"] is True


# ── 6. No deduction on controlled failure ─────────────────────────────


def test_no_deduction_on_canon_incomplete_409(client: TestClient, monkeypatch):
    """Quota is NOT consumed when include_character=True but canon is incomplete (409)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 5)

    token = _register_and_login(client, "quota_nodeduce@example.com")
    cid = _create_character(client, token)
    # No canon set up → include_character=True must fail gracefully with 409.

    quota_before = client.get("/images/quota", headers=auth_headers(token)).json()

    resp = _generate(client, token, cid, include_character=True)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Character canon incomplete"

    quota_after = client.get("/images/quota", headers=auth_headers(token)).json()
    # Quota must be unchanged — no image was saved
    assert quota_after["used"] == quota_before["used"]
    assert quota_after["remaining"] == quota_before["remaining"]


# ── 7. Single deduction on a successful canon generation ──────────────


def test_single_deduction_on_canon_success(client: TestClient, db_session, monkeypatch):
    """A successful canon-based generation deducts exactly one from the quota."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 5)

    token = _register_and_login(client, "quota_retry@example.com")
    cid = _create_character(client, token)
    setup_canon(db_session, cid)

    monkeypatch.setattr(
        "app.api.routes.image_generator.get_provider_for_option",
        lambda _opt: _mock_provider_succeeds(),
    )

    quota_before = client.get("/images/quota", headers=auth_headers(token)).json()
    resp = _generate(client, token, cid, include_character=True)
    assert resp.status_code == 200, resp.text
    quota_after = client.get("/images/quota", headers=auth_headers(token)).json()

    # Exactly one image saved.
    assert quota_after["used"] == quota_before["used"] + 1
