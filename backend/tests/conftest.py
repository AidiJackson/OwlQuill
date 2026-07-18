"""Pytest configuration and fixtures."""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

# Set test environment variables BEFORE any app imports
# This ensures Settings() sees these values when instantiated at import time
os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"
os.environ["DEBUG"] = "true"  # force override — Replit sets DEBUG=False in shell env
# Ensure tests use stub image generator, never the real OpenAI or fal API
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("FAL_KEY", None)
# Strip every other live image/GPU provider credential too (Sprint 34).
# Identity-pack generation degrades to the stub provider when the configured
# provider has no API key — with GOOGLE_AI_API_KEY present, character-locking
# tests were silently calling the real Gemini image API on every run.
os.environ.pop("GOOGLE_AI_API_KEY", None)
os.environ.pop("TOGETHER_API_KEY", None)
os.environ.pop("REPLICATE_API_TOKEN", None)
os.environ.pop("RUNPOD_API_KEY", None)
# Force deterministic stub provider for all StoryLab tests — never call live OpenRouter
os.environ["STORYLAB_PROVIDER"] = "stub"
os.environ.pop("OPENROUTER_API_KEY", None)
# Disable invite-code gate in tests — no invite codes are seeded in the test DB
os.environ["BETA_INVITE_REQUIRED"] = "false"

# --- Production-infrastructure isolation (Sprint 34) ---
# Object storage must be OFF for the whole suite, and the production R2
# credentials must be absent so any code path that still tries to upload
# fails loudly (KeyError) instead of silently writing to the live bucket.
# Tests that exercise R2 plumbing set their own stub values.
os.environ["USE_OBJECT_STORAGE"] = "false"
for _var in (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_URL",
):
    os.environ.pop(_var, None)

# The app engine (app.core.database, used by startup seeds and background
# services via SessionLocal) must never reach the Replit-managed Postgres in
# DATABASE_URL. Point it at a throwaway SQLite file that vanishes with the
# temp dir. It stays a *separate* file from the test-fixture DB below so the
# app engine sees the same "different database than the fixtures" world it
# always has (startup seeds fail softly on the empty DB and are swallowed).
_TEST_TMP_ROOT = Path(tempfile.mkdtemp(prefix="ficshon-tests-"))
atexit.register(shutil.rmtree, _TEST_TMP_ROOT, ignore_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_TMP_ROOT / 'app.db'}"

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

# Create test database — a disposable file inside the session temp dir, never
# a repository-root test.db. File-based SQLite (not :memory:) preserves the
# existing connection/threading semantics exactly; the whole dir is removed at
# interpreter exit.
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_TEST_TMP_ROOT / 'test.db'}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def generated_media_dir(tmp_path_factory):
    """Redirect all generated-image disk writes to a pytest-managed temp dir.

    ``_GENERATED_DIR`` is a module-level constant duplicated across
    app.core.storage and several route modules; every one is repointed so no
    test can write into backend/static/generated/. Stored *paths* remain
    "static/generated/<uuid>.png" strings, so test assertions are unaffected.
    """
    tmp_dir = tmp_path_factory.mktemp("generated_media")

    import app.core.storage as _storage
    from app.api.routes import (
        character_visual as _character_visual,
        characters as _characters,
        image_generator as _image_generator,
        scene_images as _scene_images,
        users as _users,
    )

    mods = [_storage, _character_visual, _characters, _image_generator,
            _scene_images, _users]
    originals = [(m, m._GENERATED_DIR) for m in mods]
    for m in mods:
        m._GENERATED_DIR = tmp_dir
    yield tmp_dir
    for m, original in originals:
        m._GENERATED_DIR = original


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
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        # Close the session so its connection returns to the pool. Without this
        # every test leaks one connection and a long run eventually exhausts the
        # QueuePool (size 5 + overflow 10) at teardown's drop_all.
        session.close()
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


def get_auth_token(client, email: str = "user@test.com", username: str = "testuser") -> str:
    """Register a user (if needed) and return their Bearer JWT token.

    Idempotent — if the email already exists the registration 400 is ignored
    and login proceeds normally.
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


def make_admin(email: str) -> None:
    """Promote an existing test user to admin (is_admin=True).

    Used by admin-only surfaces (e.g. Adult Studio, S24D FIX 2) so tests can act
    as an admin while still exercising the downstream ownership/logic checks.
    """
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user and not user.is_admin:
            user.is_admin = True
            db.commit()
    finally:
        db.close()


@pytest.fixture(scope="function")
def authed_client(client):
    """TestClient wrapper that auto-injects auth headers for a default test user.

    Drop-in replacement for ``client`` in tests that require authentication.
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
