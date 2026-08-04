"""Wanderer identity, the Writer Unlock paywall, and public attribution.

Covers the corrective sprint's product rules:

* a Wanderer is a complete account type — it cannot reach character creation
  through the API, entitlement or not-yet-paid;
* the Wanderer username is public, editable and validated;
* the internal user id is untouched by a rename;
* comments attribute a Wanderer by username + sigil and a Writer by character
  only, never leaking the private account username.
"""
import pytest
from datetime import datetime, timedelta

from tests.conftest import (
    TestingSessionLocal,
    auth_headers,
    ensure_character,
    get_auth_token,
    grant_writer_unlock,
    make_admin,
)

_CHAR = {"name": "Test Hero", "species": "human"}


def _register(client, email: str, username: str) -> str:
    return get_auth_token(client, email=email, username=username)


def _me(client, token: str) -> dict:
    resp = client.get("/users/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_realm(client, token: str, slug: str) -> int:
    resp = client.post(
        "/realms/",
        json={"name": f"Realm {slug}", "slug": slug, "is_public": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_post(client, token: str, realm_id: int, character_id: int | None) -> int:
    body = {"content": "A post to comment on.", "content_type": "ooc"}
    if character_id is not None:
        body["character_id"] = character_id
    resp = client.post(
        f"/posts/realms/{realm_id}/posts", json=body, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── Writer Unlock: the character-creation paywall ────────────────────────────


@pytest.mark.writer_unlock_enforced
def test_unpaid_wanderer_cannot_create_character_via_api(client):
    """Direct API access to character creation is denied without the unlock."""
    token = _register(client, "wanderer1@test.com", "wanderer_one")

    resp = client.post("/characters/", json=_CHAR, headers=auth_headers(token))

    assert resp.status_code == 403
    assert "Writer Unlock" in resp.json()["detail"]
    assert client.get("/characters/", headers=auth_headers(token)).json() == []


@pytest.mark.writer_unlock_enforced
def test_me_reports_wanderer_cannot_create_character(client):
    """/me tells the client the truth, so the UI needn't reconstruct the rule."""
    token = _register(client, "wanderer2@test.com", "wanderer_two")

    me = _me(client, token)

    assert me["writer_unlocked"] is False
    assert me["can_create_character"] is False
    assert me["character_count"] == 0


@pytest.mark.writer_unlock_enforced
def test_unlocked_writer_may_create_exactly_one_character(client):
    """A paid account creates one character — and only one."""
    token = _register(client, "writer1@test.com", "writer_one")
    grant_writer_unlock("writer1@test.com")

    assert _me(client, token)["can_create_character"] is True

    first = client.post("/characters/", json=_CHAR, headers=auth_headers(token))
    assert first.status_code == 201, first.text

    second = client.post(
        "/characters/", json={"name": "Second", "species": "elf"}, headers=auth_headers(token)
    )
    assert second.status_code == 403
    assert "1 character per account" in second.json()["detail"]


@pytest.mark.writer_unlock_enforced
def test_founder_keeps_creator_access_and_multi_character_switching(client):
    """Founder/admin accounts are exempt from the paywall AND the one-character
    limit, and can still switch which character they are being."""
    token = _register(client, "founder@test.com", "founder_acct")
    make_admin("founder@test.com")

    assert _me(client, token)["can_create_character"] is True

    first = client.post("/characters/", json={"name": "Alpha", "species": "human"}, headers=auth_headers(token))
    second = client.post("/characters/", json={"name": "Beta", "species": "human"}, headers=auth_headers(token))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    for char in (first.json(), second.json()):
        switched = client.patch(
            "/users/me/active-character",
            json={"character_id": char["id"]},
            headers=auth_headers(token),
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["active_character"]["name"] == char["name"]


@pytest.mark.writer_unlock_enforced
def test_character_creation_requires_authentication(client):
    """No token, no character — the gate is never reachable anonymously."""
    assert client.post("/characters/", json=_CHAR).status_code == 403


# ── Wanderer username: editing, validation, ownership ────────────────────────


def test_wanderer_can_update_own_username(client):
    token = _register(client, "rename1@test.com", "rename_one")

    resp = client.patch(
        "/users/me/username", json={"username": "Riverwalker"}, headers=auth_headers(token)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "Riverwalker"
    assert _me(client, token)["username"] == "Riverwalker"


def test_username_change_does_not_change_internal_user_id(client):
    token = _register(client, "rename2@test.com", "rename_two")
    original_id = _me(client, token)["id"]

    resp = client.patch(
        "/users/me/username", json={"username": "NewName"}, headers=auth_headers(token)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == original_id
    assert _me(client, token)["id"] == original_id


def test_username_is_trimmed(client):
    token = _register(client, "rename3@test.com", "rename_three")

    resp = client.patch(
        "/users/me/username", json={"username": "  Trimmed  "}, headers=auth_headers(token)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "Trimmed"


def test_duplicate_username_rejected_case_insensitively(client):
    _register(client, "taken@test.com", "TakenName")
    token = _register(client, "other@test.com", "other_acct")

    resp = client.patch(
        "/users/me/username", json={"username": "takenname"}, headers=auth_headers(token)
    )

    assert resp.status_code == 409
    assert "taken" in resp.json()["detail"].lower()
    assert _me(client, token)["username"] == "other_acct"


@pytest.mark.parametrize(
    "bad",
    [
        "ab",                        # too short
        "x" * 25,                    # too long
        "has space",                 # whitespace inside
        "bad!chars",                 # symbol outside the safe set
        "_leading",                  # separator at the edge
        "trailing.",                 # separator at the edge
        "double__sep",               # doubled separator
        "admin",                     # reserved
        "Ficshon",                   # reserved, case-insensitively
        "",                          # empty
    ],
)
def test_invalid_and_reserved_usernames_are_rejected(client, bad):
    token = _register(client, "validate@test.com", "validate_acct")

    resp = client.patch(
        "/users/me/username", json={"username": bad}, headers=auth_headers(token)
    )

    # 400 from the shared validator; 422 for the empty string, which the request
    # schema rejects before the validator is reached. Either way: refused, with
    # a message, and the account keeps its name.
    assert resp.status_code in (400, 422), resp.text
    assert resp.json()["detail"]
    assert _me(client, token)["username"] == "validate_acct"


def test_username_change_requires_authentication(client):
    assert client.patch("/users/me/username", json={"username": "Nobody"}).status_code == 403


def test_user_cannot_alter_another_users_username(client):
    """The endpoint updates the caller and only the caller — there is no target
    parameter, and smuggling one in changes nothing about the other account."""
    victim_token = _register(client, "victim@test.com", "victim_acct")
    victim_id = _me(client, victim_token)["id"]
    attacker_token = _register(client, "attacker@test.com", "attacker_acct")

    resp = client.patch(
        "/users/me/username",
        json={"username": "Hijacked", "user_id": victim_id, "id": victim_id},
        headers=auth_headers(attacker_token),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] != victim_id
    assert _me(client, victim_token)["username"] == "victim_acct"


def test_username_change_is_rate_limited_by_cooldown(client):
    token = _register(client, "cooldown@test.com", "cooldown_acct")

    first = client.patch(
        "/users/me/username", json={"username": "FirstPick"}, headers=auth_headers(token)
    )
    assert first.status_code == 200, first.text
    assert first.json()["username_change_available_at"] is not None

    second = client.patch(
        "/users/me/username", json={"username": "SecondPick"}, headers=auth_headers(token)
    )

    assert second.status_code == 429
    assert _me(client, token)["username"] == "FirstPick"


def test_username_cooldown_expires(client):
    """The cooldown is a wait, not a one-shot lock."""
    from app.models.user import User

    token = _register(client, "cooldown2@test.com", "cooldown_two")
    assert client.patch(
        "/users/me/username", json={"username": "Early"}, headers=auth_headers(token)
    ).status_code == 200

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "cooldown2@test.com").first()
        user.username_changed_at = datetime.utcnow() - timedelta(days=15)
        db.commit()
    finally:
        db.close()

    resp = client.patch(
        "/users/me/username", json={"username": "Later"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == "Later"


def test_registration_enforces_the_same_username_rules(client):
    """One rule, two doors: a name that can't be registered can't be renamed to."""
    resp = client.post(
        "/auth/register",
        json={"email": "reserved@test.com", "username": "admin", "password": "testpass!123"},
    )
    assert resp.status_code == 400
    assert "reserved" in resp.json()["detail"].lower()


def test_registration_rejects_case_variant_of_existing_username(client):
    _register(client, "first@test.com", "Duplicated")

    resp = client.post(
        "/auth/register",
        json={"email": "second@test.com", "username": "duplicated", "password": "testpass!123"},
    )

    assert resp.status_code == 400
    assert "taken" in resp.json()["detail"].lower()


# ── Public attribution ───────────────────────────────────────────────────────


def test_wanderer_comment_shows_username_and_account_sigil(client):
    """A Wanderer's public identity is their username + sigil, not 'Account'."""
    writer_token = _register(client, "poster@test.com", "poster_acct")
    realm_id = _create_realm(client, writer_token, "wanderer-attr")
    character_id = ensure_character(client, writer_token, name="Post Author")
    post_id = _create_post(client, writer_token, realm_id, character_id)

    wanderer_token = _register(client, "commenter@test.com", "commenter_acct")
    sigil = "data:image/svg+xml,%3Csvg/%3E"
    assert client.patch(
        "/users/me", json={"avatar_url": sigil}, headers=auth_headers(wanderer_token)
    ).status_code == 200
    assert client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "Hello from the road."},
        headers=auth_headers(wanderer_token),
    ).status_code == 201

    # Read as a third party — attribution must hold for any viewer.
    viewer_token = _register(client, "viewer@test.com", "viewer_acct")
    comments = client.get(
        f"/comments/posts/{post_id}/comments", headers=auth_headers(viewer_token)
    ).json()

    assert len(comments) == 1
    assert comments[0]["author_username"] == "commenter_acct"
    assert comments[0]["author_avatar_url"] == sigil
    assert comments[0]["character_name"] is None


def test_wanderer_comment_follows_a_username_change(client):
    """Existing activity resolves to the *current* username — no stale copies."""
    writer_token = _register(client, "poster2@test.com", "poster_two")
    realm_id = _create_realm(client, writer_token, "rename-attr")
    post_id = _create_post(
        client, writer_token, realm_id, ensure_character(client, writer_token, "Author Two")
    )

    wanderer_token = _register(client, "renamer@test.com", "renamer_acct")
    assert client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "Before the rename."},
        headers=auth_headers(wanderer_token),
    ).status_code == 201

    assert client.patch(
        "/users/me/username", json={"username": "AfterRename"}, headers=auth_headers(wanderer_token)
    ).status_code == 200

    viewer_token = _register(client, "viewer2@test.com", "viewer_two")
    comments = client.get(
        f"/comments/posts/{post_id}/comments", headers=auth_headers(viewer_token)
    ).json()

    assert comments[0]["author_username"] == "AfterRename"


def test_writer_comment_exposes_character_only(client):
    """A Writer's public output carries the character — never the account."""
    writer_token = _register(client, "poster3@test.com", "poster_three")
    realm_id = _create_realm(client, writer_token, "writer-attr")
    post_id = _create_post(
        client, writer_token, realm_id, ensure_character(client, writer_token, "Author Three")
    )

    commenter_token = _register(client, "charcommenter@test.com", "charcommenter")
    character_id = ensure_character(client, commenter_token, name="Speaking Character")
    assert client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "In character.", "character_id": character_id},
        headers=auth_headers(commenter_token),
    ).status_code == 201

    viewer_token = _register(client, "viewer3@test.com", "viewer_three")
    body = client.get(
        f"/comments/posts/{post_id}/comments", headers=auth_headers(viewer_token)
    ).text
    comments = client.get(
        f"/comments/posts/{post_id}/comments", headers=auth_headers(viewer_token)
    ).json()

    written = next(c for c in comments if c["content"] == "In character.")
    assert written["character_name"] == "Speaking Character"
    assert written["author_username"] is None
    assert written["author_avatar_url"] is None
    assert written["author_user_id"] is None
    # Belt and braces: the private account name appears nowhere in the payload.
    assert "charcommenter" not in body


def test_writer_post_does_not_expose_account_username(client):
    """Same rule on the feed: character attribution, no account identity."""
    writer_token = _register(client, "feedwriter@test.com", "feedwriter_acct")
    realm_id = _create_realm(client, writer_token, "feed-attr")
    character_id = ensure_character(client, writer_token, name="Feed Character")
    _create_post(client, writer_token, realm_id, character_id)

    viewer_token = _register(client, "feedviewer@test.com", "feedviewer")
    assert client.post(
        f"/realms/{realm_id}/join", headers=auth_headers(viewer_token)
    ).status_code in (200, 201)
    feed = client.get("/posts/feed", headers=auth_headers(viewer_token))
    assert feed.status_code == 200, feed.text

    mine = [p for p in feed.json() if p.get("character_name") == "Feed Character"]
    assert mine, "expected the character's post in the feed"
    for post in mine:
        assert post["author_username"] is None
        assert post["author_user_id"] is None
    assert "feedwriter_acct" not in feed.text
