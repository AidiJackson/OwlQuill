"""Tests for the login rate limiter's user-facing contract.

The limit itself is not under test here — slowapi enforces it. What is under
test is everything a throttled human sees: that the response carries a readable
``detail`` instead of slowapi's stock ``{"error": ...}`` body (which made the UI
render the bare string "HTTP 429"), that ``Retry-After`` is present, that the
message leaks nothing about whether the account exists, and that a *correct*
password hands the allowance back so a legitimate user is not left locked out
by their own typos.

The shared ``client`` fixture disables the limiter for determinism; these tests
re-enable it around themselves and reset its storage on both sides, so they
neither depend on nor leak counter state.
"""
import pytest
from fastapi.testclient import TestClient

from app.api.routes.auth import (
    RATE_LIMIT_MESSAGE_LOGIN,
    limiter,
)
from app.core.config import settings

# The configured allowance, e.g. "5/minute" -> 5.
LIMIT = int(settings.RATE_LIMIT_AUTH.split("/")[0])


@pytest.fixture
def limited(client: TestClient):
    """Run a test with the limiter live and its counters empty."""
    limiter.limiter.storage.reset()
    limiter.enabled = True
    try:
        yield client
    finally:
        limiter.enabled = False
        limiter.limiter.storage.reset()


def _register(client: TestClient, email: str, username: str, password: str) -> None:
    response = client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    assert response.status_code == 201


def _login(client: TestClient, email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_repeated_failures_trip_a_readable_429(limited: TestClient):
    """The N+1th bad attempt is throttled, and says so in plain words."""
    for _ in range(LIMIT):
        assert _login(limited, "ghost@example.com", "wrong").status_code == 401

    response = _login(limited, "ghost@example.com", "wrong")
    assert response.status_code == 429

    detail = response.json()["detail"]
    assert detail == RATE_LIMIT_MESSAGE_LOGIN
    # The UI shows `detail` verbatim, so a status code must never appear in it.
    assert "429" not in detail
    assert "HTTP" not in detail
    # slowapi's stock body key must be gone — it is what the frontend could not
    # read, and reading it is what produced "HTTP 429".
    assert "error" not in response.json()


def test_throttled_response_carries_retry_after(limited: TestClient):
    """Clients can be told how long to wait rather than guessing."""
    for _ in range(LIMIT):
        _login(limited, "ghost@example.com", "wrong")

    response = _login(limited, "ghost@example.com", "wrong")
    assert response.status_code == 429
    assert "retry-after" in {k.lower() for k in response.headers}
    assert int(response.headers["retry-after"]) >= 0


def test_throttling_does_not_reveal_whether_an_account_exists(limited: TestClient):
    """A real account and an unknown one are throttled identically."""
    _register(limited, "real@example.com", "realuser", "correct-horse-battery")
    limiter.limiter.storage.reset()

    for _ in range(LIMIT):
        _login(limited, "real@example.com", "wrong")
    real = _login(limited, "real@example.com", "wrong")

    limiter.limiter.storage.reset()
    for _ in range(LIMIT):
        _login(limited, "unknown@example.com", "wrong")
    unknown = _login(limited, "unknown@example.com", "wrong")

    assert real.status_code == unknown.status_code == 429
    assert real.json() == unknown.json()


def test_a_correct_password_hands_the_allowance_back(limited: TestClient):
    """Typos before a successful login must not leave the user near a lockout.

    Without the reset, a user who fumbles LIMIT-1 times and then signs in
    correctly is one attempt away from being locked out of their own account
    for the rest of the window.
    """
    _register(limited, "real@example.com", "realuser", "correct-horse-battery")
    limiter.limiter.storage.reset()

    for _ in range(LIMIT - 1):
        assert _login(limited, "real@example.com", "wrong").status_code == 401

    assert _login(limited, "real@example.com", "correct-horse-battery").status_code == 200

    # The counter is back to zero: a full fresh allowance follows, where before
    # the reset the very next attempt would have been throttled.
    for _ in range(LIMIT):
        assert _login(limited, "real@example.com", "wrong").status_code == 401
    assert _login(limited, "real@example.com", "wrong").status_code == 429


def test_failed_login_still_reports_incorrect_credentials(limited: TestClient):
    """401 wording is unchanged — 429 must stay distinguishable from it."""
    response = _login(limited, "ghost@example.com", "wrong")
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_valid_credentials_work_once_the_window_clears(limited: TestClient):
    """After the window expires the same credentials succeed."""
    _register(limited, "real@example.com", "realuser", "correct-horse-battery")
    limiter.limiter.storage.reset()

    for _ in range(LIMIT):
        _login(limited, "real@example.com", "wrong")
    assert _login(limited, "real@example.com", "correct-horse-battery").status_code == 429

    # Standing in for the clock: the window elapsing is what clears the counter.
    limiter.limiter.storage.reset()
    assert _login(limited, "real@example.com", "correct-horse-battery").status_code == 200


def test_other_auth_endpoints_keep_their_own_allowance(limited: TestClient):
    """Exhausting login must not throttle an unrelated limiter key."""
    for _ in range(LIMIT + 1):
        _login(limited, "ghost@example.com", "wrong")
    assert _login(limited, "ghost@example.com", "wrong").status_code == 429

    # Registration is a separate bucket and is untouched.
    response = limited.post(
        "/auth/register",
        json={
            "email": "fresh@example.com",
            "username": "freshuser",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201
