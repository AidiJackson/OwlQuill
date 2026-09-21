"""Polish Phase 7.1 — the notification contract, pinned.

Three things this file proves and ``test_mentions.py`` does not:

1. **The payload says who and which.** A mention row names the acting
   CHARACTER and the recipient's CHARACTER by id and name snapshot, plus the
   post/realm target — and never an account username as the social actor.
2. **Protected text stays protected.** A public character mentioned from a
   PRIVATE realm its owner is not in is told the mention happened, but the
   post excerpt and the realm's name are withheld — the same rule
   ``GET /realms/{id}`` and ``GET /posts/{id}`` already apply to that account.
3. **The rows are private to their account.** Listing, mark-one and mark-all
   each touch only the caller's rows.
4. **A block closes the channel.** An author in a block relationship with the
   recipient may still post and still @mention — nothing about posting or
   mention resolution changes — but no notification row reaches the recipient.
   The relationship is the product's existing one (``blocked_user_ids``), which
   the feed, comments and messaging already treat as holding both directions.

Every row is written through ``services/notifications``; the route-level
inline construction is gone.
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


def _post(client, headers, realm_id, content, character_id):
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "character_id": character_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _user_id(db, username):
    user = db.query(User).filter(User.username == username).first()
    assert user is not None
    return user.id


def _mention_rows(db, user_id):
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.type == "mention")
        .order_by(Notification.id)
        .all()
    )


def _payload(notif):
    return json.loads(notif.payload)


def _scene(client, db_session, *, realm_public, recipient_joins_realm=False):
    """An author mentions a recipient's character from a realm the author made."""
    tok_author = get_auth_token(client, "p71author@test.com", "p71author")
    tok_recip = get_auth_token(client, "p71recip@test.com", "p71recip")
    h_author, h_recip = auth_headers(tok_author), auth_headers(tok_recip)

    recip_char_id = _character(client, h_recip, "Elowen")
    author_char_id = _character(client, h_author, "Bram")
    realm_id = _realm(client, h_author, "Contract Realm", is_public=realm_public)
    if recipient_joins_realm:
        # A private realm cannot be self-joined; membership is granted. Written
        # directly: how the recipient got in is not what these tests are about.
        db_session.add(RealmMembership(realm_id=realm_id, user_id=_user_id(db_session, "p71recip")))
        db_session.commit()

    content = "At the gate, @Elowen turned and the whole market went quiet. " * 3
    post = _post(client, h_author, realm_id, content, author_char_id)
    return {
        "h_author": h_author, "h_recip": h_recip,
        "author_id": _user_id(db_session, "p71author"),
        "recip_id": _user_id(db_session, "p71recip"),
        "author_char_id": author_char_id, "recip_char_id": recip_char_id,
        "realm_id": realm_id, "post": post, "content": content,
    }


# ── 1. who and which ─────────────────────────────────────────────────────────

def test_mention_notifies_the_other_owner_only(client, db_session):
    s = _scene(client, db_session, realm_public=True)
    assert len(_mention_rows(db_session, s["recip_id"])) == 1
    assert _mention_rows(db_session, s["author_id"]) == []


def test_self_owned_character_mention_writes_nothing(client, db_session):
    tok = get_auth_token(client, "p71self@test.com", "p71self")
    h = auth_headers(tok)
    own = _character(client, h, "Selby")
    realm_id = _realm(client, h, "Self Realm", is_public=True)
    _post(client, h, realm_id, "Talking to myself, @Selby.", own)
    assert _mention_rows(db_session, _user_id(db_session, "p71self")) == []


def test_payload_names_actor_and_recipient_characters_and_target(client, db_session):
    s = _scene(client, db_session, realm_public=True)
    p = _payload(_mention_rows(db_session, s["recip_id"])[0])

    # actor — the CHARACTER that wrote the post
    assert p["author_character_id"] == s["author_char_id"]
    assert p["author_character_name"] == "Bram"
    # recipient — WHICH of the account's characters was addressed
    assert p["mentioned_character_id"] == s["recip_char_id"]
    assert p["mentioned_character_name"] == "Elowen"
    assert p["mention_text"] == "@Elowen"
    # target — the post and its realm, by id
    assert p["post_id"] == s["post"]["id"]
    assert p["realm_id"] == s["realm_id"]


def test_payload_never_carries_an_account_username_as_actor(client, db_session):
    s = _scene(client, db_session, realm_public=True)
    raw = _mention_rows(db_session, s["recip_id"])[0].payload
    assert "p71author" not in raw
    assert "author_username" not in raw
    assert "username" not in json.loads(raw)


def test_target_type_is_no_longer_written(client, db_session):
    """The old ``target_type`` key was never read; the ``user`` branch it
    served was unreachable. Neither survives 7.1."""
    s = _scene(client, db_session, realm_public=True)
    assert "target_type" not in _payload(_mention_rows(db_session, s["recip_id"])[0])


