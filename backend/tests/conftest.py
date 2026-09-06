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

# --- Outbound-network guard (external-cost safety checkpoint) ---------------
#
# WHY THIS EXISTS, GIVEN THE CREDENTIAL STRIPPING ABOVE.
#
# Popping the provider variables makes every provider REFUSE to construct, and
# that has held so far. It is not a guarantee, for three reasons found in the
# September 2026 cost audit:
#
#  1. The pop list is hand-maintained. A provider added to ``config.py`` with a
#     new variable is live in tests until somebody remembers this file.
#  2. ``Settings`` is declared with ``env_file=".env"``, and pydantic-settings
#     consults the dotenv file WHEN THE ENVIRONMENT VARIABLE IS ABSENT — which
#     is exactly the state the pops above create. Stripping ``os.environ`` does
#     not defeat ``.env``; it activates it. ``backend/.env`` happens to carry no
#     provider key today, so nothing is behind that door — but the door is open
#     and no test would notice it being opened.
#  3. This workspace really does hold live OPENAI / GOOGLE / REPLICATE / RUNPOD /
#     OPENROUTER and R2 credentials. The blast radius of a mistake is real money.
#
# So the rule is enforced where it cannot be bypassed by configuration: a paid
# request cannot leave the process, whatever a provider believes it is holding.
# Credential absence remains the first line; this is the one that does not
# depend on a list staying complete.
#
# LOOPBACK STAYS OPEN. Tests talk to themselves — Starlette's TestClient is
# in-process, but local servers, SQLite over a socket and debugger attachments
# are not, and blocking them would break tests for no safety gain.
#
# OPT-IN: LIVE_API_TESTS=1 disables the guard for deliberately invoked live
# tests. It is never set automatically anywhere in this repository.

import socket as _socket

LIVE_API_TESTS_ENV = "LIVE_API_TESTS"

#: Hostnames and addresses that are this machine talking to itself.
_LOOPBACK = frozenset({
    "localhost", "localhost.localdomain",
    "127.0.0.1", "::1", "::ffff:127.0.0.1",
    "0.0.0.0", "::", "",
    "testserver",  # Starlette TestClient's synthetic host
})

_BLOCKED_MESSAGE = (
    "Outbound network is disabled during tests (attempted %s).\n"
    "Ficshon's test suite must not be able to reach a paid provider — OpenAI, "
    "Google, Replicate, RunPod, OpenRouter, Together, fal or R2 — because this "
    "workspace holds live credentials for most of them.\n"
    "If you genuinely intend to make live API calls (they cost money), run with "
    "%s=1."
)


def _host_of(address):
    """The host part of a socket address, or None when there is no host.

    AF_UNIX addresses are ``str``/``bytes`` paths and never leave the machine;
    AF_INET is ``(host, port)`` and AF_INET6 ``(host, port, flow, scope)``.
    """
    if isinstance(address, (str, bytes, os.PathLike)):
        return None  # AF_UNIX — local by construction
    if isinstance(address, tuple) and address:
        return address[0]
    return None


def _is_local(address) -> bool:
    host = _host_of(address)
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("utf-8", "replace")
    if host in _LOOPBACK:
        return True
    # 127.0.0.0/8 in full, not just 127.0.0.1.
    return isinstance(host, str) and host.startswith("127.")


def _install_network_guard():
    """Patch the socket layer so no connection can reach a non-loopback host.

    WHAT IS PATCHED, AND WHY THESE THREE.
    Every HTTP mechanism this codebase uses — ``urllib.request`` (9 modules),
    ``requests``/urllib3 (6), ``httpx`` (3, and the OpenAI SDK), and boto3 for
    R2 — reaches the network through exactly one of these:

    * ``socket.socket.connect`` — the funnel. ``socket.create_connection``
      builds a socket and calls it, so urllib3 and httpcore are covered without
      patching them; asyncio's ``sock_connect`` calls it too, so async clients
      are covered as well. Patching only the higher-level helpers would leave
      the funnel open, which is the cosmetic version of this guard.
    * ``socket.socket.connect_ex`` — the same syscall with an errno return
      instead of an exception. Not covered by patching ``connect``.
    * ``socket.getaddrinfo`` — DNS. Resolution happens BEFORE connect and is
      itself outbound traffic to a resolver, so blocking connect alone would
      still leak the hostname being looked up. Blocking it here also means a
      test fails on the attempt rather than after a 30-second timeout.

    Returns the originals so the session fixture can put them back.
    """
    originals = (
        _socket.socket.connect,
        _socket.socket.connect_ex,
        _socket.getaddrinfo,
    )
    real_connect, real_connect_ex, real_getaddrinfo = originals

    def _guarded_connect(self, address, *args, **kwargs):
        if not _is_local(address):
            raise RuntimeError(_BLOCKED_MESSAGE % (address, LIVE_API_TESTS_ENV))
        return real_connect(self, address, *args, **kwargs)

    def _guarded_connect_ex(self, address, *args, **kwargs):
        if not _is_local(address):
            raise RuntimeError(_BLOCKED_MESSAGE % (address, LIVE_API_TESTS_ENV))
        return real_connect_ex(self, address, *args, **kwargs)

    def _guarded_getaddrinfo(host, port, *args, **kwargs):
        if not _is_local((host, port)):
            raise RuntimeError(_BLOCKED_MESSAGE % (host, LIVE_API_TESTS_ENV))
        return real_getaddrinfo(host, port, *args, **kwargs)

    _socket.socket.connect = _guarded_connect
    _socket.socket.connect_ex = _guarded_connect_ex
    _socket.getaddrinfo = _guarded_getaddrinfo
    return originals


