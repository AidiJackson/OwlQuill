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

# ── posts ─────────────────────────────────────────────────────────────────────

def _get_channel(client: TestClient, token: str, space: dict, channel_type: str) -> dict:
    channels = client.get(
        f"/story-spaces/{space['id']}/channels",
        headers=auth_headers(token),
    ).json()
    return next(c for c in channels if c["channel_type"] == channel_type)


def _create_character(client: TestClient, token: str, name: str = "TestChar") -> dict:
    resp = client.post(
        "/characters/",
        json={"name": name},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, f"Character creation failed: {resp.text}"
    return resp.json()


def test_member_can_post_to_story_channel(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "story")

    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": "Once upon a time...", "content_type": "ic"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"] == "Once upon a time..."
    assert data["content_type"] == "ic"
    assert data["author_username"] == "spacetest1"
    assert data["channel_id"] == ch["id"]
    assert data["space_id"] == space["id"]


def test_member_can_post_to_chat_channel(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "chat")

    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": "Hey everyone", "content_type": "ooc"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert resp.json()["content_type"] == "ooc"


def test_member_can_post_to_planning_channel(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "planning")

    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": "Let's plan the next arc", "content_type": "ooc"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201


def test_non_member_post_returns_404(client):
    owner = _make_user(client, 1)
    outsider = _make_user(client, 2)
    space = _create_space(client, owner)
    ch = _get_channel(client, owner, space, "story")

    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": "Sneaking in", "content_type": "ic"},
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 404


def test_wrong_channel_different_space_returns_404(client):
    t1 = _make_user(client, 1)
    t2 = _make_user(client, 2)
    space1 = _create_space(client, t1, name="Space 1")
    space2 = _create_space(client, t2, name="Space 2")
    ch2 = _get_channel(client, t2, space2, "story")

    # t1 is member of space1, tries to post to channel from space2
    resp = client.post(
        f"/story-spaces/{space1['id']}/channels/{ch2['id']}/posts",
        json={"content": "Wrong space channel", "content_type": "ic"},
        headers=auth_headers(t1),
    )
    assert resp.status_code == 404


def test_invalid_character_ownership_returns_403(client):
    owner = _make_user(client, 1)
    member = _make_user(client, 2)
    space = _create_space(client, owner)
    ch = _get_channel(client, owner, space, "story")

    # Invite member
    client.post(
        f"/story-spaces/{space['id']}/invites",
        json={"username": "spacetest2"},
        headers=auth_headers(owner),
    )

    # Create character owned by owner (user 1)
    char = _create_character(client, owner, name="OwnerChar")

    # member (user 2) tries to post with owner's character
    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": "Using someone else's char", "content_type": "ic", "character_id": char["id"]},
        headers=auth_headers(member),
    )
    assert resp.status_code == 403


def test_post_with_own_character_includes_character_fields(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "story")
    char = _create_character(client, token, name="MyHero")

    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": "Entering the scene", "content_type": "ic", "character_id": char["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["character_id"] == char["id"]
    assert data["character_name"] == "MyHero"
    assert data["character_avatar_url"] is None   # no avatar set in test


def test_post_without_character_has_null_character_fields(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "story")

    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": "Narrator voice", "content_type": "narration"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["character_id"] is None
    assert data["character_name"] is None
    assert data["character_avatar_url"] is None


