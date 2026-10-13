"""Phase 7.2A — a post's author hears about comments, pinned.

``post_commented`` is written through ``services/notifications`` in the same
transaction as the comment, under the rules 7.1 and W-10A established:

1. **Another account only.** Commenting on your own post — as any of your
   characters — writes nothing.
2. **A block closes the channel**, in both directions, through the product's
   one ``blocked_user_ids``. The comment itself is unaffected.
3. **Protected text stays protected.** The comment preview and realm name are
   carried only when the post's author can still open the realm.
4. **Characters, never accounts.** A character comment names the character; a
   Wanderer comment names no one — not even the public Wanderer username.
5. **The row goes with what it describes.** Deleting the comment or the post
   deletes it; removing a Featuring tag does not.
"""
import json

from app.models.notification import Notification
from app.models.realm import RealmMembership
from app.models.user import User
from tests.conftest import auth_headers, get_auth_token, make_seeder


# ── helpers ──────────────────────────────────────────────────────────────────

def _character(client, headers, name):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _realm(client, headers, name, *, is_public):
    slug = name.lower().replace(" ", "-")
    resp = client.post(
        "/realms/",
        json={"name": name, "slug": slug, "is_public": is_public},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    realm_id = resp.json()["id"]
    client.post(f"/realms/{realm_id}/join", headers=headers)
    return realm_id


def _post(client, headers, realm_id, character_id, content="The lanterns went out one by one.", tagged=()):
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "character_id": character_id,
              "tagged_character_ids": list(tagged)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _comment(client, headers, post_id, content, character_id=None, expect=201):
    body = {"content": content}
    if character_id is not None:
        body["character_id"] = character_id
    resp = client.post(f"/comments/posts/{post_id}/comments", json=body, headers=headers)
    assert resp.status_code == expect, resp.text
    return resp.json() if expect == 201 else None


def _user_id(db, username):
    user = db.query(User).filter(User.username == username).first()
    assert user is not None
    return user.id


def _rows(db, user_id, type_="post_commented"):
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


def _scene(client, db_session, *, realm_public=True):
    """Angelo (owner's character) posts in a realm Mara's account made."""
    tok_owner = get_auth_token(client, "c72owner@test.com", "c72owner")
    tok_other = get_auth_token(client, "c72other@test.com", "c72other")
    h_owner, h_other = auth_headers(tok_owner), auth_headers(tok_other)
    owner_id, other_id = _user_id(db_session, "c72owner"), _user_id(db_session, "c72other")

    angelo = _character(client, h_owner, "Angelo")
    mara = _character(client, h_other, "Mara")
    realm_id = _realm(client, h_other, "Ashfall", is_public=realm_public)
    if realm_public:
        assert client.post(f"/realms/{realm_id}/join", headers=h_owner).status_code in (200, 201)
    else:
        # A private realm cannot be self-joined; membership is granted directly.
        db_session.add(RealmMembership(realm_id=realm_id, user_id=owner_id))
        db_session.commit()
    post = _post(client, h_owner, realm_id, angelo)
    return {
        "h_owner": h_owner, "h_other": h_other,
        "owner_id": owner_id, "other_id": other_id,
        "angelo": angelo, "mara": mara, "realm_id": realm_id, "post": post,
    }


# ── 1. who is told ───────────────────────────────────────────────────────────

def test_another_accounts_comment_notifies_the_post_owner(client, db_session):
    s = _scene(client, db_session)
    comment = _comment(client, s["h_other"], s["post"]["id"], "The lanterns were never lit.", s["mara"])

    rows = _rows(db_session, s["owner_id"])
    assert len(rows) == 1
    assert rows[0].is_read is False
    assert _payload(rows[0]) == {
        "post_id": s["post"]["id"],
        "realm_id": s["realm_id"],
        "comment_id": comment["id"],
        "commenter_kind": "character",
        "commenter_character_id": s["mara"],
        "commenter_character_name": "Mara",
        "post_character_id": s["angelo"],
        "post_character_name": "Angelo",
        "realm_name": "Ashfall",
        "comment_preview": "The lanterns were never lit.",
    }
    # The commenter is not told about their own comment.
    assert _all_rows(db_session, s["other_id"]) == []


def test_payload_never_carries_an_account_identity(client, db_session):
    s = _scene(client, db_session)
    _comment(client, s["h_other"], s["post"]["id"], "Hello.", s["mara"])
    raw = _rows(db_session, s["owner_id"])[0].payload
    assert "c72other" not in raw and "c72owner" not in raw
    assert "username" not in raw and "user_id" not in raw


def test_commenting_on_your_own_post_writes_nothing(client, db_session):
    s = _scene(client, db_session)
    _comment(client, s["h_owner"], s["post"]["id"], "Talking to myself.", s["angelo"])
    assert _all_rows(db_session, s["owner_id"]) == []


def test_commenting_as_your_own_second_character_writes_nothing(client, db_session):
    tok = get_auth_token(client, "c72seed@test.com", "c72seed")
    make_seeder("c72seed@test.com")
    h = auth_headers(tok)
    first = _character(client, h, "Isolde")
    second = _character(client, h, "Tamsin")
    realm_id = _realm(client, h, "Two Voices", is_public=True)
    post = _post(client, h, realm_id, first)

    _comment(client, h, post["id"], "A reply from my other self.", second)
    assert _all_rows(db_session, _user_id(db_session, "c72seed")) == []


def test_one_notification_per_created_comment(client, db_session):
    s = _scene(client, db_session)
    c1 = _comment(client, s["h_other"], s["post"]["id"], "First.", s["mara"])
    c2 = _comment(client, s["h_other"], s["post"]["id"], "Second.", s["mara"])
    rows = _rows(db_session, s["owner_id"])
    assert [_payload(r)["comment_id"] for r in rows] == [c1["id"], c2["id"]]


def test_rejected_comments_write_nothing(client, db_session):
    s = _scene(client, db_session)
    # Commenting as a character the caller does not own: 403.
    _comment(client, s["h_other"], s["post"]["id"], "Impostor.", s["angelo"], expect=403)
    # An account with characters must pick one: 403.
    _comment(client, s["h_other"], s["post"]["id"], "Nobody.", None, expect=403)
    # A post the caller cannot see: 404.
    private_realm = _realm(client, s["h_owner"], "Closed Door", is_public=False)
    hidden = _post(client, s["h_owner"], private_realm, s["angelo"])
    _comment(client, s["h_other"], hidden["id"], "Let me in.", s["mara"], expect=404)
    # A post that does not exist: 404.
    _comment(client, s["h_other"], 999999, "Anyone?", s["mara"], expect=404)

    assert _all_rows(db_session, s["owner_id"]) == []


# ── 2. blocks ────────────────────────────────────────────────────────────────

def test_post_owner_who_blocked_the_commenter_gets_no_row(client, db_session):
    s = _scene(client, db_session)
    assert client.post(f"/blocks/{s['other_id']}", headers=s["h_owner"]).status_code == 201
    _comment(client, s["h_other"], s["post"]["id"], "Can you hear me?", s["mara"])
    assert _all_rows(db_session, s["owner_id"]) == []


def test_commenter_who_blocked_the_post_owner_writes_no_row_either(client, db_session):
    s = _scene(client, db_session)
    assert client.post(f"/blocks/{s['owner_id']}", headers=s["h_other"]).status_code == 201
    _comment(client, s["h_other"], s["post"]["id"], "Parting words.", s["mara"])
    assert _all_rows(db_session, s["owner_id"]) == []


def test_comment_guard_uses_the_products_block_helper():
    """One definition of "blocked", not a second query with its own semantics."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app/api/routes/comments.py").read_text()
    called = {
        (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
        for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
    }
    assert "blocked_user_ids" in called
    assert "Block" not in called, "comments.py must not query the Block table by hand"


# ── 3. protected text ────────────────────────────────────────────────────────

def test_private_realm_member_owner_gets_the_preview(client, db_session):
    s = _scene(client, db_session, realm_public=False)
    _comment(client, s["h_other"], s["post"]["id"], "Behind closed doors.", s["mara"])
    payload = _payload(_rows(db_session, s["owner_id"])[0])
    assert payload["realm_name"] == "Ashfall"
    assert payload["comment_preview"] == "Behind closed doors."


def test_owner_who_lost_realm_access_is_told_without_text_or_realm_name(client, db_session):
    s = _scene(client, db_session, realm_public=False)
    db_session.query(RealmMembership).filter(
        RealmMembership.realm_id == s["realm_id"], RealmMembership.user_id == s["owner_id"]
    ).delete()
    db_session.commit()
    # The destination agrees: the owner can no longer open the post.
    assert client.get(f"/posts/{s['post']['id']}", headers=s["h_owner"]).status_code == 404

    _comment(client, s["h_other"], s["post"]["id"], "A secret they cannot read.", s["mara"])
    payload = _payload(_rows(db_session, s["owner_id"])[0])
    assert "realm_name" not in payload
    assert "comment_preview" not in payload
    assert "A secret" not in _rows(db_session, s["owner_id"])[0].payload
    assert payload["post_id"] == s["post"]["id"]
    assert payload["commenter_character_name"] == "Mara"


def test_preview_is_capped(client, db_session):
    s = _scene(client, db_session)
    _comment(client, s["h_other"], s["post"]["id"], "x" * 500, s["mara"])
    assert _payload(_rows(db_session, s["owner_id"])[0])["comment_preview"] == "x" * 120


# ── 4. Wanderers ─────────────────────────────────────────────────────────────

def test_wanderer_comment_notifies_without_naming_anyone(client, db_session):
    s = _scene(client, db_session)
    tok = get_auth_token(client, "c72wander@test.com", "c72wander")
    _comment(client, auth_headers(tok), s["post"]["id"], "Just passing through.")

    row = _rows(db_session, s["owner_id"])[0]
    payload = _payload(row)
    assert payload["commenter_kind"] == "wanderer"
    assert "commenter_character_id" not in payload
    assert "commenter_character_name" not in payload
    assert "c72wander" not in row.payload
    assert payload["comment_preview"] == "Just passing through."


# ── 5. deletion ──────────────────────────────────────────────────────────────

def test_deleting_the_comment_removes_only_its_notification(client, db_session):
    s = _scene(client, db_session)
    keep = _comment(client, s["h_other"], s["post"]["id"], "Stays.", s["mara"])
    gone = _comment(client, s["h_other"], s["post"]["id"], "Goes.", s["mara"])

    assert client.delete(f"/comments/{gone['id']}", headers=s["h_other"]).status_code == 204
    rows = _rows(db_session, s["owner_id"])
    assert [_payload(r)["comment_id"] for r in rows] == [keep["id"]]


def test_deleting_the_post_removes_comment_and_tag_notifications(client, db_session):
    s = _scene(client, db_session)
    # Mara's account posts, featuring Angelo; then Angelo's owner comments on
    # Mara's post and Mara's owner comments on Angelo's.
    maras_post = _post(client, s["h_other"], s["realm_id"], s["mara"], tagged=[s["angelo"]])
    _comment(client, s["h_owner"], maras_post["id"], "Thanks for featuring me.", s["angelo"])
    _comment(client, s["h_other"], s["post"]["id"], "Unrelated post.", s["mara"])
    assert len(_rows(db_session, s["owner_id"], "character_tagged")) == 1
    assert len(_rows(db_session, s["other_id"])) == 1

    assert client.delete(f"/posts/{maras_post['id']}", headers=s["h_other"]).status_code == 204
    assert _rows(db_session, s["owner_id"], "character_tagged") == []
    assert _rows(db_session, s["other_id"]) == []
    # The comment notification on the OTHER post is untouched.
    assert len(_rows(db_session, s["owner_id"])) == 1


def test_removing_a_featuring_tag_keeps_comment_notifications(client, db_session):
    s = _scene(client, db_session)
    maras_post = _post(client, s["h_other"], s["realm_id"], s["mara"], tagged=[s["angelo"]])
    _comment(client, s["h_owner"], maras_post["id"], "Featured and replying.", s["angelo"])

    resp = client.delete(f"/posts/{maras_post['id']}/tags/{s['angelo']}", headers=s["h_owner"])
    assert resp.status_code == 204
    assert _rows(db_session, s["owner_id"], "character_tagged") == []
    assert len(_rows(db_session, s["other_id"])) == 1


def test_deleting_a_comment_leaves_featuring_notifications(client, db_session):
    s = _scene(client, db_session)
    maras_post = _post(client, s["h_other"], s["realm_id"], s["mara"], tagged=[s["angelo"]])
    comment = _comment(client, s["h_owner"], maras_post["id"], "Hi.", s["angelo"])
    assert client.delete(f"/comments/{comment['id']}", headers=s["h_owner"]).status_code == 204
    assert _rows(db_session, s["other_id"]) == []
    assert len(_rows(db_session, s["owner_id"], "character_tagged")) == 1


# ── 6. the reader ────────────────────────────────────────────────────────────

def test_post_owner_lists_the_row_and_its_destination_opens(client, db_session):
    s = _scene(client, db_session)
    _comment(client, s["h_other"], s["post"]["id"], "Read me.", s["mara"])
    listed = client.get("/notifications", headers=s["h_owner"]).json()
    assert [n["type"] for n in listed] == ["post_commented"]
    assert client.get("/notifications/unread-count", headers=s["h_owner"]).json() == {"count": 1}
    post_id = json.loads(listed[0]["payload"])["post_id"]
    assert client.get(f"/posts/{post_id}", headers=s["h_owner"]).status_code == 200
    # Not visible to the commenter's account.
    assert client.get("/notifications", headers=s["h_other"]).json() == []
