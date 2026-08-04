"""The Writer waitlist — interest, and only interest.

The waitlist exists so a Wanderer who reaches the locked upgrade gate has
something to do other than leave. The single thing these tests care about most
is that it stays inert: joining must never become a route to the entitlement.
"""
from datetime import datetime, timedelta

import pytest

from tests.conftest import (
    TestingSessionLocal,
    auth_headers,
    ensure_character,
    get_auth_token,
    grant_writer_unlock,
    make_admin,
)


def _me(client, token: str) -> dict:
    resp = client.get("/users/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(client, token: str):
    return client.post("/users/me/writer-waitlist", headers=auth_headers(token))


def _leave(client, token: str):
    return client.delete("/users/me/writer-waitlist", headers=auth_headers(token))


def _set_joined_at(email: str, when: datetime) -> None:
    """Backdate a waitlist join, so the rolling-window counts can be tested
    without waiting seven days."""
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None, email
        user.writer_waitlist_joined_at = when
        db.commit()
    finally:
        db.close()


# ── Joining, and what it does not grant ──────────────────────────────────────

def test_wanderer_joins_and_state_is_exposed_on_me(client):
    token = get_auth_token(client, email="w@test.com", username="wanderer_one")
    assert _me(client, token)["writer_waitlist_joined_at"] is None

    resp = _join(client, token)
    assert resp.status_code == 200, resp.text
    assert resp.json()["writer_waitlist_joined_at"] is not None
    assert _me(client, token)["writer_waitlist_joined_at"] is not None


@pytest.mark.writer_unlock_enforced
def test_joining_grants_nothing(client):
    """The whole point. Interest is not entitlement.

    Marked ``writer_unlock_enforced`` so the suite-wide fixture that patches
    out the creation gate for legacy fixtures is disabled — this assertion is
    meaningless against a patched gate."""
    token = get_auth_token(client, email="w@test.com", username="wanderer_one")
    body = _join(client, token).json()

    assert body["writer_unlocked"] is False
    assert body["can_create_character"] is False
    assert body["character_count"] == 0

    # ...and the paywall still refuses the creation endpoint itself.
    resp = client.post(
        "/characters/",
        json={"name": "Should Not Exist", "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403, resp.text


def test_joining_is_idempotent_and_keeps_the_original_timestamp(client):
    """A double-click must not create a second entry or re-date the first —
    otherwise it would inflate the 'joined this week' figure."""
    token = get_auth_token(client, email="w@test.com", username="wanderer_one")
    first = _join(client, token).json()["writer_waitlist_joined_at"]
    second = _join(client, token).json()["writer_waitlist_joined_at"]
    third = _join(client, token).json()["writer_waitlist_joined_at"]

    assert first == second == third

    from app.models.user import User

    db = TestingSessionLocal()
    try:
        waiting = (
            db.query(User).filter(User.writer_waitlist_joined_at.isnot(None)).count()
        )
    finally:
        db.close()
    assert waiting == 1


def test_an_account_that_can_already_create_is_refused(client):
    token = get_auth_token(client, email="writer@test.com", username="a_writer")
    grant_writer_unlock("writer@test.com")
    assert _join(client, token).status_code == 400


def test_waitlist_requires_authentication(client):
    assert client.post("/users/me/writer-waitlist").status_code in (401, 403)


# ── Withdrawing ──────────────────────────────────────────────────────────────

def test_withdrawing_clears_the_state_and_is_idempotent(client):
    token = get_auth_token(client, email="w@test.com", username="wanderer_one")
    _join(client, token)

    assert _leave(client, token).json()["writer_waitlist_joined_at"] is None
    # Withdrawing again is a no-op success, not a 404.
    assert _leave(client, token).status_code == 200
    assert _me(client, token)["writer_waitlist_joined_at"] is None


def test_rejoining_after_withdrawing_records_fresh_interest(client):
    token = get_auth_token(client, email="w@test.com", username="wanderer_one")
    _join(client, token)
    _leave(client, token)
    assert _join(client, token).json()["writer_waitlist_joined_at"] is not None


# ── Operator readout ─────────────────────────────────────────────────────────

def test_admin_waitlist_counts_use_rolling_windows(client):
    admin = get_auth_token(client, email="founder@test.com", username="the_founder")
    make_admin("founder@test.com")

    recent = get_auth_token(client, email="recent@test.com", username="recent_one")
    _join(client, recent)

    mid = get_auth_token(client, email="mid@test.com", username="mid_one")
    _join(client, mid)
    _set_joined_at("mid@test.com", datetime.utcnow() - timedelta(days=10))

    old = get_auth_token(client, email="old@test.com", username="old_one")
    _join(client, old)
    _set_joined_at("old@test.com", datetime.utcnow() - timedelta(days=100))

    resp = client.get("/users/admin/writer-waitlist", headers=auth_headers(admin))
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert stats["total"] == 3
    assert stats["last_7_days"] == 1
    assert stats["last_30_days"] == 2


def test_waitlist_readout_is_admin_only(client):
    wanderer = get_auth_token(client, email="w@test.com", username="wanderer_one")
    resp = client.get("/users/admin/writer-waitlist", headers=auth_headers(wanderer))
    assert resp.status_code == 403, resp.text


def test_readout_reports_counts_only(client):
    """A demand figure, not a roster export — no usernames, emails or ids."""
    admin = get_auth_token(client, email="founder@test.com", username="the_founder")
    make_admin("founder@test.com")
    joiner = get_auth_token(client, email="w@test.com", username="wanderer_one")
    _join(client, joiner)

    body = client.get("/users/admin/writer-waitlist", headers=auth_headers(admin)).json()
    assert set(body) == {"total", "last_7_days", "last_30_days"}
    assert "wanderer_one" not in str(body)


# ── The username rules are untouched by any of this ──────────────────────────

def test_username_rename_still_works_for_a_waitlisted_wanderer(client):
    token = get_auth_token(client, email="w@test.com", username="wanderer_one")
    _join(client, token)

    resp = client.patch(
        "/users/me/username",
        json={"username": "renamed_one"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == "renamed_one"
    # Renaming neither joins nor clears the waitlist.
    assert body["writer_waitlist_joined_at"] is not None
    assert body["writer_unlocked"] is False
