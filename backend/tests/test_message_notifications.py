"""Phase 7.2B — direct message notifications, pinned.

``message_received`` is written through ``services/notifications`` in the same
transaction as the message:

1. **The other account only.** The sender's account is never notified, which
   also silences a conversation between two characters one account owns.
2. **Grouped while unread.** One UNREAD row per recipient and conversation; a
   further message updates it (count + 1, timestamp moved forward). Once read,
   the next message starts a new row.
3. **No text, no account.** The payload carries conversation and character
   ids and name snapshots and a count — never a message body or a username.
4. **Existing rules decide.** A send refused for a block, a non-participant or
   a character the caller does not own writes nothing.
5. **Reading is explicit and narrow.** ``POST /messages/conversations/{id}/read``
   is admitted exactly as the thread is and marks only the caller's
   ``message_received`` rows for that conversation. ``GET`` never writes.
6. **The unread count narrows, never widens.** ``?type=`` filters the caller's
   own rows.
"""
import json
from datetime import datetime, timedelta

from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth_headers, get_auth_token, make_seeder


# ── helpers ──────────────────────────────────────────────────────────────────

def _character(client, headers, name):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _user_id(db, username):
    user = db.query(User).filter(User.username == username).first()
    assert user is not None
    return user.id


def _conversation(client, headers, from_id, to_id):
    resp = client.post(
        "/messages/conversations",
        json={"from_character_id": from_id, "to_character_id": to_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _send(client, headers, conv_id, sender_id, body="Meet me at the lighthouse.", expect=201):
    resp = client.post(
        f"/messages/conversations/{conv_id}/messages",
        json={"sender_character_id": sender_id, "body": body},
        headers=headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _rows(db, user_id, type_="message_received"):
    db.expire_all()
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.type == type_)
        .order_by(Notification.id)
        .all()
    )


def _all_rows(db, user_id):
    db.expire_all()
    return db.query(Notification).filter(Notification.user_id == user_id).all()


def _payload(notif):
    return json.loads(notif.payload)


def _mark_read(client, headers, conv_id):
    return client.post(f"/messages/conversations/{conv_id}/read", headers=headers)


def _unread(client, headers, type_=None):
    url = "/notifications/unread-count" + (f"?type={type_}" if type_ else "")
    resp = client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["count"]


def _scene(client, db_session):
    """Mara (sender account) and Angelo (recipient account), one conversation."""
    tok_s = get_auth_token(client, "m72sender@test.com", "m72sender")
    tok_r = get_auth_token(client, "m72recip@test.com", "m72recip")
    h_s, h_r = auth_headers(tok_s), auth_headers(tok_r)
    mara = _character(client, h_s, "Mara")
    angelo = _character(client, h_r, "Angelo")
    conv = _conversation(client, h_s, mara, angelo)
    return {
        "h_s": h_s, "h_r": h_r,
        "sender_id": _user_id(db_session, "m72sender"),
        "recip_id": _user_id(db_session, "m72recip"),
        "mara": mara, "angelo": angelo, "conv": conv,
    }


def _third(client, db_session):
    tok = get_auth_token(client, "m72third@test.com", "m72third")
    h = auth_headers(tok)
    return {"h": h, "id": _user_id(db_session, "m72third"), "char": _character(client, h, "Wren")}


# ── 1. who is told, and what ─────────────────────────────────────────────────

def test_a_message_notifies_the_other_account_with_ids_and_snapshots_only(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"], "A secret about the lighthouse.")

    rows = _rows(db_session, s["recip_id"])
    assert len(rows) == 1
    assert rows[0].is_read is False
    assert _payload(rows[0]) == {
        "conversation_id": s["conv"],
        "sender_character_id": s["mara"],
        "sender_character_name": "Mara",
        "recipient_character_id": s["angelo"],
        "recipient_character_name": "Angelo",
        "message_count": 1,
    }
    raw = rows[0].payload
    assert "lighthouse" not in raw and "secret" not in raw
    assert "m72sender" not in raw and "m72recip" not in raw
    # The sender is not told about their own message.
    assert _all_rows(db_session, s["sender_id"]) == []


def test_a_reply_notifies_the_original_sender(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"])
    _send(client, s["h_r"], s["conv"], s["angelo"], "On my way.")
    back = _rows(db_session, s["sender_id"])
    assert len(back) == 1
    assert _payload(back[0])["sender_character_name"] == "Angelo"
    assert _payload(back[0])["recipient_character_name"] == "Mara"
    # The recipient's own row is untouched by their reply.
    assert _payload(_rows(db_session, s["recip_id"])[0])["message_count"] == 1


def test_messaging_between_two_characters_of_one_account_writes_nothing(client, db_session):
    tok = get_auth_token(client, "m72seed@test.com", "m72seed")
    make_seeder("m72seed@test.com")
    h = auth_headers(tok)
    first = _character(client, h, "Isolde")
    second = _character(client, h, "Tamsin")
    conv = _conversation(client, h, first, second)
    _send(client, h, conv, first)
    _send(client, h, conv, second)
    assert _all_rows(db_session, _user_id(db_session, "m72seed")) == []


# ── 2. grouping ──────────────────────────────────────────────────────────────

def test_further_unread_messages_update_one_row(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"], "One.")
    first = _rows(db_session, s["recip_id"])[0]
    # Age the row so "moved forward" is observable at any clock resolution.
    old = datetime.utcnow() - timedelta(hours=1)
    first.created_at = old
    db_session.commit()

    _send(client, s["h_s"], s["conv"], s["mara"], "Two.")
    _send(client, s["h_s"], s["conv"], s["mara"], "Three.")
    rows = _rows(db_session, s["recip_id"])
    assert len(rows) == 1
    assert rows[0].id == first.id
    assert _payload(rows[0])["message_count"] == 3
    assert rows[0].created_at > old
    assert _unread(client, s["h_r"], "message_received") == 1


def test_after_reading_the_next_message_starts_a_new_row(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"])
    _send(client, s["h_s"], s["conv"], s["mara"])
    assert _mark_read(client, s["h_r"], s["conv"]).json() == {"marked": 1}

    _send(client, s["h_s"], s["conv"], s["mara"])
    rows = _rows(db_session, s["recip_id"])
    assert [r.is_read for r in rows] == [True, False]
    assert [_payload(r)["message_count"] for r in rows] == [2, 1]


def test_reading_the_notification_itself_also_ends_the_group(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"])
    row_id = _rows(db_session, s["recip_id"])[0].id
    assert client.patch(f"/notifications/{row_id}/read", headers=s["h_r"]).status_code == 200
    _send(client, s["h_s"], s["conv"], s["mara"])
    assert len(_rows(db_session, s["recip_id"])) == 2


def test_each_conversation_groups_separately(client, db_session):
    s = _scene(client, db_session)
    t = _third(client, db_session)
    other_conv = _conversation(client, t["h"], t["char"], s["angelo"])
    _send(client, s["h_s"], s["conv"], s["mara"])
    _send(client, t["h"], other_conv, t["char"])
    _send(client, s["h_s"], s["conv"], s["mara"])
    rows = _rows(db_session, s["recip_id"])
    assert sorted((_payload(r)["conversation_id"], _payload(r)["message_count"]) for r in rows) == sorted(
        [(s["conv"], 2), (other_conv, 1)]
    )


# ── 3. refused sends ─────────────────────────────────────────────────────────

def test_recipient_who_blocked_the_sender_gets_nothing(client, db_session):
    s = _scene(client, db_session)
    assert client.post(f"/blocks/{s['sender_id']}", headers=s["h_r"]).status_code == 201
    _send(client, s["h_s"], s["conv"], s["mara"], expect=403)
    assert _all_rows(db_session, s["recip_id"]) == []


def test_sender_who_blocked_the_recipient_writes_nothing_either(client, db_session):
    s = _scene(client, db_session)
    assert client.post(f"/blocks/{s['recip_id']}", headers=s["h_s"]).status_code == 201
    _send(client, s["h_s"], s["conv"], s["mara"], expect=403)
    assert _all_rows(db_session, s["recip_id"]) == []


def test_rejected_sends_write_nothing(client, db_session):
    s = _scene(client, db_session)
    t = _third(client, db_session)
    # Not a participant.
    _send(client, t["h"], s["conv"], t["char"], expect=403)
    # A participant sending as the other side's character.
    _send(client, s["h_s"], s["conv"], s["angelo"], expect=403)
    # No such conversation.
    _send(client, s["h_s"], 999999, s["mara"], expect=404)
    assert _all_rows(db_session, s["recip_id"]) == []
    assert _all_rows(db_session, s["sender_id"]) == []


# ── 4. marking a conversation read ───────────────────────────────────────────

def test_read_marks_only_the_callers_rows_for_that_conversation(client, db_session):
    s = _scene(client, db_session)
    t = _third(client, db_session)
    other_conv = _conversation(client, t["h"], t["char"], s["angelo"])
    _send(client, s["h_s"], s["conv"], s["mara"])     # -> recipient, conv
    _send(client, t["h"], other_conv, t["char"])       # -> recipient, other_conv
    _send(client, s["h_r"], s["conv"], s["angelo"])   # -> sender, conv

    assert _mark_read(client, s["h_r"], s["conv"]).json() == {"marked": 1}
    by_conv = {_payload(r)["conversation_id"]: r.is_read for r in _rows(db_session, s["recip_id"])}
    assert by_conv == {s["conv"]: True, other_conv: False}
    # The other participant's row for the SAME conversation is untouched.
    assert [r.is_read for r in _rows(db_session, s["sender_id"])] == [False]
    # Idempotent.
    assert _mark_read(client, s["h_r"], s["conv"]).json() == {"marked": 0}


def test_read_is_refused_to_non_participants_missing_and_blocked_conversations(client, db_session):
    s = _scene(client, db_session)
    t = _third(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"])

    assert _mark_read(client, t["h"], s["conv"]).status_code == 403
    assert _mark_read(client, s["h_r"], 999999).status_code == 404
    assert client.post(f"/messages/conversations/{s['conv']}/read").status_code in (401, 403)

    # A conversation that became inaccessible (block) opens nothing — read
    # included — and its row stays as it was.
    assert client.post(f"/blocks/{s['sender_id']}", headers=s["h_r"]).status_code == 201
    assert _mark_read(client, s["h_r"], s["conv"]).status_code == 404
    assert client.get(f"/messages/conversations/{s['conv']}/messages", headers=s["h_r"]).status_code == 404
    assert [r.is_read for r in _rows(db_session, s["recip_id"])] == [False]


def test_reading_messages_with_get_writes_nothing(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"])
    assert client.get(f"/messages/conversations/{s['conv']}/messages", headers=s["h_r"]).status_code == 200
    assert client.get("/messages/conversations", headers=s["h_r"]).status_code == 200
    assert [r.is_read for r in _rows(db_session, s["recip_id"])] == [False]


# ── 5. the unread count ──────────────────────────────────────────────────────

def test_unread_count_by_type_counts_only_the_callers_rows(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"])

    assert _unread(client, s["h_r"], "message_received") == 1
    assert _unread(client, s["h_r"]) == 1
    # The sender's account cannot see the recipient's row through the filter.
    assert _unread(client, s["h_s"], "message_received") == 0
    assert _unread(client, s["h_s"]) == 0
    # An unknown type narrows to nothing; it never widens.
    assert _unread(client, s["h_r"], "no_such_type") == 0
    assert client.get("/notifications/unread-count?type=message_received").status_code in (401, 403)

    _mark_read(client, s["h_r"], s["conv"])
    assert _unread(client, s["h_r"], "message_received") == 0


# ── 6. isolation from comment and Featuring notifications ────────────────────

def _realm_post(client, headers, character_id, tagged=()):
    resp = client.post(
        "/realms/", json={"name": "Harbour", "slug": "harbour", "is_public": True}, headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    realm_id = resp.json()["id"]
    client.post(f"/realms/{realm_id}/join", headers=headers)
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": "Harbour lights.", "character_id": character_id,
              "tagged_character_ids": list(tagged)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return realm_id, resp.json()


def test_comment_and_featuring_notifications_are_unaffected(client, db_session):
    s = _scene(client, db_session)
    # Mara's account features Angelo on a post and comments on Angelo's post.
    realm_id, maras_post = _realm_post(client, s["h_s"], s["mara"], tagged=[s["angelo"]])
    client.post(f"/realms/{realm_id}/join", headers=s["h_r"])
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": "Angelo's own post.", "character_id": s["angelo"]},
        headers=s["h_r"],
    )
    angelos_post = resp.json()
    resp = client.post(
        f"/comments/posts/{angelos_post['id']}/comments",
        json={"content": "Nice.", "character_id": s["mara"]}, headers=s["h_s"],
    )
    assert resp.status_code == 201, resp.text
    _send(client, s["h_s"], s["conv"], s["mara"])

    assert len(_rows(db_session, s["recip_id"], "character_tagged")) == 1
    assert len(_rows(db_session, s["recip_id"], "post_commented")) == 1
    assert _unread(client, s["h_r"]) == 3
    assert _unread(client, s["h_r"], "message_received") == 1

    # Reading the conversation reads only the message row.
    _mark_read(client, s["h_r"], s["conv"])
    assert [r.is_read for r in _rows(db_session, s["recip_id"], "character_tagged")] == [False]
    assert [r.is_read for r in _rows(db_session, s["recip_id"], "post_commented")] == [False]

    # Deleting a post never touches message rows.
    _send(client, s["h_s"], s["conv"], s["mara"])
    assert client.delete(f"/posts/{maras_post['id']}", headers=s["h_s"]).status_code == 204
    assert _rows(db_session, s["recip_id"], "character_tagged") == []
    assert len(_rows(db_session, s["recip_id"])) == 2


def test_notifications_list_carries_the_row_to_its_owner_only(client, db_session):
    s = _scene(client, db_session)
    _send(client, s["h_s"], s["conv"], s["mara"])
    listed = client.get("/notifications", headers=s["h_r"]).json()
    assert [n["type"] for n in listed] == ["message_received"]
    assert json.loads(listed[0]["payload"])["conversation_id"] == s["conv"]
    assert client.get("/notifications", headers=s["h_s"]).json() == []
