"""Tests for the reports + admin ban system (Gate 3A)."""
from fastapi.testclient import TestClient

from tests.conftest import auth_headers


def _register_and_login(client: TestClient, email: str, username: str) -> str:
    """Register + login and return bearer token."""
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass!123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _make_admin(db_session, email: str) -> None:
    """Directly set is_admin=True for the given user in the test DB."""
    from app.models.user import User as UserModel
    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == email).first()
    assert user is not None, f"User {email!r} not found in DB"
    user.is_admin = True
    db_session.commit()


# ── Report submission ─────────────────────────────────────────────────────────

def test_user_can_submit_report(authed_client):
    """Authenticated user can POST /api/reports and it persists with status=open."""
    resp = authed_client.post(
        "/api/reports",
        json={"target_type": "user", "target_id": "999", "reason": "spam"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "open"
    assert data["target_type"] == "user"
    assert data["target_id"] == "999"
    assert data["reason"] == "spam"
    assert "id" in data
    assert isinstance(data["id"], int)


def test_report_with_detail(authed_client):
    """Report can carry an optional detail field."""
    resp = authed_client.post(
        "/api/reports",
        json={
            "target_type": "post",
            "target_id": "42",
            "reason": "harassment",
            "detail": "This post contains targeted harassment.",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["detail"] == "This post contains targeted harassment."


def test_unauthenticated_cannot_report(client):
    """Unauthenticated request to /api/reports is rejected."""
    resp = client.post(
        "/api/reports",
        json={"target_type": "user", "target_id": "1", "reason": "spam"},
    )
    assert resp.status_code in (401, 403)


# ── Ban enforcement ───────────────────────────────────────────────────────────

def test_banned_user_cannot_access_protected_route(client, db_session):
    """Banned user gets 403 with error=banned on any auth-gated route."""
    from app.models.user import User as UserModel

    token = _register_and_login(client, "banned@example.com", "banneduser")

    # Ban the user directly in the DB
    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == "banned@example.com").first()
    user.is_banned = True
    user.ban_reason = "violation of terms"
    db_session.commit()

    resp = client.get("/api/characters", headers=auth_headers(token))
    assert resp.status_code == 403, resp.text
    data = resp.json()
    assert data["detail"]["error"] == "banned"
    assert "violation of terms" in data["detail"]["detail"]


def test_unbanned_user_can_access_again(client, db_session):
    """After is_banned is cleared, the user can access protected routes again."""
    from app.models.user import User as UserModel

    token = _register_and_login(client, "unbanned@example.com", "unbanneduser")

    # Ban then unban
    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == "unbanned@example.com").first()
    user.is_banned = True
    db_session.commit()

    assert client.get("/api/characters", headers=auth_headers(token)).status_code == 403

    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == "unbanned@example.com").first()
    user.is_banned = False
    user.ban_reason = None
    db_session.commit()

    assert client.get("/api/characters", headers=auth_headers(token)).status_code == 200


# ── Admin: list + resolve reports ────────────────────────────────────────────

def test_admin_can_list_reports(client, db_session):
    """Admin can GET /api/admin/reports and see submitted reports."""
    user_token = _register_and_login(client, "reporter2@example.com", "reporter2")
    client.post(
        "/api/reports",
        json={"target_type": "post", "target_id": "10", "reason": "spam"},
        headers=auth_headers(user_token),
    )

    admin_token = _register_and_login(client, "admin2@example.com", "admin2user")
    _make_admin(db_session, "admin2@example.com")

    resp = client.get("/api/admin/reports?status=open", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list) and len(data) >= 1
    assert data[0]["status"] == "open"


def test_admin_can_resolve_report(client, db_session):
    """Admin can POST /api/admin/reports/{id}/resolve to close a report."""
    user_token = _register_and_login(client, "reporter3@example.com", "reporter3")
    report_resp = client.post(
        "/api/reports",
        json={"target_type": "comment", "target_id": "7", "reason": "harassment"},
        headers=auth_headers(user_token),
    )
    report_id = report_resp.json()["id"]

    admin_token = _register_and_login(client, "admin3@example.com", "admin3user")
    _make_admin(db_session, "admin3@example.com")

    resp = client.post(
        f"/api/admin/reports/{report_id}/resolve",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["resolved_by_id"] is not None
    assert data["resolved_at"] is not None


# ── Admin: ban / unban ────────────────────────────────────────────────────────

def test_admin_can_ban_and_unban_user(client, db_session):
    """Admin can ban a user via /api/admin/ban/{id}, then unban via /api/admin/unban/{id}."""
    from app.models.user import User as UserModel

    target_token = _register_and_login(client, "target@example.com", "targetuser")

    admin_token = _register_and_login(client, "admin4@example.com", "admin4user")
    _make_admin(db_session, "admin4@example.com")

    # Look up target user id
    db_session.expire_all()
    target_user = db_session.query(UserModel).filter(UserModel.email == "target@example.com").first()
    target_id = target_user.id

    # Ban
    ban_resp = client.post(
        f"/api/admin/ban/{target_id}",
        json={"reason": "spamming"},
        headers=auth_headers(admin_token),
    )
    assert ban_resp.status_code == 200, ban_resp.text
    assert ban_resp.json()["is_banned"] is True

    # Banned user is blocked
    assert client.get("/api/characters", headers=auth_headers(target_token)).status_code == 403

    # Unban
    unban_resp = client.post(
        f"/api/admin/unban/{target_id}",
        headers=auth_headers(admin_token),
    )
    assert unban_resp.status_code == 200, unban_resp.text
    assert unban_resp.json()["is_banned"] is False

    # User can access again
    assert client.get("/api/characters", headers=auth_headers(target_token)).status_code == 200


# ── Admin guard: non-admin is rejected ───────────────────────────────────────

def test_non_admin_cannot_list_reports(authed_client):
    """Non-admin user gets 403 on GET /api/admin/reports."""
    resp = authed_client.get("/api/admin/reports")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "forbidden"


def test_non_admin_cannot_ban(authed_client):
    """Non-admin user gets 403 on POST /api/admin/ban/{id}."""
    resp = authed_client.post("/api/admin/ban/999", json={})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["error"] == "forbidden"
