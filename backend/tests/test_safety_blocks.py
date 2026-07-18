"""Tests for the safety blocks feature (Gate 3B).

Covers:
- Block / unblock CRUD
- Messaging: send blocked → 403, thread blocked → 404, list filtered
- Feed: blocked author's posts excluded
- Comments: blocked author's comments excluded
- Reverse-direction enforcement (B blocks A → A also affected)
"""
import pytest
from fastapi.testclient import TestClient


# ── Helpers ──────────────────────────────────────────────────────────────────

def _register(client: TestClient, email: str, username: str) -> dict:
    """Register a user and return {id, token}."""
    r = client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "Password123!"},
    )
    assert r.status_code == 201, r.json()
    user_id = r.json()["id"]
    r2 = client.post("/auth/login", json={"email": email, "password": "Password123!"})
    assert r2.status_code == 200, r2.json()
    return {"id": user_id, "token": r2.json()["access_token"]}


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_character(client: TestClient, token: str, name: str) -> int:
    r = client.post("/characters/", json={"name": name}, headers=_h(token))
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _create_realm(client: TestClient, token: str, name: str, slug: str) -> int:
    r = client.post(
        "/realms",
        json={"name": name, "slug": slug, "description": "test realm"},
        headers=_h(token),
    )
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _join_realm(client: TestClient, token: str, realm_id: int) -> None:
    r = client.post(f"/realms/{realm_id}/join", headers=_h(token))
    assert r.status_code in (200, 201), r.json()


# Posts are authored by characters (Sprint 33). One character per account:
# create on first use, reuse the existing one after.
def _character_for(client: TestClient, token: str) -> int:
    r = client.post("/characters/", json={"name": "AuthorChar"}, headers=_h(token))
    if r.status_code == 201:
        return r.json()["id"]
    owned = client.get("/characters/", headers=_h(token))
    assert owned.status_code == 200, owned.text
    assert owned.json(), "no character available and creation was refused"
    return owned.json()[0]["id"]


def _create_post(client: TestClient, token: str, realm_id: int, content: str = "Hello") -> int:
    r = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "character_id": _character_for(client, token)},
        headers=_h(token),
    )
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _create_comment(
    client: TestClient, token: str, post_id: int, body: str = "Nice",
    character_id: int | None = None,
) -> int:
    payload: dict = {"content": body}
    if character_id is not None:
        payload["character_id"] = character_id
    r = client.post(
        f"/comments/posts/{post_id}/comments",
        json=payload,
        headers=_h(token),
    )
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _open_conversation(client: TestClient, token: str, from_char: int, to_char: int) -> int:
    r = client.post(
        "/messages/conversations",
        json={"from_character_id": from_char, "to_character_id": to_char},
        headers=_h(token),
    )
    assert r.status_code == 200, r.json()
    return r.json()["id"]


def _block(client: TestClient, token: str, user_id: int):
    return client.post(f"/blocks/{user_id}", headers=_h(token))


def _unblock(client: TestClient, token: str, user_id: int):
    return client.delete(f"/blocks/{user_id}", headers=_h(token))


# ── Block / unblock CRUD ─────────────────────────────────────────────────────

def test_block_user_201(client: TestClient):
    a = _register(client, "a@t.com", "user_a")
    b = _register(client, "b@t.com", "user_b")

    r = _block(client, a["token"], b["id"])
    assert r.status_code == 201
    data = r.json()
    assert data["blocked"]["id"] == b["id"]
    assert data["blocked"]["username"] == "user_b"


def test_block_self_returns_400(client: TestClient):
    a = _register(client, "c@t.com", "user_c")

    r = _block(client, a["token"], a["id"])
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_block"


def test_block_unknown_user_404(client: TestClient):
    a = _register(client, "d@t.com", "user_d")

    r = _block(client, a["token"], 99999)
    assert r.status_code == 404


