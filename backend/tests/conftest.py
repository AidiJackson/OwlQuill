"""Pytest configuration and fixtures."""
import os

# Set test environment variables BEFORE any app imports
# This ensures Settings() sees these values when instantiated at import time
os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"
os.environ["DEBUG"] = "true"  # force override — Replit sets DEBUG=False in shell env
# Ensure tests use stub image generator, never the real OpenAI or fal API
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("FAL_KEY", None)
# Force deterministic stub provider for all StoryLab tests — never call live OpenRouter
os.environ["STORYLAB_PROVIDER"] = "stub"
os.environ.pop("OPENROUTER_API_KEY", None)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Fix bcrypt/passlib compatibility issue (bcrypt 4.0+ requires explicit truncation)
# Must be done before passlib is imported
import bcrypt
_original_hashpw = bcrypt.hashpw
def _patched_hashpw(password, salt):
    # Truncate password to 72 bytes as required by bcrypt
    if isinstance(password, bytes) and len(password) > 72:
        password = password[:72]
    return _original_hashpw(password, salt)
bcrypt.hashpw = _patched_hashpw

from app.core.database import Base, get_db
from app.main import app
from app.api.routes.auth import limiter

# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client."""
    app.dependency_overrides[get_db] = override_get_db
    # Disable rate limiting during tests by enabling the limiter's enabled flag to False
    limiter.enabled = False
    with TestClient(app) as test_client:
        yield test_client
    # Re-enable rate limiting after tests
    limiter.enabled = True
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def authed_client(client):
    """TestClient wrapper that auto-injects auth headers for a default test user.

    Drop-in replacement for ``client`` in tests that require authentication.
    Exposes .get/.post/.delete/.put/.patch with the Bearer token pre-injected.
    """
    token = get_auth_token(client)
    hdrs = {"Authorization": f"Bearer {token}"}

    class _AuthedClient:
        def get(self, url, **kwargs):
            kw_headers = dict(kwargs.pop("headers", {}) or {})
            kw_headers.update(hdrs)
            return client.get(url, headers=kw_headers, **kwargs)

        def post(self, url, **kwargs):
            kw_headers = dict(kwargs.pop("headers", {}) or {})
            kw_headers.update(hdrs)
            return client.post(url, headers=kw_headers, **kwargs)

        def delete(self, url, **kwargs):
            kw_headers = dict(kwargs.pop("headers", {}) or {})
            kw_headers.update(hdrs)
            return client.delete(url, headers=kw_headers, **kwargs)

        def put(self, url, **kwargs):
            kw_headers = dict(kwargs.pop("headers", {}) or {})
            kw_headers.update(hdrs)
            return client.put(url, headers=kw_headers, **kwargs)

        def patch(self, url, **kwargs):
            kw_headers = dict(kwargs.pop("headers", {}) or {})
            kw_headers.update(hdrs)
            return client.patch(url, headers=kw_headers, **kwargs)

        @property
        def _raw(self):
            return client

    return _AuthedClient()


def get_auth_token(client, email: str = "user@test.com", username: str = "testuser") -> str:
    """Register a user (if needed) and return their Bearer JWT token.

    Idempotent — if the email already exists the registration 400 is ignored
    and login proceeds normally.  Suitable for use inside test functions that
    already have a ``client`` fixture.
    """
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass!123"},
    )
    resp = client.post(
        "/auth/login",
        json={"email": email, "password": "testpass!123"},
    )
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    """Return Authorization header dict for a token."""
    return {"Authorization": f"Bearer {token}"}
