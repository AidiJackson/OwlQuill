"""Tests for identity-pack per-character 24-hour rate limit.

Rules under test:
  - Regular users: max IDENTITY_PACK_DAILY_LIMIT packs per character per 24 h
  - Admins: unlimited
  - Dry-run calls are not counted
  - accept/lock does not add to the generation count
  - Different characters have independent limits
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from tests.conftest import auth_headers


# ── Helpers ────────────────────────────────────────────────────────────

def _register_and_login(client: TestClient, email: str) -> str:
    username = email.split("@")[0].replace(".", "_").replace("+", "_")
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass!123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str, name: str = "RLTestChar") -> int:
    resp = client.post(
        "/characters/",
        json={"name": name, "visibility": "public"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _generate(client: TestClient, token: str, cid: int) -> "Response":
    return client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers=auth_headers(token),
    )


def _accept(client: TestClient, token: str, cid: int, pack_id: str):
    return client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers=auth_headers(token),
    )


# ── Service-level unit tests ──────────────────────────────────────────


def _make_mock_image(pack_role: str | None, created_at: datetime | None = None):
    """Build a mock CharacterImage for unit tests."""
    from app.models.character_image import CharacterImage
    img = MagicMock(spec=CharacterImage)
    img.created_at = created_at or datetime.utcnow()
    img.metadata_json = {"pack_role": pack_role} if pack_role else {"source": "other"}
    return img


def _db_returning(images: list) -> MagicMock:
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = images
    return mock_db


def _mock_ordinary_user(email: str) -> MagicMock:
    """Build a mock User that is genuinely an ordinary creator.

    ``MagicMock(spec=User)`` auto-creates every User attribute as a truthy Mock,
    so a mock that stubs only ``email`` silently claims ``is_admin`` and
    ``is_seeder``. That was harmless while the quota exemption read ADMIN_EMAILS
    alone, and became wrong the moment it read the account flags too. Stub the
    flags explicitly so these tests model the account they describe.
    """
    from app.models.user import User
    user = MagicMock(spec=User)
    user.email = email
    user.is_admin = False
    user.is_seeder = False
    return user


class TestIdentityPackQuotaService:
    """Unit tests for the quota service layer (mock DB)."""

    def test_no_generations_returns_full_remaining(self):
        from app.services.image_quota import get_identity_pack_quota_status

        mock_user = _mock_ordinary_user("fresh@example.com")
        mock_db = _db_returning([])

        from app.core.config import settings
        with patch.object(settings, "IDENTITY_PACK_DAILY_LIMIT", 10):
            with patch.object(settings, "ADMIN_EMAILS", ""):
                status = get_identity_pack_quota_status(1, mock_user, mock_db)

        assert status["used"] == 0
        assert status["limit"] == 10
        assert status["remaining"] == 10
        assert status["unlimited"] is False

    def test_generation_attempts_counted_correctly(self):
        """Each anchor_front image counts as one generation attempt."""
        from app.services.image_quota import get_identity_pack_quota_status

        mock_user = _mock_ordinary_user("regular@example.com")
        images = [
            _make_mock_image("anchor_front"),   # generation 1
            _make_mock_image("anchor_three_quarter"),  # same generation 1
            _make_mock_image("anchor_torso"),   # same generation 1
            _make_mock_image("anchor_full_body"),  # same generation 1
            _make_mock_image("anchor_front"),   # generation 2
            _make_mock_image("anchor_three_quarter"),
            _make_mock_image("anchor_torso"),
            _make_mock_image("anchor_full_body"),
        ]
        mock_db = _db_returning(images)

        from app.core.config import settings
        with patch.object(settings, "IDENTITY_PACK_DAILY_LIMIT", 10):
            with patch.object(settings, "ADMIN_EMAILS", ""):
                status = get_identity_pack_quota_status(1, mock_user, mock_db)

        assert status["used"] == 2
        assert status["remaining"] == 8

    def test_admin_returns_unlimited(self):
        from app.services.image_quota import get_identity_pack_quota_status
        from app.models.user import User

        mock_user = MagicMock(spec=User)
        mock_user.email = "admin@ficshon.com"
        mock_db = MagicMock()

        from app.core.config import settings
        with patch.object(settings, "ADMIN_EMAILS", "admin@ficshon.com"):
            status = get_identity_pack_quota_status(1, mock_user, mock_db)

        assert status["unlimited"] is True
        assert status["limit"] is None
        assert status["remaining"] is None
        mock_db.query.assert_not_called()

    def test_check_returns_none_when_under_limit(self):
        from app.services.image_quota import check_identity_pack_quota

        mock_user = _mock_ordinary_user("under@example.com")
        images = [_make_mock_image("anchor_front")] * 3  # 3 used of 5
        mock_db = _db_returning(images)

        from app.core.config import settings
        with patch.object(settings, "IDENTITY_PACK_DAILY_LIMIT", 5):
            with patch.object(settings, "ADMIN_EMAILS", ""):
                result = check_identity_pack_quota(1, mock_user, mock_db)

        assert result is None

    def test_check_returns_429_at_limit(self):
        from app.services.image_quota import check_identity_pack_quota

        mock_user = _mock_ordinary_user("exhausted@example.com")
        images = [_make_mock_image("anchor_front")] * 5  # at limit
        mock_db = _db_returning(images)

        from app.core.config import settings
        with patch.object(settings, "IDENTITY_PACK_DAILY_LIMIT", 5):
            with patch.object(settings, "ADMIN_EMAILS", ""):
                result = check_identity_pack_quota(1, mock_user, mock_db)

        assert result is not None
        assert result.status_code == 429
        body = json.loads(result.body)
        assert body["error"] == "identity_pack_rate_limited"
        assert body["limit"] == 5
        assert body["remaining"] == 0
        assert body["used"] == 5
        assert "window_hours" in body

    def test_check_admin_bypass(self):
        from app.services.image_quota import check_identity_pack_quota
        from app.models.user import User

        mock_user = MagicMock(spec=User)
        mock_user.email = "boss@ficshon.com"
        mock_db = MagicMock()

        from app.core.config import settings
        with patch.object(settings, "ADMIN_EMAILS", "boss@ficshon.com"):
            result = check_identity_pack_quota(1, mock_user, mock_db)

        assert result is None
        mock_db.query.assert_not_called()

    def test_accept_images_not_double_counted(self):
        """Accepted pack images keep pack_role in metadata — count should still be 1."""
        from app.services.image_quota import get_identity_pack_quota_status

        mock_user = _mock_ordinary_user("accepted@example.com")

        # Simulate: one generation attempt, all 4 images promoted via accept.
        # After accept, kind changes but metadata_json.pack_role is preserved.
        accepted_anchor_front = _make_mock_image("anchor_front")
        other_roles = [
            _make_mock_image("anchor_three_quarter"),
            _make_mock_image("anchor_torso"),
            _make_mock_image("anchor_full_body"),
        ]
        mock_db = _db_returning([accepted_anchor_front] + other_roles)

        from app.core.config import settings
        with patch.object(settings, "IDENTITY_PACK_DAILY_LIMIT", 5):
            with patch.object(settings, "ADMIN_EMAILS", ""):
                status = get_identity_pack_quota_status(1, mock_user, mock_db)

        assert status["used"] == 1, "one generation attempt, regardless of accept state"
        assert status["remaining"] == 4

    def test_non_pack_images_not_counted(self):
        """Moment, sketch, and body-slot images must not count toward the pack limit."""
        from app.services.image_quota import get_identity_pack_quota_status
        from app.models.character_image import CharacterImage

        mock_user = _mock_ordinary_user("mixed@example.com")

        def _img(meta):
            m = MagicMock(spec=CharacterImage)
            m.created_at = datetime.utcnow()
            m.metadata_json = meta
            return m

        images = [
            _img({"anchor_version": 1, "request": {}}),    # moment image
            _img({"style": "pencil", "is_temp": False}),   # sketch
            _img({"source": "admin_canon_import"}),         # body slot
            _img(None),                                     # no metadata at all
            _img({"pack_role": "anchor_front"}),            # identity pack — counts
        ]
        mock_db = _db_returning(images)

        from app.core.config import settings
        with patch.object(settings, "IDENTITY_PACK_DAILY_LIMIT", 5):
            with patch.object(settings, "ADMIN_EMAILS", ""):
                status = get_identity_pack_quota_status(1, mock_user, mock_db)

        assert status["used"] == 1, "only the identity-pack anchor_front should be counted"


# ── Integration tests (real HTTP, stub provider) ──────────────────────


class TestIdentityPackRateLimitIntegration:
    """Integration tests against the live FastAPI routes using the stub provider."""

    def test_generation_allowed_under_limit(self, client: TestClient, monkeypatch):
        """Requests within the limit return 200."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "IDENTITY_PACK_DAILY_LIMIT", 3)

        token = _register_and_login(client, "rl_under@test.com")
        cid = _create_character(client, token, "UnderLimitChar")

        for i in range(3):
            resp = _generate(client, token, cid)
            assert resp.status_code == 200, f"attempt {i+1} failed: {resp.text}"

    def test_generation_blocked_when_limit_reached(self, client: TestClient, monkeypatch):
        """The request after the limit returns 429 with correct body."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "IDENTITY_PACK_DAILY_LIMIT", 2)

        token = _register_and_login(client, "rl_limit@test.com")
        cid = _create_character(client, token, "LimitChar")

        r1 = _generate(client, token, cid)
        r2 = _generate(client, token, cid)
        assert r1.status_code == 200
        assert r2.status_code == 200

        r3 = _generate(client, token, cid)
        assert r3.status_code == 429, r3.text
        body = r3.json()
        assert body["error"] == "identity_pack_rate_limited"
        assert body["limit"] == 2
        assert body["remaining"] == 0
        assert body["used"] == 2

    def test_admin_bypasses_limit(self, client: TestClient, monkeypatch):
        """Admin users are never blocked regardless of generation count."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "IDENTITY_PACK_DAILY_LIMIT", 1)
        admin_email = "admin_rl@ficshon.com"
        monkeypatch.setattr(settings, "ADMIN_EMAILS", admin_email)

        token = _register_and_login(client, admin_email)
        cid = _create_character(client, token, "AdminRLChar")

        for i in range(3):
            resp = _generate(client, token, cid)
            assert resp.status_code == 200, f"admin blocked on attempt {i+1}: {resp.text}"

    def test_accept_does_not_count_toward_limit(self, client: TestClient, monkeypatch):
        """Accepting a pack does not register as an additional generation attempt."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "IDENTITY_PACK_DAILY_LIMIT", 2)

        token = _register_and_login(client, "rl_accept@test.com")
        cid = _create_character(client, token, "AcceptChar")

        # Generate and accept the pack (locks the character)
        r1 = _generate(client, token, cid)
        assert r1.status_code == 200
        pack_id = r1.json()["pack_id"]

        racc = _accept(client, token, cid, pack_id)
        assert racc.status_code == 200, racc.text
        # Character is now locked — the 409 (locked) must come before any 429 (rate limited)
        # when someone tries to generate again for this character.
        r2 = _generate(client, token, cid)
        # Must be 409 (locked), not 429 (rate limited) — proves accept didn't burn quota slots.
        assert r2.status_code == 409, (
            f"Expected 409 (already locked), got {r2.status_code}: {r2.text}"
        )

    def test_different_characters_have_independent_limits(self, client: TestClient, monkeypatch):
        """Exhausting the limit on character A does not block character B."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "IDENTITY_PACK_DAILY_LIMIT", 1)

        # Beta gate limits 1 character per account — use separate users.
        token_a = _register_and_login(client, "rl_chars_a@test.com")
        token_b = _register_and_login(client, "rl_chars_b@test.com")
        cid_a = _create_character(client, token_a, "CharA")
        cid_b = _create_character(client, token_b, "CharB")

        # Exhaust char A's limit
        ra = _generate(client, token_a, cid_a)
        assert ra.status_code == 200
        blocked = _generate(client, token_a, cid_a)
        assert blocked.status_code == 429

        # Char B must still have its own fresh limit
        rb = _generate(client, token_b, cid_b)
        assert rb.status_code == 200, (
            f"char B should have independent limit but got {rb.status_code}: {rb.text}"
        )

    def test_dry_run_not_counted(self, client: TestClient, monkeypatch):
        """dry_run=true calls are not counted toward the rate limit."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "IDENTITY_PACK_DAILY_LIMIT", 1)

        token = _register_and_login(client, "rl_dryrun@test.com")
        cid = _create_character(client, token, "DryRunChar")

        # Exhaust limit with one real generation
        resp = _generate(client, token, cid)
        assert resp.status_code == 200

        # Dry-run should not be blocked (it compiles prompts only)
        r_dry = client.post(
            f"/characters/{cid}/identity-pack/generate",
            params={"dry_run": "true"},
            json={},
            headers=auth_headers(token),
        )
        assert r_dry.status_code == 200, (
            f"dry_run must not be rate-limited: {r_dry.text}"
        )
        assert r_dry.json()["dry_run"] is True
