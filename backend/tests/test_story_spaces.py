"""Stage 2 API tests for Story Spaces — space management + channels.

BETA_INVITE_REQUIRED is True in this environment.  The seed_test_invite
fixture (autouse=True) inserts a test invite code into the SQLite test DB
before each test so _make_user() can register without error.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers

# ── invite seeding ────────────────────────────────────────────────────────────

_INVITE_CODE = "SS-STAGE2-TEST"


@pytest.fixture(autouse=True)
def seed_test_invite(db_session):
    """Insert a test invite code for every test in this module."""
    from app.models.invite_code import InviteCode

    db_session.add(InviteCode(
        code=_INVITE_CODE,
        is_enabled=True,
        max_uses=None,   # unlimited — many users per test
        use_count=0,
        created_at=datetime.utcnow(),
    ))
    db_session.commit()


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(client: TestClient, n: int) -> str:
    """Register user N (idempotent) and return their Bearer token."""
    client.post(
        "/auth/register",
        json={
            "email": f"spacetest{n}@test.com",
            "username": f"spacetest{n}",
            "password": "testpass!123",
            "invite_code": _INVITE_CODE,
        },
    )
    resp = client.post(
        "/auth/login",
        json={"email": f"spacetest{n}@test.com", "password": "testpass!123"},
    )
    assert resp.status_code == 200, f"Login failed for user {n}: {resp.text}"
    return resp.json()["access_token"]


def _create_space(client: TestClient, token: str, name: str = "Test Space", **kwargs) -> dict:
    resp = client.post(
        "/story-spaces/",
        json={"name": name, **kwargs},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, f"Space creation failed: {resp.text}"
    return resp.json()


def _get_my_user_id(client: TestClient, token: str) -> int:
    resp = client.get("/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200
    return resp.json()["id"]


# ── create space ──────────────────────────────────────────────────────────────

def test_create_space_returns_201(client):
    token = _make_user(client, 1)
    resp = client.post(
        "/story-spaces/",
        json={"name": "My Space"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Space"
    assert data["your_role"] == "owner"
    assert data["member_count"] == 1


def test_create_space_auto_creates_three_channels(client):
    token = _make_user(client, 1)
    data = _create_space(client, token)
    channels = data["channels"]
    assert len(channels) == 3
    assert [c["channel_type"] for c in channels] == ["story", "chat", "planning"]
    assert [c["position"] for c in channels] == [0, 1, 2]
    assert [c["name"] for c in channels] == ["Story", "Chat", "Planning"]


def test_create_space_with_slug_stores_it(client):
    token = _make_user(client, 1)
    data = _create_space(client, token, slug="my-slug")
    assert data["slug"] == "my-slug"


def test_create_space_without_slug_is_null(client):
    token = _make_user(client, 1)
    data = _create_space(client, token)
    assert data["slug"] is None


def test_create_space_with_description(client):
    token = _make_user(client, 1)
    data = _create_space(client, token, description="A shared writing space")
    assert data["description"] == "A shared writing space"


def test_create_space_unauthenticated_returns_403(client):
    resp = client.post("/story-spaces/", json={"name": "No Auth"})
    assert resp.status_code == 403


def test_create_multiple_spaces_same_slug_allowed(client):
    """Slugs have no global uniqueness constraint — two users can use the same slug."""
    t1 = _make_user(client, 1)
    t2 = _make_user(client, 2)
    _create_space(client, t1, slug="shared-slug")
    data = _create_space(client, t2, name="Other Space", slug="shared-slug")
    assert data["slug"] == "shared-slug"


# ── list spaces ───────────────────────────────────────────────────────────────

def test_list_spaces_returns_only_users_spaces(client):
    t1 = _make_user(client, 1)
    t2 = _make_user(client, 2)
    _create_space(client, t1, name="Space A")
    _create_space(client, t2, name="Space B")

    resp = client.get("/story-spaces/", headers=auth_headers(t1))
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert "Space A" in names
    assert "Space B" not in names


def test_list_spaces_empty_for_new_user(client):
    token = _make_user(client, 1)
    resp = client.get("/story-spaces/", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_spaces_includes_space_after_invite(client):
    owner = _make_user(client, 1)
    member = _make_user(client, 2)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )

    resp = client.get("/story-spaces/", headers=auth_headers(member))
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert space["id"] in ids


def test_list_spaces_shows_correct_role(client):
    owner = _make_user(client, 1)
    member = _make_user(client, 2)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )

    owner_list = client.get("/story-spaces/", headers=auth_headers(owner)).json()
    member_list = client.get("/story-spaces/", headers=auth_headers(member)).json()

    owner_item = next(s for s in owner_list if s["id"] == space["id"])
    member_item = next(s for s in member_list if s["id"] == space["id"])

    assert owner_item["your_role"] == "owner"
    assert member_item["your_role"] == "member"


# ── get detail ────────────────────────────────────────────────────────────────

def test_get_space_detail_as_owner(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    resp = client.get(f"/story-spaces/{space['id']}", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == space["id"]
    assert data["your_role"] == "owner"
    assert data["member_count"] == 1
    assert len(data["channels"]) == 3


def test_get_space_detail_channels_in_order(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    resp = client.get(f"/story-spaces/{space['id']}", headers=auth_headers(token))
    channels = resp.json()["channels"]
    assert [c["channel_type"] for c in channels] == ["story", "chat", "planning"]
    assert [c["position"] for c in channels] == [0, 1, 2]


def test_get_space_non_member_returns_404(client):
    owner = _make_user(client, 1)
    outsider = _make_user(client, 2)
    space = _create_space(client, owner)

    resp = client.get(f"/story-spaces/{space['id']}", headers=auth_headers(outsider))
    assert resp.status_code == 404


def test_get_space_unauthenticated_returns_403(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    resp = client.get(f"/story-spaces/{space['id']}")
    assert resp.status_code == 403


def test_get_space_nonexistent_id_returns_404(client):
    token = _make_user(client, 1)
    resp = client.get("/story-spaces/99999", headers=auth_headers(token))
    assert resp.status_code == 404


# ── invite ────────────────────────────────────────────────────────────────────

def test_invite_member_returns_201(client):
    owner = _make_user(client, 1)
    _make_user(client, 2)
    space = _create_space(client, owner)

    resp = client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "spacetest2"
    assert data["role"] == "member"
    assert data["space_id"] == space["id"]


def test_invite_gives_invited_user_access(client):
    owner = _make_user(client, 1)
    member = _make_user(client, 2)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )

    resp = client.get(f"/story-spaces/{space['id']}", headers=auth_headers(member))
    assert resp.status_code == 200
    assert resp.json()["your_role"] == "member"


def test_invite_nonexistent_user_returns_404(client):
    owner = _make_user(client, 1)
    space = _create_space(client, owner)

    resp = client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "nobody_here"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404


def test_invite_duplicate_returns_409(client):
    owner = _make_user(client, 1)
    _make_user(client, 2)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )
    resp = client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 409


def test_invite_by_non_member_returns_404(client):
    owner = _make_user(client, 1)
    outsider = _make_user(client, 2)
    _make_user(client, 3)
    space = _create_space(client, owner)

    resp = client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest3"},
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 404


def test_invite_increments_member_count(client):
    owner = _make_user(client, 1)
    _make_user(client, 2)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )

    resp = client.get(f"/story-spaces/{space['id']}", headers=auth_headers(owner))
    assert resp.json()["member_count"] == 2


def test_member_can_also_invite(client):
    """Any member (not just owner) can invite in v1."""
    owner = _make_user(client, 1)
    member = _make_user(client, 2)
    _make_user(client, 3)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )

    resp = client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest3"},
        headers=auth_headers(member),
    )
    assert resp.status_code == 201


# ── remove / leave ────────────────────────────────────────────────────────────

def test_owner_can_remove_member(client):
    owner = _make_user(client, 1)
    member = _make_user(client, 2)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )
    member_id = _get_my_user_id(client, member)

    resp = client.delete(
        f"/story-spaces/{space['id']}/members/{member_id}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204

    # removed user can no longer access the space
    check = client.get(f"/story-spaces/{space['id']}", headers=auth_headers(member))
    assert check.status_code == 404


def test_owner_cannot_be_removed(client):
    owner = _make_user(client, 1)
    space = _create_space(client, owner)
    owner_id = _get_my_user_id(client, owner)

    resp = client.delete(
        f"/story-spaces/{space['id']}/members/{owner_id}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 400


def test_member_can_leave(client):
    owner = _make_user(client, 1)
    member = _make_user(client, 2)
    space = _create_space(client, owner)

    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )
    member_id = _get_my_user_id(client, member)

    resp = client.delete(
        f"/story-spaces/{space['id']}/members/{member_id}",
        headers=auth_headers(member),
    )
    assert resp.status_code == 204

    check = client.get(f"/story-spaces/{space['id']}", headers=auth_headers(member))
    assert check.status_code == 404


def test_member_cannot_remove_other_member(client):
    owner = _make_user(client, 1)
    m1 = _make_user(client, 2)
    m2 = _make_user(client, 3)
    space = _create_space(client, owner)

    for username in ["spacetest2", "spacetest3"]:
        client.post(
            f"/story-spaces/{space['id']}/invites",
            json={"username": username},
            headers=auth_headers(owner),
        )
    m2_id = _get_my_user_id(client, m2)

    resp = client.delete(
        f"/story-spaces/{space['id']}/members/{m2_id}",
        headers=auth_headers(m1),
    )
    assert resp.status_code == 403


def test_remove_nonexistent_member_returns_404(client):
    owner = _make_user(client, 1)
    space = _create_space(client, owner)

    resp = client.delete(
        f"/story-spaces/{space['id']}/members/99999",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404


# ── channels ──────────────────────────────────────────────────────────────────

def test_list_channels_returns_three_in_order(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    resp = client.get(
        f"/story-spaces/{space['id']}/channels",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert [c["channel_type"] for c in data] == ["story", "chat", "planning"]
    assert [c["position"] for c in data] == [0, 1, 2]


def test_list_channels_non_member_returns_404(client):
    owner = _make_user(client, 1)
    outsider = _make_user(client, 2)
    space = _create_space(client, owner)

    resp = client.get(
        f"/story-spaces/{space['id']}/channels",
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 404


def test_list_channels_each_has_id(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    channels = client.get(
        f"/story-spaces/{space['id']}/channels",
        headers=auth_headers(token),
    ).json()

    ids = [c["id"] for c in channels]
    assert len(ids) == 3
    assert len(set(ids)) == 3   # all distinct