def test_multi_character_account_gets_one_row_per_addressed_character(client, db_session):
    tok_author = get_auth_token(client, "p71multi_a@test.com", "p71multia")
    tok_recip = get_auth_token(client, "p71multi_r@test.com", "p71multir")
    make_seeder("p71multi_r@test.com")  # the tier that may own several characters
    h_author, h_recip = auth_headers(tok_author), auth_headers(tok_recip)
    one = _character(client, h_recip, "Mira")
    two = _character(client, h_recip, "Tobin")
    author_char = _character(client, h_author, "Quill")
    realm_id = _realm(client, h_author, "Multi Realm", is_public=True)
    _post(client, h_author, realm_id, "@Mira and @Tobin, both of you, now.", author_char)

    rows = _mention_rows(db_session, _user_id(db_session, "p71multir"))
    assert len(rows) == 2
    addressed = {(_payload(r)["mentioned_character_id"], _payload(r)["mentioned_character_name"]) for r in rows}
    assert addressed == {(one, "Mira"), (two, "Tobin")}


# ── 2. protected text stays protected ────────────────────────────────────────

def test_public_realm_mention_carries_preview_and_realm_name(client, db_session):
    s = _scene(client, db_session, realm_public=True)
    p = _payload(_mention_rows(db_session, s["recip_id"])[0])
    assert p["post_preview"] == s["content"][:120]
    assert p["realm_name"] == "Contract Realm"


def test_private_realm_mention_withholds_preview_from_a_non_member(client, db_session):
    s = _scene(client, db_session, realm_public=False)
    rows = _mention_rows(db_session, s["recip_id"])
    assert len(rows) == 1, "the recipient is still told their character was mentioned"

    p = _payload(rows[0])
    assert "post_preview" not in p
    assert "realm_name" not in p
    # and the protected body is not smuggled in under any other key
    raw = rows[0].payload
    assert "the whole market went quiet" not in raw
    assert "Contract Realm" not in raw
    # what remains is exactly the truthful, non-content context
    assert p["mentioned_character_name"] == "Elowen"
    assert p["author_character_name"] == "Bram"
    assert p["post_id"] == s["post"]["id"]
    assert p["realm_id"] == s["realm_id"]


def test_private_realm_mention_rule_matches_the_destination(client, db_session):
    """The preview is withheld from exactly the account the post route refuses."""
    s = _scene(client, db_session, realm_public=False)
    resp = client.get(f"/posts/{s['post']['id']}", headers=s["h_recip"])
    assert resp.status_code == 404, resp.text
    assert "post_preview" not in _payload(_mention_rows(db_session, s["recip_id"])[0])


def test_private_realm_member_recipient_gets_the_preview(client, db_session):
    s = _scene(client, db_session, realm_public=False, recipient_joins_realm=True)
    p = _payload(_mention_rows(db_session, s["recip_id"])[0])
    assert p["post_preview"] == s["content"][:120]
    assert p["realm_name"] == "Contract Realm"
    assert client.get(f"/posts/{s['post']['id']}", headers=s["h_recip"]).status_code == 200


def test_private_realm_mention_does_not_add_the_recipient_to_the_realm(client, db_session):
    s = _scene(client, db_session, realm_public=False)
    # Still a stranger to the realm: the realm itself is invisible to them.
    assert client.get(f"/realms/{s['realm_id']}", headers=s["h_recip"]).status_code == 404


# ── 3. the rows are private to their account ─────────────────────────────────

def _two_accounts_each_with_a_mention(client, db_session):
    tok_a = get_auth_token(client, "p71own_a@test.com", "p71owna")
    tok_b = get_auth_token(client, "p71own_b@test.com", "p71ownb")
    tok_x = get_auth_token(client, "p71own_x@test.com", "p71ownx")
    h_a, h_b, h_x = auth_headers(tok_a), auth_headers(tok_b), auth_headers(tok_x)
    _character(client, h_a, "Anwen")
    _character(client, h_b, "Bertram")
    x_char = _character(client, h_x, "Xan")
    realm_id = _realm(client, h_x, "Owner Realm", is_public=True)
    _post(client, h_x, realm_id, "Hello @Anwen.", x_char)
    _post(client, h_x, realm_id, "Hello @Bertram.", x_char)
    return h_a, h_b


def test_list_returns_only_the_callers_rows(client, db_session):
    h_a, h_b = _two_accounts_each_with_a_mention(client, db_session)
    seen_a = client.get("/notifications", headers=h_a).json()
    seen_b = client.get("/notifications", headers=h_b).json()
    assert [json.loads(n["payload"])["mentioned_character_name"] for n in seen_a] == ["Anwen"]
    assert [json.loads(n["payload"])["mentioned_character_name"] for n in seen_b] == ["Bertram"]
    for n in seen_a + seen_b:
        assert "user_id" not in n