def test_block_idempotent_same_id(client: TestClient):
    a = _register(client, "e@t.com", "user_e")
    b = _register(client, "f@t.com", "user_f")

    r1 = _block(client, a["token"], b["id"])
    r2 = _block(client, a["token"], b["id"])
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


def test_unblock_204(client: TestClient):
    a = _register(client, "g@t.com", "user_g")
    b = _register(client, "h@t.com", "user_h")

    _block(client, a["token"], b["id"])
    r = _unblock(client, a["token"], b["id"])
    assert r.status_code == 204


def test_unblock_idempotent_when_not_blocked(client: TestClient):
    a = _register(client, "i@t.com", "user_i")
    b = _register(client, "j@t.com", "user_j")

    r = _unblock(client, a["token"], b["id"])
    assert r.status_code == 204


def test_list_blocks(client: TestClient):
    a = _register(client, "k@t.com", "user_k")
    b = _register(client, "l@t.com", "user_l")

    _block(client, a["token"], b["id"])
    r = client.get("/blocks", headers=_h(a["token"]))
    assert r.status_code == 200
    ids = [entry["blocked"]["id"] for entry in r.json()]
    assert b["id"] in ids


def test_list_blocks_empty_after_unblock(client: TestClient):
    a = _register(client, "m@t.com", "user_m")
    b = _register(client, "n@t.com", "user_n")

    _block(client, a["token"], b["id"])
    _unblock(client, a["token"], b["id"])
    r = client.get("/blocks", headers=_h(a["token"]))
    assert r.status_code == 200
    assert r.json() == []


# ── Messaging enforcement ────────────────────────────────────────────────────

