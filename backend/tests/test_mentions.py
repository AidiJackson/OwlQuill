"""Tests for @mentions + notifications feature."""
import pytest

from tests.conftest import get_auth_token, auth_headers
from app.services.mentions import parse_mention_texts


# ── Unit tests: parse_mention_texts ─────────────────────────────────────────

def test_parse_basic():
    result = parse_mention_texts("hey @alice and @bob")
    assert result == ["@alice", "@bob"]


def test_parse_dedup():
    result = parse_mention_texts("@alice @alice")
    assert result == ["@alice"]


def test_parse_no_mentions():
    result = parse_mention_texts("hello world")
    assert result == []


def test_parse_max_20():
    # 25 unique mentions — should return only 20
    text = " ".join(f"@user{i}" for i in range(25))
    result = parse_mention_texts(text)
    assert len(result) == 20


# ── Integration tests ─────────────────────────────────────────────────────────
#
# Sprint 33 (character-first): posts are authored by characters, mentions
# resolve to PUBLIC CHARACTERS only, and username mentions stay unresolved —
# no /u/ link, no existence confirmation, no notification.

def _create_realm(client, headers):
    """Helper: create a realm and return its id."""
    resp = client.post(
        "/realms/",
        json={"name": "Test Realm", "slug": "test-realm", "is_public": True},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _create_character(client, headers, name="AuthorChar"):
    """Helper: create a public character and return its id."""
    resp = client.post(
        "/characters/",
        json={"name": name, "visibility": "public"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_post(client, headers, realm_id, content, character_id):
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "content_type": "ic", "character_id": character_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_post_create_with_mention_creates_row(client, db_session):
    """Post mentioning a public character creates a PostMention row."""
    from app.models.post_mention import PostMention

    token_a = get_auth_token(client, "author@test.com", "authoruser")
    token_b = get_auth_token(client, "mentioned@test.com", "mentioneduser")
    hdrs_a = auth_headers(token_a)
    hdrs_b = auth_headers(token_b)

    _create_character(client, hdrs_b, name="Mentioned")
    author_char = _create_character(client, hdrs_a)
    realm_id = _create_realm(client, hdrs_a)
    client.post(f"/realms/{realm_id}/join", headers=hdrs_a)

    data = _create_post(client, hdrs_a, realm_id, "Hello @Mentioned!", author_char)

    pm = db_session.query(PostMention).filter(PostMention.post_id == data["id"]).first()
    assert pm is not None
    assert pm.mention_text == "@Mentioned"
    assert pm.mentioned_character_id is not None


def test_post_response_includes_mentions(client, db_session):
    """The post response includes the mentions array with resolved data."""
    token_a = get_auth_token(client, "author2@test.com", "authoruser2")
    token_b = get_auth_token(client, "mentioned2@test.com", "mentioneduser2")
    hdrs_a = auth_headers(token_a)
    hdrs_b = auth_headers(token_b)

    target_char = _create_character(client, hdrs_b, name="Nyra")
    author_char = _create_character(client, hdrs_a)
    realm_id = _create_realm(client, hdrs_a)
    client.post(f"/realms/{realm_id}/join", headers=hdrs_a)

    data = _create_post(client, hdrs_a, realm_id, "Hey @Nyra, what's up?", author_char)

    assert "mentions" in data
    assert len(data["mentions"]) == 1
    m = data["mentions"][0]
    assert m["mention_text"] == "@Nyra"
    assert m["target_type"] == "character"
    assert m["url"] == f"/characters/{target_char}"
    assert m["display_name"] == "Nyra"


def test_username_mention_stays_unresolved(client, db_session):
    """A username mention resolves to nothing — accounts are never targets."""
    token_a = get_auth_token(client, "author2b@test.com", "authoruser2b")
    token_b = get_auth_token(client, "mentioned2b@test.com", "mentioneduser2b")
    hdrs_a = auth_headers(token_a)

    author_char = _create_character(client, hdrs_a)
    realm_id = _create_realm(client, hdrs_a)
    client.post(f"/realms/{realm_id}/join", headers=hdrs_a)

    data = _create_post(
        client, hdrs_a, realm_id, "Hey @mentioneduser2b!", author_char
    )
    assert len(data["mentions"]) == 1
    m = data["mentions"][0]
    assert m["target_type"] == "unresolved"
    assert m["url"] == ""
    assert m["target_id"] is None


def test_unresolved_mention_does_not_break(client, db_session):
    """A mention to a non-existent name still creates the post successfully."""
    token_a = get_auth_token(client, "author3@test.com", "authoruser3")
    hdrs_a = auth_headers(token_a)

    author_char = _create_character(client, hdrs_a)
    realm_id = _create_realm(client, hdrs_a)
    client.post(f"/realms/{realm_id}/join", headers=hdrs_a)

    data = _create_post(client, hdrs_a, realm_id, "Hey @nobody_exists!", author_char)
    assert len(data["mentions"]) == 1
    assert data["mentions"][0]["target_type"] == "unresolved"
    assert data["mentions"][0]["url"] == ""


def test_self_mention_no_notification(client, db_session):
    """Mentioning your own character does not generate a notification."""
    from app.models.notification import Notification

    token = get_auth_token(client, "self@test.com", "selfuser")
    hdrs = auth_headers(token)

    own_char = _create_character(client, hdrs, name="SelfChar")
    realm_id = _create_realm(client, hdrs)
    client.post(f"/realms/{realm_id}/join", headers=hdrs)

    _create_post(client, hdrs, realm_id, "I am @SelfChar!", own_char)

    from app.models.user import User
    user = db_session.query(User).filter(User.username == "selfuser").first()
    if user:
        count = db_session.query(Notification).filter(
            Notification.user_id == user.id,
            Notification.type == "mention",
        ).count()
        assert count == 0


def test_character_mention_notifies_owner(client, db_session):
    """Mentioning a public character notifies its owner."""
    from app.models.notification import Notification
    from app.models.user import User

    token_owner = get_auth_token(client, "charowner@test.com", "charowner")
    token_author = get_auth_token(client, "charauthor@test.com", "charauthor")
    hdrs_owner = auth_headers(token_owner)
    hdrs_author = auth_headers(token_author)

    _create_character(client, hdrs_owner, name="Elara")
    author_char = _create_character(client, hdrs_author)
    realm_id = _create_realm(client, hdrs_author)
    client.post(f"/realms/{realm_id}/join", headers=hdrs_author)

    _create_post(client, hdrs_author, realm_id, "I see @Elara walking by!", author_char)

    owner = db_session.query(User).filter(User.username == "charowner").first()
    assert owner is not None
    notif = db_session.query(Notification).filter(
        Notification.user_id == owner.id,
        Notification.type == "mention",
    ).first()
    assert notif is not None


def test_unread_count_endpoint(client, db_session):
    """GET /notifications/unread-count returns correct count."""
    token_a = get_auth_token(client, "notifauthor@test.com", "notifauthor")
    token_b = get_auth_token(client, "notifrecv@test.com", "notifrecv")
    hdrs_a = auth_headers(token_a)
    hdrs_b = auth_headers(token_b)

    _create_character(client, hdrs_b, name="Recva")
    author_char = _create_character(client, hdrs_a)
    realm_id = _create_realm(client, hdrs_a)
    client.post(f"/realms/{realm_id}/join", headers=hdrs_a)

    _create_post(client, hdrs_a, realm_id, "Hey @Recva!", author_char)

    count_resp = client.get("/notifications/unread-count", headers=hdrs_b)
    assert count_resp.status_code == 200, count_resp.text
    assert count_resp.json()["count"] >= 1


def test_mark_notification_read(client, db_session):
    """PATCH /notifications/{id}/read marks a notification as read."""
    token_a = get_auth_token(client, "markauthor@test.com", "markauthor")
    token_b = get_auth_token(client, "markrecv@test.com", "markrecv")
    hdrs_a = auth_headers(token_a)
    hdrs_b = auth_headers(token_b)

    _create_character(client, hdrs_b, name="Markrecva")
    author_char = _create_character(client, hdrs_a)
    realm_id = _create_realm(client, hdrs_a)
    client.post(f"/realms/{realm_id}/join", headers=hdrs_a)

    _create_post(client, hdrs_a, realm_id, "Hello @Markrecva!", author_char)

    notif_resp = client.get("/notifications", headers=hdrs_b)
    assert notif_resp.status_code == 200, notif_resp.text
    notifications = notif_resp.json()
    assert len(notifications) >= 1

    notif_id = notifications[0]["id"]
    assert notifications[0]["is_read"] is False

    patch_resp = client.patch(f"/notifications/{notif_id}/read", headers=hdrs_b)
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["is_read"] is True