def test_mark_one_read_cannot_touch_another_accounts_row(client, db_session):
    h_a, h_b = _two_accounts_each_with_a_mention(client, db_session)
    b_row_id = client.get("/notifications", headers=h_b).json()[0]["id"]

    resp = client.patch(f"/notifications/{b_row_id}/read", headers=h_a)
    assert resp.status_code == 404, resp.text
    assert client.get("/notifications", headers=h_b).json()[0]["is_read"] is False
    assert client.get("/notifications/unread-count", headers=h_b).json()["count"] == 1


def test_mark_all_read_affects_only_the_caller(client, db_session):
    h_a, h_b = _two_accounts_each_with_a_mention(client, db_session)
    resp = client.post("/notifications/mark-all-read", headers=h_a)
    assert resp.status_code == 200, resp.text
    assert client.get("/notifications/unread-count", headers=h_a).json()["count"] == 0
    assert client.get("/notifications/unread-count", headers=h_b).json()["count"] == 1
    assert client.get("/notifications", headers=h_a).json()[0]["is_read"] is True


# ── 4. a block closes the channel ────────────────────────────────────────────

def _blocked_scene(client, db_session, *, who_blocks):
    """Author mentions recipient's character after a block in the given
    direction. ``who_blocks`` is "recipient" or "author"."""
    tok_author = get_auth_token(client, "p71blk_a@test.com", "p71blka")
    tok_recip = get_auth_token(client, "p71blk_r@test.com", "p71blkr")
    h_author, h_recip = auth_headers(tok_author), auth_headers(tok_recip)
    author_id, recip_id = _user_id(db_session, "p71blka"), _user_id(db_session, "p71blkr")

    _character(client, h_recip, "Wren")
    author_char = _character(client, h_author, "Hollis")
    realm_id = _realm(client, h_author, "Block Realm", is_public=True)

    if who_blocks == "recipient":
        assert client.post(f"/blocks/{author_id}", headers=h_recip).status_code == 201
    elif who_blocks == "author":
        assert client.post(f"/blocks/{recip_id}", headers=h_author).status_code == 201

    post = _post(client, h_author, realm_id, "Well met, @Wren.", author_char)
    return {"post": post, "author_id": author_id, "recip_id": recip_id, "h_recip": h_recip}


def test_recipient_who_blocked_the_author_gets_no_row(client, db_session):
    s = _blocked_scene(client, db_session, who_blocks="recipient")
    # posting and mention resolution are untouched by the block
    assert s["post"]["mentions"][0]["target_type"] == "character"
    assert _mention_rows(db_session, s["recip_id"]) == []
    assert client.get("/notifications/unread-count", headers=s["h_recip"]).json()["count"] == 0


def test_author_who_blocked_the_recipient_writes_no_row_either(client, db_session):
    """Both directions: the same rule the feed, comments and messaging apply
    (``test_feed_reverse_block_excludes_author``). Not invented here — reused."""
    s = _blocked_scene(client, db_session, who_blocks="author")
    assert s["post"]["mentions"][0]["target_type"] == "character"
    assert _mention_rows(db_session, s["recip_id"]) == []


def test_without_a_block_the_same_mention_notifies(client, db_session):
    s = _blocked_scene(client, db_session, who_blocks=None)
    rows = _mention_rows(db_session, s["recip_id"])
    assert len(rows) == 1
    assert _payload(rows[0])["mentioned_character_name"] == "Wren"


def test_block_guard_uses_the_products_block_helper():
    """One definition of "blocked", not a second query with its own semantics."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app/api/routes/posts.py").read_text()
    tree = ast.parse(src)
    called = {
        (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
        for n in ast.walk(tree) if isinstance(n, ast.Call)
    }
    assert "blocked_user_ids" in called
    assert "Block" not in called, "posts.py must not query the Block table by hand"


# ── the seam ─────────────────────────────────────────────────────────────────

def test_rows_are_written_only_through_the_service():
    """No route builds ``Notification(...)`` by hand any more."""
    import ast
    from pathlib import Path

    app_root = Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in app_root.rglob("*.py"):
        rel = str(path.relative_to(app_root))
        if rel in ("services/notifications.py", "models/notification.py"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Notification":
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], offenders


def test_create_notification_drops_none_and_does_not_commit(db_session):
    from app.services.notifications import create_notification

    user = User(email="p71svc@test.com", username="p71svc", hashed_password="x")
    db_session.add(user)
    db_session.flush()

    notif = create_notification(
        db_session, user_id=user.id, type="mention", payload={"a": 1, "gone": None}
    )
    assert notif.id is None, "the caller owns the commit"
    assert json.loads(notif.payload) == {"a": 1}
    db_session.rollback()