def test_send_message_blocked_403(client: TestClient):
    """A blocks B; A tries to send a message in their conversation → 403."""
    a = _register(client, "ma@t.com", "msg_a")
    b = _register(client, "mb@t.com", "msg_b")
    char_a = _create_character(client, a["token"], "CharA")
    char_b = _create_character(client, b["token"], "CharB")

    # Establish conversation before blocking
    conv_id = _open_conversation(client, a["token"], char_a, char_b)

    # A blocks B
    _block(client, a["token"], b["id"])

    r = client.post(
        f"/messages/conversations/{conv_id}/messages",
        json={"sender_character_id": char_a, "body": "hi"},
        headers=_h(a["token"]),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "blocked"


def test_send_message_reverse_block_403(client: TestClient):
    """B blocks A; A still cannot send messages (reverse enforcement)."""
    a = _register(client, "rc@t.com", "rev_a")
    b = _register(client, "rd@t.com", "rev_b")
    char_a = _create_character(client, a["token"], "RevCharA")
    char_b = _create_character(client, b["token"], "RevCharB")

    conv_id = _open_conversation(client, a["token"], char_a, char_b)

    # B blocks A (reverse direction)
    _block(client, b["token"], a["id"])

    r = client.post(
        f"/messages/conversations/{conv_id}/messages",
        json={"sender_character_id": char_a, "body": "hi"},
        headers=_h(a["token"]),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "blocked"


def test_get_message_thread_blocked_404(client: TestClient):
    """A blocks B; fetching the conversation thread returns 404."""
    a = _register(client, "th@t.com", "thr_a")
    b = _register(client, "ti@t.com", "thr_b")
    char_a = _create_character(client, a["token"], "ThrCharA")
    char_b = _create_character(client, b["token"], "ThrCharB")

    conv_id = _open_conversation(client, a["token"], char_a, char_b)

    _block(client, a["token"], b["id"])

    r = client.get(
        f"/messages/conversations/{conv_id}/messages",
        headers=_h(a["token"]),
    )
    assert r.status_code == 404


def test_conversation_list_excludes_blocked(client: TestClient):
    """A blocks B; the conversation does not appear in A's list."""
    a = _register(client, "cl@t.com", "clist_a")
    b = _register(client, "cm@t.com", "clist_b")
    char_a = _create_character(client, a["token"], "CListCharA")
    char_b = _create_character(client, b["token"], "CListCharB")

    conv_id = _open_conversation(client, a["token"], char_a, char_b)

    _block(client, a["token"], b["id"])

    r = client.get("/messages/conversations", headers=_h(a["token"]))
    assert r.status_code == 200
    conv_ids = [c["id"] for c in r.json()]
    assert conv_id not in conv_ids


# ── Feed enforcement ─────────────────────────────────────────────────────────

def test_feed_excludes_blocked_author(client: TestClient):
    """A blocks B; B's posts do not appear in A's feed."""
    a = _register(client, "fa@t.com", "feed_a")
    b = _register(client, "fb@t.com", "feed_b")

    realm_id = _create_realm(client, a["token"], "TestRealm", "test-realm")
    _join_realm(client, b["token"], realm_id)

    post_id = _create_post(client, b["token"], realm_id, "B's post")

    # Before blocking, A sees B's post
    r = client.get("/posts/feed", headers=_h(a["token"]))
    assert r.status_code == 200
    assert any(p["id"] == post_id for p in r.json())

    _block(client, a["token"], b["id"])

    # After blocking, B's post is gone from A's feed
    r = client.get("/posts/feed", headers=_h(a["token"]))
    assert r.status_code == 200
    assert not any(p["id"] == post_id for p in r.json())


def test_feed_reverse_block_excludes_author(client: TestClient):
    """B blocks A; B's posts are excluded from A's feed (reverse enforcement)."""
    a = _register(client, "fc@t.com", "feedr_a")
    b = _register(client, "fd@t.com", "feedr_b")

    realm_id = _create_realm(client, a["token"], "RevRealm", "rev-realm")
    _join_realm(client, b["token"], realm_id)

    post_id = _create_post(client, b["token"], realm_id, "B's post")

    # B blocks A
    _block(client, b["token"], a["id"])

    r = client.get("/posts/feed", headers=_h(a["token"]))
    assert r.status_code == 200
    assert not any(p["id"] == post_id for p in r.json())


# ── Comments enforcement ─────────────────────────────────────────────────────

def test_comments_excludes_blocked_author(client: TestClient):
    """A blocks B; B's comments are absent when A lists comments."""
    a = _register(client, "ca@t.com", "cmt_a")
    b = _register(client, "cb@t.com", "cmt_b")

    realm_id = _create_realm(client, a["token"], "CmtRealm", "cmt-realm")
    _join_realm(client, b["token"], realm_id)

    post_id = _create_post(client, a["token"], realm_id, "A's post")
    cmt_id = _create_comment(client, b["token"], post_id, "B's comment")

    # Without auth / before block: comment is visible
    r = client.get(f"/comments/posts/{post_id}/comments")
    assert r.status_code == 200
    assert any(c["id"] == cmt_id for c in r.json())

    # A blocks B
    _block(client, a["token"], b["id"])

    # Authenticated as A: B's comment is filtered
    r = client.get(
        f"/comments/posts/{post_id}/comments", headers=_h(a["token"])
    )
    assert r.status_code == 200
    assert not any(c["id"] == cmt_id for c in r.json())


def test_comments_unauthenticated_still_works(client: TestClient):
    """Unauthenticated requests to list comments still succeed (no filter)."""
    a = _register(client, "cc@t.com", "cmt_c")

    realm_id = _create_realm(client, a["token"], "OpenRealm", "open-realm")
    post_id = _create_post(client, a["token"], realm_id, "Open post")
    # A owns a character (created by _create_post), so the comment must be
    # character-attributed (Sprint 33).
    cmt_id = _create_comment(
        client, a["token"], post_id, "Open comment",
        character_id=_character_for(client, a["token"]),
    )

    r = client.get(f"/comments/posts/{post_id}/comments")
    assert r.status_code == 200
    assert any(c["id"] == cmt_id for c in r.json())