def _restore_network(originals) -> None:
    _socket.socket.connect, _socket.socket.connect_ex, _socket.getaddrinfo = originals


#: Installed at conftest IMPORT, not in a fixture, so collection-time imports are
#: covered too — a module that called a provider at import would otherwise run
#: before any fixture could stop it. ``None`` when the opt-in is set.
_NETWORK_GUARD_ORIGINALS = (
    None if os.environ.get(LIVE_API_TESTS_ENV) == "1" else _install_network_guard()
)

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
def _network_guard():
    """Keep the guard for the whole session, then put the socket layer back.

    Restoration matters because pytest runs in a process that may go on to do
    other things (``--pdb``, plugins with teardown reporting), and leaving the
    standard library monkeypatched after the run is its own surprise.
    """
    yield
    if _NETWORK_GUARD_ORIGINALS is not None:
        _restore_network(_NETWORK_GUARD_ORIGINALS)


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


def ensure_character(client, token: str, name: str = "Fixture Character") -> int:
    """Give this account an owned character, idempotently. Returns its id.

    Creator mutations — StoryLab stories, Story Spaces, RP threads, image
    generation — are gated by ``app.core.entitlements.require_creator``, which
    derives the creator entitlement from character ownership. A fixture that
    registers a bare account and immediately posts to one of those routes is
    acting as a WANDERER, and a 403 is the endpoint working correctly.

    Call this for any fixture user that is meant to be a creator. Do NOT call it
    for a user whose test is specifically asserting the Wanderer 403 — that
    account must stay characterless for the assertion to mean anything.

    Idempotent: returns the existing character when the account already owns
    one, so repeat calls don't trip the one-character-per-account limit.
    """
    existing = client.get("/characters/", headers=auth_headers(token))
    if existing.status_code == 200 and existing.json():
        return existing.json()[0]["id"]
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, f"Fixture character creation failed: {resp.text}"
    return resp.json()["id"]


def character_owner_id(db, character_id: int) -> int:
    """The account that owns a character.

    ``CharacterImage.user_id`` is NOT NULL as of Phase 4B2 and means "the
    account that owns this asset", so a hand-built image row in a test has to
    name an owner the same way production writers do — from the character, not
    from whoever happened to be authenticated.
    """
    from app.models.character import Character

    return db.query(Character).filter(Character.id == character_id).one().owner_id


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


# ── Writer Unlock (paid entitlement) ─────────────────────────────────────────


def grant_writer_unlock(email: str) -> None:
    """Give an existing test account the paid Writer Unlock.

    This is the operator grant — it writes the same ``writer_unlocked_at``
    column a real purchase would, so a test that uses it exercises the genuine
    entitlement path rather than a bypass.
    """
    from datetime import datetime

    from app.models.user import User

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None, f"No such test user: {email}"
        user.writer_unlocked_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "writer_unlock_enforced: run this test with the real character-creation "
        "paywall in force (the suite-wide fixture is disabled).",
    )


@pytest.fixture(autouse=True)
def auto_writer_unlock(request, monkeypatch):
    """Treat every test account as Writer-unlocked *for character creation only*.

    Most of the suite predates the paid unlock and registers a bare account
    purely so it can own a character to test something else with. Rather than
    thread a purchase through a hundred fixtures, this patches the single
    creation gate — and nothing else, so the creator-workspace entitlement
    (``require_creator``) and every Wanderer 403 assertion elsewhere are still
    exercised for real.

    Tests that assert the paywall itself mark themselves
    ``@pytest.mark.writer_unlock_enforced`` and get the unpatched gate.
    """
    if request.node.get_closest_marker("writer_unlock_enforced"):
        return
    from app.api.routes import characters as characters_route

    monkeypatch.setattr(characters_route, "can_create_character", lambda db, user: True)