def test_list_posts_returns_correct_order(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "story")

    messages = ["First post", "Second post", "Third post"]
    for msg in messages:
        client.post(
            f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
            json={"content": msg, "content_type": "ic"},
            headers=auth_headers(token),
        )

    resp = client.get(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert [p["content"] for p in data] == messages


def test_list_posts_non_member_returns_404(client):
    owner = _make_user(client, 1)
    outsider = _make_user(client, 2)
    space = _create_space(client, owner)
    ch = _get_channel(client, owner, space, "story")

    resp = client.get(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 404


def test_list_posts_wrong_channel_returns_404(client):
    t1 = _make_user(client, 1)
    t2 = _make_user(client, 2)
    space1 = _create_space(client, t1, name="Space 1")
    space2 = _create_space(client, t2, name="Space 2")
    ch2 = _get_channel(client, t2, space2, "story")

    resp = client.get(
        f"/story-spaces/{space1['id']}/channels/{ch2['id']}/posts",
        headers=auth_headers(t1),
    )
    assert resp.status_code == 404


def test_list_posts_empty_channel_returns_empty_list(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "chat")

    resp = client.get(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json() == []

# ── publish ───────────────────────────────────────────────────────────────────

def _publish_space(client: TestClient, token: str, space_id: int, post_ids: list, title: str = "Test Story") -> object:
    return client.post(
        f"/story-spaces/{space_id}/publish",
        json={"title": title, "post_ids": post_ids},
        headers=auth_headers(token),
    )


def _post_to_channel(client: TestClient, token: str, space: dict, channel_type: str, content: str = "Post content", content_type: str = "ic") -> dict:
    ch = _get_channel(client, token, space, channel_type)
    resp = client.post(
        f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
        json={"content": content, "content_type": content_type},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, f"Post failed: {resp.text}"
    return resp.json()


def test_publish_valid_story_posts(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    post_ids = []
    for msg in ["Chapter one begins.", "The hero arrives.", "A twist emerges."]:
        post = _post_to_channel(client, token, space, "story", content=msg)
        post_ids.append(post["id"])

    resp = _publish_space(client, token, space["id"], post_ids)
    assert resp.status_code == 201
    data = resp.json()
    assert data["segment_count"] == 3
    assert "space_id" not in data


def test_publish_rejects_chat_channel(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    post = _post_to_channel(client, token, space, "chat", content="Hey all", content_type="ooc")

    resp = _publish_space(client, token, space["id"], [post["id"]])
    assert resp.status_code == 400


def test_publish_rejects_planning_channel(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    post = _post_to_channel(client, token, space, "planning", content="Arc notes", content_type="ooc")

    resp = _publish_space(client, token, space["id"], [post["id"]])
    assert resp.status_code == 400


def test_publish_rejects_cross_space_post(client):
    t1 = _make_user(client, 1)
    t2 = _make_user(client, 2)
    space_a = _create_space(client, t1, name="Space A")
    space_b = _create_space(client, t2, name="Space B")

    post_in_a = _post_to_channel(client, t1, space_a, "story", content="Post in A")

    # t2 tries to publish space B using a post that belongs to space A
    resp = _publish_space(client, t2, space_b["id"], [post_in_a["id"]])
    assert resp.status_code == 400


def test_publish_rejects_duplicate_ids(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    post = _post_to_channel(client, token, space, "story", content="Once.")

    resp = _publish_space(client, token, space["id"], [post["id"], post["id"]])
    assert resp.status_code == 400


def test_publish_rejects_empty_list(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    resp = _publish_space(client, token, space["id"], [])
    assert resp.status_code == 400


def test_published_story_not_leaking_internal_fields(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    post = _post_to_channel(client, token, space, "story", content="Visible content")
    publish_resp = _publish_space(client, token, space["id"], [post["id"]])
    assert publish_resp.status_code == 201
    published_id = publish_resp.json()["id"]

    resp = client.get(f"/published-stories/{published_id}", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "space_id" not in data
    for segment in data.get("segments", []):
        assert "source_post_id" not in segment


def test_get_published_requires_auth(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    post = _post_to_channel(client, token, space, "story", content="Auth-gated story")
    publish_resp = _publish_space(client, token, space["id"], [post["id"]])
    assert publish_resp.status_code == 201
    published_id = publish_resp.json()["id"]

    resp = client.get(f"/published-stories/{published_id}")
    assert resp.status_code == 403  # HTTPBearer raises 403 for missing token, consistent with all other auth guards


def test_published_segments_order(client):
    token = _make_user(client, 1)
    space = _create_space(client, token)
    ch = _get_channel(client, token, space, "story")

    post_ids = []
    for msg in ["First", "Second", "Third"]:
        p = client.post(
            f"/story-spaces/{space['id']}/channels/{ch['id']}/posts",
            json={"content": msg, "content_type": "ic"},
            headers=auth_headers(token),
        )
        assert p.status_code == 201
        post_ids.append(p.json()["id"])

    publish_resp = _publish_space(client, token, space["id"], post_ids)
    assert publish_resp.status_code == 201
    published_id = publish_resp.json()["id"]

    resp = client.get(f"/published-stories/{published_id}", headers=auth_headers(token))
    assert resp.status_code == 200
    segments = resp.json()["segments"]
    assert [s["position"] for s in segments] == [1, 2, 3]


def test_segment_content_snapshot(client, db_session):
    token = _make_user(client, 1)
    space = _create_space(client, token)

    original_content = "Original story content — must not change."
    post = _post_to_channel(client, token, space, "story", content=original_content)
    post_id = post["id"]

    publish_resp = _publish_space(client, token, space["id"], [post_id])
    assert publish_resp.status_code == 201
    published_id = publish_resp.json()["id"]

    # Mutate the source post directly via DB — simulates a future edit
    from app.models.story_space import StorySpacePost
    source = db_session.query(StorySpacePost).filter(StorySpacePost.id == post_id).first()
    source.content = "Mutated — should NOT appear in published snapshot"
    db_session.commit()

    resp = client.get(f"/published-stories/{published_id}", headers=auth_headers(token))
    assert resp.status_code == 200
    segments = resp.json()["segments"]
    assert segments[0]["content"] == original_content
