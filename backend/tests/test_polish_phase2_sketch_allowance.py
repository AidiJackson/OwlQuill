"""Polish Phase 2 — C10: the Sketch allowance.

ONE rule: ``settings.IDENTITY_SKETCH_ALLOWANCE`` (3) paid sketch generations
per character in a rolling 24-hour window, counted from persisted
IDENTITY_SKETCH rows, enforced by the server BEFORE the provider is called.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.image_quota import SKETCH_WINDOW_HOURS, get_sketch_allowance
from tests.conftest import TestingSessionLocal, auth_headers, character_owner_id, get_auth_token

PROVIDER = "app.api.routes.character_visual.get_identity_provider_by_name"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _character(client: TestClient, token: str, name: str = "Bertie") -> int:
    resp = client.post("/characters/", json={"name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_sketch(cid: int, *, age: timedelta, status: str = "archived") -> int:
    """One persisted IDENTITY_SKETCH row for *cid*, created ``age`` ago."""
    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )

    db = TestingSessionLocal()
    try:
        row = CharacterImage(
            character_id=cid,
            user_id=character_owner_id(db, cid),
            kind=ImageKindEnum.IDENTITY_SKETCH,
            status=ImageStatusEnum(status),
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path=f"static/generated/sketch-{cid}-{age.total_seconds()}.png",
            created_at=datetime.utcnow() - age,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _mock_provider():
    provider = MagicMock()
    provider.generate_image = MagicMock(return_value=_PNG)
    return provider


def _generate(client: TestClient, token: str, cid: int, provider=None):
    provider = provider or _mock_provider()
    with patch(PROVIDER, return_value=provider):
        resp = client.post(
            f"/characters/{cid}/identity-sketch/generate",
            json={"style": "pencil"},
            headers=auth_headers(token),
        )
    return resp, provider


def _allowance(client: TestClient, token: str, cid: int):
    return client.get(f"/characters/{cid}/identity-sketch/allowance", headers=auth_headers(token))


# ── The count ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seeded, remaining", [(0, 3), (1, 2), (2, 1), (3, 0)])
def test_remaining_counts_down_from_three(client: TestClient, seeded, remaining):
    token = get_auth_token(client, email=f"p2a{seeded}@test.com", username=f"p2a{seeded}")
    cid = _character(client, token)
    for i in range(seeded):
        _seed_sketch(cid, age=timedelta(hours=i + 1))

    resp = _allowance(client, token, cid)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["limit"] == 3
    assert body["used"] == seeded
    assert body["remaining"] == remaining
    assert body["allowed"] is (remaining > 0)
    assert body["window_hours"] == SKETCH_WINDOW_HOURS
    if remaining > 0:
        assert body["next_available_at"] is None
    else:
        assert body["next_available_at"] is not None


def test_rows_older_than_the_window_do_not_count(client: TestClient):
    token = get_auth_token(client, email="p2old@test.com", username="p2old")
    cid = _character(client, token)
    _seed_sketch(cid, age=timedelta(hours=25))
    _seed_sketch(cid, age=timedelta(days=3))
    _seed_sketch(cid, age=timedelta(hours=2))

    body = _allowance(client, token, cid).json()
    assert body["used"] == 1
    assert body["remaining"] == 2


def test_archived_and_active_rows_both_count(client: TestClient):
    """Regenerating archives the previous sketch; that row is the attempt."""
    token = get_auth_token(client, email="p2arch@test.com", username="p2arch")
    cid = _character(client, token)
    _seed_sketch(cid, age=timedelta(hours=1), status="archived")
    _seed_sketch(cid, age=timedelta(minutes=5), status="active")
    assert _allowance(client, token, cid).json()["used"] == 2


def test_window_boundary_is_strictly_less_than_24h(client: TestClient):
    """A row counts while now - created_at < 24h; at exactly 24h it has left."""
    db = TestingSessionLocal()
    try:
        token = get_auth_token(client, email="p2edge@test.com", username="p2edge")
        cid = _character(client, token)
        _seed_sketch(cid, age=timedelta(hours=24) - timedelta(seconds=5))
        _seed_sketch(cid, age=timedelta(hours=24) + timedelta(seconds=5))
        now = datetime.utcnow()
        inside = get_sketch_allowance(cid, db, now=now)
        assert inside["used"] == 1
        # Ten seconds later the inside row has crossed the boundary too.
        later = get_sketch_allowance(cid, db, now=now + timedelta(seconds=10))
        assert later["used"] == 0
    finally:
        db.close()


def test_next_available_is_when_the_oldest_counted_attempt_leaves_the_window(client: TestClient):
    db = TestingSessionLocal()
    try:
        token = get_auth_token(client, email="p2next@test.com", username="p2next")
        cid = _character(client, token)
        now = datetime.utcnow().replace(microsecond=0)
        for hours in (20, 3, 1):
            _seed_sketch(cid, age=timedelta(hours=hours))
        a = get_sketch_allowance(cid, db, now=now)
        assert a["remaining"] == 0
        expected = (now - timedelta(hours=20) + timedelta(hours=SKETCH_WINDOW_HOURS))
        got = datetime.fromisoformat(a["next_available_at"].rstrip("Z"))
        assert abs((got - expected).total_seconds()) <= 1
    finally:
        db.close()


# ── Enforcement ──────────────────────────────────────────────────────────────


def test_exhausted_allowance_is_429_and_the_provider_is_never_called(client: TestClient):
    token = get_auth_token(client, email="p2full@test.com", username="p2full")
    cid = _character(client, token)
    for i in range(3):
        _seed_sketch(cid, age=timedelta(hours=i + 1))

    resp, provider = _generate(client, token, cid)
    assert resp.status_code == 429, resp.text
    body = resp.json()
    assert body["error"] == "sketch_allowance_exhausted"
    assert body["allowance"]["remaining"] == 0
    assert body["allowance"]["used"] == 3
    assert body["allowance"]["next_available_at"]
    provider.generate_image.assert_not_called()


def test_a_successful_generation_changes_the_authoritative_allowance(client: TestClient):
    token = get_auth_token(client, email="p2gen@test.com", username="p2gen")
    cid = _character(client, token)
    assert _allowance(client, token, cid).json()["remaining"] == 3

    resp, provider = _generate(client, token, cid)
    assert resp.status_code == 200, resp.text
    provider.generate_image.assert_called_once()
    # The generate response carries the allowance AFTER this attempt.
    assert resp.json()["allowance"] == _allowance(client, token, cid).json()
    assert resp.json()["allowance"]["remaining"] == 2

    resp, _ = _generate(client, token, cid)
    assert resp.status_code == 200
    assert resp.json()["allowance"]["remaining"] == 1
    resp, _ = _generate(client, token, cid)
    assert resp.status_code == 200
    assert resp.json()["allowance"]["remaining"] == 0

    resp, provider = _generate(client, token, cid)
    assert resp.status_code == 429
    provider.generate_image.assert_not_called()


def test_a_provider_failure_does_not_consume_an_attempt(client: TestClient):
    token = get_auth_token(client, email="p2fail@test.com", username="p2fail")
    cid = _character(client, token)
    broken = MagicMock()
    broken.generate_image = MagicMock(side_effect=RuntimeError("provider down"))

    resp, _ = _generate(client, token, cid, provider=broken)
    assert resp.status_code == 503, resp.text
    assert "sketch_allowance" not in resp.text
    assert _allowance(client, token, cid).json()["remaining"] == 3


def test_a_persistence_failure_after_the_provider_does_not_consume_an_attempt(client: TestClient):
    """The provider was paid, the creator was not charged — the safe direction."""
    token = get_auth_token(client, email="p2persist@test.com", username="p2persist")
    cid = _character(client, token)
    with patch("app.api.routes.character_visual.persist_image_asset", side_effect=RuntimeError("disk")):
        with pytest.raises(RuntimeError):
            _generate(client, token, cid)
    assert _allowance(client, token, cid).json()["remaining"] == 3


# ── Ownership ────────────────────────────────────────────────────────────────


def test_another_user_cannot_read_or_spend_the_allowance(client: TestClient):
    owner = get_auth_token(client, email="p2own@test.com", username="p2own")
    cid = _character(client, owner)
    stranger = get_auth_token(client, email="p2str@test.com", username="p2str")

    assert _allowance(client, stranger, cid).status_code == 403
    resp, provider = _generate(client, stranger, cid)
    assert resp.status_code == 403
    provider.generate_image.assert_not_called()
    assert _allowance(client, owner, cid).json()["remaining"] == 3


def test_allowance_is_per_character(client: TestClient):
    token = get_auth_token(client, email="p2two@test.com", username="p2two")
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        u = db.query(User).filter(User.email == "p2two@test.com").one()
        u.is_seeder = True  # may own more than one character
        db.commit()
    finally:
        db.close()
    a = _character(client, token, "A")
    b = _character(client, token, "B")
    for i in range(3):
        _seed_sketch(a, age=timedelta(hours=i + 1))
    assert _allowance(client, token, a).json()["remaining"] == 0
    assert _allowance(client, token, b).json()["remaining"] == 3
