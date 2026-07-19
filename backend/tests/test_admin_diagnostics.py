"""Tests for GET /api/admin/diagnostics and forgot-password hint."""
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────

_ADMIN_EMAIL = "diag-admin@ficshon.com"
_ADMIN_PASS = "adminpass123"
_USER_EMAIL = "diag-user@ficshon.com"
_USER_PASS = "userpass123"


def _register_and_login(client: TestClient, email: str, password: str, username: str) -> str:
    """Register a user and return a Bearer token."""
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Admin diagnostics: access control ────────────────────────────────────────

def test_admin_diagnostics_requires_auth(client: TestClient):
    """No token → 403 (HTTPBearer raises 403 when no credentials)."""
    resp = client.get("/api/admin/diagnostics")
    assert resp.status_code in (401, 403)


def test_admin_diagnostics_non_admin_gets_403(client: TestClient):
    """Authenticated but non-admin user → 403."""
    token = _register_and_login(client, _USER_EMAIL, _USER_PASS, "diaguser")
    resp = client.get("/api/admin/diagnostics", headers=_auth_headers(token))
    assert resp.status_code == 403
    assert "Admin" in resp.json()["detail"]


def test_admin_diagnostics_admin_gets_200(client: TestClient, monkeypatch):
    """Admin email → 200 with diagnostics payload."""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    # Patch settings cache so get_admin_emails() sees the new env var
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")

    token = _register_and_login(client, _ADMIN_EMAIL, _ADMIN_PASS, "diagadmin")
    resp = client.get("/api/admin/diagnostics", headers=_auth_headers(token))
    assert resp.status_code == 200, resp.text


# ── Admin diagnostics: payload shape ─────────────────────────────────────────

def test_admin_diagnostics_payload_shape(client: TestClient, monkeypatch):
    """Response contains all required top-level keys with correct sub-keys."""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")

    token = _register_and_login(client, _ADMIN_EMAIL, _ADMIN_PASS, "diagadmin2")
    resp = client.get("/api/admin/diagnostics", headers=_auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()

    # Top-level
    assert "ok" in data
    assert isinstance(data["ok"], bool)

    # DB section
    db = data["db"]
    assert isinstance(db["ok"], bool)
    assert "database_url_redacted" in db
    assert "alembic_head_ok" in db
    assert isinstance(db["alembic_head_ok"], bool)
    # credentials must not appear in redacted URL
    assert "@" not in db["database_url_redacted"]

    # StoryLab section
    sl = data["storylab"]
    assert "provider" in sl
    assert "daily_limit" in sl
    assert isinstance(sl["daily_limit"], int)
    assert "openrouter_key_present" in sl
    assert isinstance(sl["openrouter_key_present"], bool)
    assert "models" in sl
    assert {"sfw", "fade", "sensual"} == set(sl["models"].keys())

    # Images section
    img = data["images"]
    assert "provider" in img
    assert "weekly_limit" in img
    assert isinstance(img["weekly_limit"], int)
    assert "openai_key_present" in img
    assert isinstance(img["openai_key_present"], bool)
    assert "fal_key_present" in img
    assert isinstance(img["fal_key_present"], bool)
    assert "model" in img

    # Email section
    email = data["email"]
    assert "smtp_configured" in email
    assert isinstance(email["smtp_configured"], bool)
    assert "from_email" in email
    assert "port" in email

    # Safety section — all capabilities are present in this codebase
    safety = data["safety"]
    assert safety["reports_enabled"] is True
    assert safety["blocks_enabled"] is True
    assert safety["ban_enabled"] is True


def test_admin_diagnostics_storylab_provider_mirrors_env(client: TestClient, monkeypatch):
    """storylab.provider in diagnostics matches whatever STORYLAB_PROVIDER is set to."""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")
    # Patch the live settings object to simulate openrouter being configured
    monkeypatch.setattr(cfg_module.settings, "STORYLAB_PROVIDER", "openrouter")

    token = _register_and_login(client, _ADMIN_EMAIL, _ADMIN_PASS, "diagadmin4")
    resp = client.get("/api/admin/diagnostics", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["storylab"]["provider"] == "openrouter"


def test_admin_diagnostics_no_credentials_in_url(client: TestClient, monkeypatch):
    """Redacted DB URL never contains credentials."""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")

    token = _register_and_login(client, _ADMIN_EMAIL, _ADMIN_PASS, "diagadmin3")
    resp = client.get("/api/admin/diagnostics", headers=_auth_headers(token))
    assert resp.status_code == 200
    url_redacted = resp.json()["db"]["database_url_redacted"]
    assert "@" not in url_redacted
    assert "password" not in url_redacted.lower()


# ── Forgot-password hint ──────────────────────────────────────────────────────

def test_forgot_password_response_has_hint(client: TestClient):
    """forgot-password always returns ok, message, and hint — regardless of email existence."""
    resp = client.post(
        "/auth/forgot-password",
        json={"email": "definitely-not-registered@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("ok") is True
    assert "message" in data
    assert "hint" in data
    assert isinstance(data["hint"], str)
    assert len(data["hint"]) > 0


def test_forgot_password_hint_does_not_leak_existence(client: TestClient):
    """Response for non-existent and existing email must have same shape."""
    # Non-existent
    resp_no = client.post(
        "/auth/forgot-password",
        json={"email": "ghost-diag@example.com"},
    )
    # Existing (register first)
    client.post(
        "/auth/register",
        json={"email": "real-diag@example.com", "username": "realdiagusr", "password": "pass1234567"},
    )
    resp_yes = client.post(
        "/auth/forgot-password",
        json={"email": "real-diag@example.com"},
    )
    assert resp_no.status_code == resp_yes.status_code == 200
    # Both include hint
    assert resp_no.json().get("hint") is not None
    assert resp_yes.json().get("hint") is not None
    # Neither leaks the fact of existence via message differences
    assert resp_no.json()["message"] == resp_yes.json()["message"]
    # reset_url is NOT in the non-dev response for non-admin
    assert "reset_url" not in resp_no.json() or resp_no.json().get("reset_url") is None
