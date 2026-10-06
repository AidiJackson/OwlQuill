"""W-10A — first-class character tagging on posts.

TAGGED is not AUTHORED: a tag is the post author's deliberate association of
another character with the post. These tests pin the contract end to end:

* validation (PUBLIC only, one refusal for every non-taggable target, no
  self-tag, de-duplicate, cap 5) and atomic creation with the post;
* the per-viewer projection (live name, ids only, hidden when the character
  stops being PUBLIC, gone when it is deleted, never in the byline);
* blocks (stored but inert, invisible outside the author's own view);
* the Tagged surface (tags + legacy mentions, de-duplicated, access- and
  block-filtered);
* notifications (character_tagged only; typed @mentions no longer notify);
* tag removal (tagged owner or post author only; uniform 404 otherwise);
* the legacy ``/users/{username}/mentions`` private-realm fix.
"""
import json

import pytest
from sqlalchemy import event

from app.models.character import Character
from app.models.notification import Notification
from app.models.post import Post
from app.models.post_character_tag import PostCharacterTag
from app.models.post_mention import PostMention
from app.models.realm import RealmMembership
from app.models.user import User
from app.services.character_tags import SELF_TAG_DETAIL, TAG_REFUSAL_DETAIL
from tests.conftest import auth_headers, engine, get_auth_token, make_seeder


# ── helpers ──────────────────────────────────────────────────────────────────

def _account(client, slug):
    return auth_headers(get_auth_token(client, f"{slug}@w10atest.com", slug))


def _uid(db, slug):
    user = db.query(User).filter(User.username == slug).first()
    assert user is not None
    return user.id


def _character(client, h, name, visibility="public"):
    resp = client.post("/characters/", json={"name": name, "visibility": visibility}, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _realm(client, h, name, *, is_public=True):
    resp = client.post(
        "/realms/",
        json={"name": name, "slug": name.lower().replace(" ", "-"), "is_public": is_public},
        headers=h,
    )
    assert resp.status_code in (200, 201), resp.text
    realm_id = resp.json()["id"]
    client.post(f"/realms/{realm_id}/join", headers=h)
    return realm_id


def _join(client, h, realm_id):
    assert client.post(f"/realms/{realm_id}/join", headers=h).status_code in (200, 201, 400)


def _grant(db, realm_id, user_id):
    db.add(RealmMembership(realm_id=realm_id, user_id=user_id))
    db.commit()


def _create(client, h, realm_id, author_char, tags, content="A quiet scene at the docks."):
    return client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "character_id": author_char, "tagged_character_ids": tags},
        headers=h,
    )


def _post(client, h, realm_id, author_char, tags, content="A quiet scene at the docks."):
    resp = _create(client, h, realm_id, author_char, tags, content)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _tags_seen(client, h, post_id):
    resp = client.get(f"/posts/{post_id}", headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()["tagged_characters"]


def _tagged_surface(client, h, character_id):
    resp = client.get(f"/characters/{character_id}/mentions", headers=h)
    assert resp.status_code == 200, resp.text
    return [item["payload"]["id"] for item in resp.json()]


def _tag_rows(db, user_id):
    db.expire_all()
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.type == "character_tagged")
        .order_by(Notification.id)
        .all()
    )


def _all_rows(db, user_id):
    db.expire_all()
    return db.query(Notification).filter(Notification.user_id == user_id).all()


def _block(client, h, user_id):
    assert client.post(f"/blocks/{user_id}", headers=h).status_code == 201


@pytest.fixture
def scene(client, db_session):
    """An author (Bram) and a tagged owner (Elowen) in a public realm, plus a
    third, unrelated signed-in viewer."""
    h_author, h_owner, h_viewer = (
        _account(client, "w10author"), _account(client, "w10owner"), _account(client, "w10viewer")
    )
    author_char = _character(client, h_author, "Bram")
    target = _character(client, h_owner, "Elowen")
    viewer_char = _character(client, h_viewer, "Vesna")
    realm_id = _realm(client, h_author, "Tag Realm")
    _join(client, h_owner, realm_id)
    _join(client, h_viewer, realm_id)
    return {
        "h_author": h_author, "h_owner": h_owner, "h_viewer": h_viewer,
        "author_id": _uid(db_session, "w10author"),
        "owner_id": _uid(db_session, "w10owner"),
        "viewer_id": _uid(db_session, "w10viewer"),
        "author_char": author_char, "target": target, "viewer_char": viewer_char,
        "realm_id": realm_id,
    }


# ── 1. validation & creation ─────────────────────────────────────────────────

def test_valid_public_tag(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    assert post["tagged_characters"] == [{"character_id": scene["target"], "name": "Elowen"}]
    # Tagging is not authorship: the byline is untouched.
    assert post["character_id"] == scene["author_char"]
    assert post["character_name"] == "Bram"
    rows = db_session.query(PostCharacterTag).filter(PostCharacterTag.post_id == post["id"]).all()
    assert [r.character_id for r in rows] == [scene["target"]]
    # Everyone signed in sees it.
    for h in (scene["h_owner"], scene["h_viewer"]):
        assert _tags_seen(client, h, post["id"]) == [{"character_id": scene["target"], "name": "Elowen"}]


def _post_count(db):
    db.expire_all()
    return db.query(Post).count()


def test_nonexistent_private_and_friends_targets_get_one_identical_refusal(client, db_session, scene):
    make_seeder("w10viewer@w10atest.com")  # may own several characters
    private = _character(client, scene["h_viewer"], "Hidden One", visibility="private")
    friends = _character(client, scene["h_viewer"], "Friendly One", visibility="friends")
    before = _post_count(db_session)

    answers = []
    for bad in (999999, private, friends):
        resp = _create(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"], bad])
        answers.append((resp.status_code, resp.json()))
    assert answers[0] == (422, {"detail": TAG_REFUSAL_DETAIL})
    assert answers[0] == answers[1] == answers[2], "must not be an existence oracle"
    # The whole request failed: no post, no tag rows.
    assert _post_count(db_session) == before
    assert db_session.query(PostCharacterTag).count() == 0


def test_self_tag_is_refused(client, db_session, scene):
    resp = _create(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["author_char"]])
    assert resp.status_code == 422
    assert resp.json() == {"detail": SELF_TAG_DETAIL}


def test_own_second_character_is_tagged_without_notification(client, db_session, scene):
    make_seeder("w10author@w10atest.com")
    second = _character(client, scene["h_author"], "Bram's Sister")
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [second])
    assert post["tagged_characters"] == [{"character_id": second, "name": "Bram's Sister"}]
    assert _all_rows(db_session, scene["author_id"]) == []


def test_duplicate_ids_are_deduplicated(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"],
                 [scene["target"], scene["target"], scene["target"]])
    assert len(post["tagged_characters"]) == 1
    assert db_session.query(PostCharacterTag).filter(PostCharacterTag.post_id == post["id"]).count() == 1
    assert len(_tag_rows(db_session, scene["owner_id"])) == 1


def test_more_than_five_distinct_tags_is_refused(client, db_session, scene):
    make_seeder("w10viewer@w10atest.com")
    many = [_character(client, scene["h_viewer"], f"Crowd {i}") for i in range(6)]
    resp = _create(client, scene["h_author"], scene["realm_id"], scene["author_char"], many)
    assert resp.status_code == 422
    ok = _create(client, scene["h_author"], scene["realm_id"], scene["author_char"], many[:5])
    assert ok.status_code == 201
    assert len(ok.json()["tagged_characters"]) == 5


def test_post_and_tags_are_created_atomically(client, db_session, scene, monkeypatch):
    """A failure after the tags are staged leaves no post and no tag behind."""
    import app.api.routes.posts as posts_route

    def boom(*args, **kwargs):
        raise RuntimeError("notification store unavailable")

    monkeypatch.setattr(posts_route, "notify_character_tagged", boom)
    before = _post_count(db_session)
    with pytest.raises(RuntimeError):
        _create(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    assert _post_count(db_session) == before
    assert db_session.query(PostCharacterTag).count() == 0


# ── 2. projection: live, ids-only, visibility-aware ──────────────────────────

def test_projection_carries_no_account_fields(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    for h in (scene["h_author"], scene["h_owner"], scene["h_viewer"]):
        [tag] = _tags_seen(client, h, post["id"])
        assert set(tag) == {"character_id", "name"}
    raw = client.get(f"/posts/{post['id']}", headers=scene["h_viewer"]).text
    assert "w10owner" not in raw


def test_rename_keeps_the_association_and_shows_the_live_name(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    resp = client.patch(f"/characters/{scene['target']}", json={"name": "Elowen Marr"}, headers=scene["h_owner"])
    assert resp.status_code == 200, resp.text
    assert _tags_seen(client, scene["h_viewer"], post["id"]) == [
        {"character_id": scene["target"], "name": "Elowen Marr"}
    ]


def test_private_target_is_hidden_except_from_its_owner_and_returns_when_public(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    assert client.patch(f"/characters/{scene['target']}", json={"visibility": "private"},
                        headers=scene["h_owner"]).status_code == 200

    assert _tags_seen(client, scene["h_viewer"], post["id"]) == []
    assert _tags_seen(client, scene["h_author"], post["id"]) == []
    assert _tags_seen(client, scene["h_owner"], post["id"]) == [{"character_id": scene["target"], "name": "Elowen"}]
    # Feed agrees with the detail read.
    feed = client.get("/posts/feed", headers=scene["h_viewer"]).json()
    assert next(p for p in feed if p["id"] == post["id"])["tagged_characters"] == []
    # The relationship itself is kept.
    db_session.expire_all()
    assert db_session.query(PostCharacterTag).filter(PostCharacterTag.post_id == post["id"]).count() == 1

    assert client.patch(f"/characters/{scene['target']}", json={"visibility": "public"},
                        headers=scene["h_owner"]).status_code == 200
    assert _tags_seen(client, scene["h_viewer"], post["id"]) == [{"character_id": scene["target"], "name": "Elowen"}]


def test_deleting_the_tagged_character_removes_the_tag_not_the_post(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    assert client.delete(f"/characters/{scene['target']}", headers=scene["h_owner"]).status_code == 204
    db_session.expire_all()
    assert db_session.query(PostCharacterTag).count() == 0
    detail = client.get(f"/posts/{post['id']}", headers=scene["h_viewer"]).json()
    assert detail["tagged_characters"] == []
    assert detail["character_name"] == "Bram"


def test_deleting_the_post_removes_tags_and_tag_notifications(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    assert len(_tag_rows(db_session, scene["owner_id"])) == 1
    assert client.delete(f"/posts/{post['id']}", headers=scene["h_author"]).status_code == 204
    db_session.expire_all()
    assert db_session.query(PostCharacterTag).count() == 0
    assert _tag_rows(db_session, scene["owner_id"]) == []


def test_tags_never_reach_the_authored_timeline_or_public_home(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    timeline = client.get(f"/characters/{scene['target']}/posts", headers=scene["h_viewer"]).json()
    assert post["id"] not in [i["payload"]["id"] for i in timeline]
    db_session.query(Character).filter(Character.id == scene["target"]).update({"public_home_enabled": True})
    db_session.commit()
    home = client.get(f"/characters/{scene['target']}/public-home/posts")
    assert home.status_code == 200
    assert post["id"] not in [p["id"] for p in home.json()]


# ── 3. notifications ─────────────────────────────────────────────────────────

def test_tag_notifies_the_owner_with_ids_and_snapshots(client, db_session, scene):
    content = "Elowen watched the ships come in, one by one. " * 4
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]], content)
    [row] = _tag_rows(db_session, scene["owner_id"])
    p = json.loads(row.payload)
    assert p == {
        "post_id": post["id"],
        "realm_id": scene["realm_id"],
        "author_character_id": scene["author_char"],
        "author_character_name": "Bram",
        "tagged_character_id": scene["target"],
        "tagged_character_name": "Elowen",
        "realm_name": "Tag Realm",
        "post_preview": content[:120],
    }
    assert "w10author" not in row.payload
    assert _all_rows(db_session, scene["author_id"]) == []


def test_private_realm_tag_withholds_preview_from_a_non_member(client, db_session, scene):
    realm_id = _realm(client, scene["h_author"], "Secret Realm", is_public=False)
    content = "The ledger was hidden under the floorboards. " * 3
    post = _post(client, scene["h_author"], realm_id, scene["author_char"], [scene["target"]], content)
    [row] = _tag_rows(db_session, scene["owner_id"])
    p = json.loads(row.payload)
    assert "post_preview" not in p and "realm_name" not in p
    assert "floorboards" not in row.payload and "Secret Realm" not in row.payload
    assert p["post_id"] == post["id"] and p["tagged_character_name"] == "Elowen"
    # The rule matches the destination.
    assert client.get(f"/posts/{post['id']}", headers=scene["h_owner"]).status_code == 404


def test_private_realm_member_recipient_gets_the_preview(client, db_session, scene):
    realm_id = _realm(client, scene["h_author"], "Member Realm", is_public=False)
    _grant(db_session, realm_id, scene["owner_id"])
    _post(client, scene["h_author"], realm_id, scene["author_char"], [scene["target"]], "Lanterns lit.")
    p = json.loads(_tag_rows(db_session, scene["owner_id"])[0].payload)
    assert p["post_preview"] == "Lanterns lit." and p["realm_name"] == "Member Realm"


def test_typed_mentions_no_longer_notify(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [],
                 "Hello @Elowen, the tide is turning.")
    # still parsed, stored and linked for backwards compatibility…
    [m] = post["mentions"]
    assert m["target_type"] == "character" and m["target_id"] == scene["target"]
    # …but no notification of any type is written.
    assert _all_rows(db_session, scene["owner_id"]) == []


def test_tag_and_mention_of_the_same_character_notify_once(client, db_session, scene):
    _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]],
          "Hello @Elowen.")
    rows = _all_rows(db_session, scene["owner_id"])
    assert [r.type for r in rows] == ["character_tagged"]


# ── 4. blocks ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who_blocks", ["owner", "author"])
def test_block_makes_the_tag_inert_without_revealing_it(client, db_session, scene, who_blocks):
    if who_blocks == "owner":
        _block(client, scene["h_owner"], scene["author_id"])
    else:
        _block(client, scene["h_author"], scene["owner_id"])

    resp = _create(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    # The author's answer is exactly what an unblocked tag returns.
    assert resp.status_code == 201
    post = resp.json()
    assert post["tagged_characters"] == [{"character_id": scene["target"], "name": "Elowen"}]
    assert _tags_seen(client, scene["h_author"], post["id"]) == post["tagged_characters"]

    # Nobody else sees it, it notifies nobody, and the Tagged surface omits it.
    assert _all_rows(db_session, scene["owner_id"]) == []
    assert _tags_seen(client, scene["h_viewer"], post["id"]) == []
    assert post["id"] not in _tagged_surface(client, scene["h_viewer"], scene["target"])
    assert post["id"] not in _tagged_surface(client, scene["h_owner"], scene["target"])


def test_block_created_after_tagging_also_suppresses(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    _block(client, scene["h_owner"], scene["author_id"])
    assert _tags_seen(client, scene["h_viewer"], post["id"]) == []
    assert post["id"] not in _tagged_surface(client, scene["h_viewer"], scene["target"])
    assert _tags_seen(client, scene["h_author"], post["id"]) != []
    # Lifting the block restores it.
    assert client.delete(f"/blocks/{scene['author_id']}", headers=scene["h_owner"]).status_code == 204
    assert _tags_seen(client, scene["h_viewer"], post["id"]) != []


# ── 5. the Tagged surface ────────────────────────────────────────────────────

def test_tagged_surface_includes_tags_and_legacy_mentions_once_each(client, db_session, scene):
    tagged = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    mentioned = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [],
                      "Legacy hello to @Elowen.")
    both = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]],
                 "Both ways, @Elowen.")
    unrelated = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [])
    ids = _tagged_surface(client, scene["h_viewer"], scene["target"])
    assert sorted(ids) == sorted([tagged["id"], mentioned["id"], both["id"]])
    assert unrelated["id"] not in ids
    assert len(ids) == len(set(ids))


def test_tagged_surface_respects_realm_access(client, db_session, scene):
    realm_id = _realm(client, scene["h_author"], "Closed Realm", is_public=False)
    post = _post(client, scene["h_author"], realm_id, scene["author_char"], [scene["target"]])
    assert post["id"] not in _tagged_surface(client, scene["h_viewer"], scene["target"])
    _grant(db_session, realm_id, scene["viewer_id"])
    assert post["id"] in _tagged_surface(client, scene["h_viewer"], scene["target"])


def test_tagged_surface_omits_authors_the_viewer_blocked(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]],
                 "And a legacy @Elowen too.")
    assert post["id"] in _tagged_surface(client, scene["h_viewer"], scene["target"])
    _block(client, scene["h_viewer"], scene["author_id"])
    assert post["id"] not in _tagged_surface(client, scene["h_viewer"], scene["target"])


def test_tagged_surface_of_a_private_character_is_owner_only(client, db_session, scene):
    _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    client.patch(f"/characters/{scene['target']}", json={"visibility": "private"}, headers=scene["h_owner"])
    assert client.get(f"/characters/{scene['target']}/mentions", headers=scene["h_viewer"]).status_code == 404
    assert client.get(f"/characters/{scene['target']}/mentions", headers=scene["h_owner"]).status_code == 200


# ── 6. removing a tag ────────────────────────────────────────────────────────

def test_tagged_owner_removes_the_tag(client, db_session, scene):
    content = "Hello @Elowen, by the harbour."
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]], content)
    assert len(_tag_rows(db_session, scene["owner_id"])) == 1

    resp = client.delete(f"/posts/{post['id']}/tags/{scene['target']}", headers=scene["h_owner"])
    assert resp.status_code == 204
    db_session.expire_all()
    assert db_session.query(PostCharacterTag).count() == 0
    assert _tag_rows(db_session, scene["owner_id"]) == []
    detail = client.get(f"/posts/{post['id']}", headers=scene["h_viewer"]).json()
    assert detail["tagged_characters"] == []
    assert detail["content"] == content  # prose untouched
    # the legacy mention row is untouched, so the legacy surface entry remains
    assert db_session.query(PostMention).filter(PostMention.post_id == post["id"]).count() == 1


def test_removed_tag_disappears_from_the_surface(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    assert post["id"] in _tagged_surface(client, scene["h_viewer"], scene["target"])
    client.delete(f"/posts/{post['id']}/tags/{scene['target']}", headers=scene["h_owner"])
    assert post["id"] not in _tagged_surface(client, scene["h_viewer"], scene["target"])


def test_post_author_may_remove_a_tag_they_added(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    assert client.delete(f"/posts/{post['id']}/tags/{scene['target']}", headers=scene["h_author"]).status_code == 204


def test_unrelated_account_cannot_remove_and_learns_nothing(client, db_session, scene):
    post = _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"]])
    real = client.delete(f"/posts/{post['id']}/tags/{scene['target']}", headers=scene["h_viewer"])
    missing = client.delete(f"/posts/{post['id']}/tags/999999", headers=scene["h_viewer"])
    no_post = client.delete(f"/posts/999999/tags/{scene['target']}", headers=scene["h_viewer"])
    assert real.status_code == missing.status_code == no_post.status_code == 404
    assert real.json() == missing.json() == no_post.json()
    db_session.expire_all()
    assert db_session.query(PostCharacterTag).count() == 1


def test_owner_can_remove_a_tag_from_a_post_they_cannot_read(client, db_session, scene):
    realm_id = _realm(client, scene["h_author"], "Locked Realm", is_public=False)
    post = _post(client, scene["h_author"], realm_id, scene["author_char"], [scene["target"]])
    assert client.get(f"/posts/{post['id']}", headers=scene["h_owner"]).status_code == 404
    assert client.delete(f"/posts/{post['id']}/tags/{scene['target']}", headers=scene["h_owner"]).status_code == 204


# ── 7. picker search ─────────────────────────────────────────────────────────

def test_public_only_search_excludes_the_callers_private_characters(client, db_session, scene):
    make_seeder("w10author@w10atest.com")
    _character(client, scene["h_author"], "Bramble Secret", visibility="private")
    names_all = [c["name"] for c in client.get("/characters/search?q=Bram", headers=scene["h_author"]).json()]
    names_pub = [c["name"] for c in client.get("/characters/search?q=Bram&public_only=true",
                                                headers=scene["h_author"]).json()]
    assert "Bramble Secret" in names_all
    assert "Bramble Secret" not in names_pub
    assert "Bram" in names_pub


# ── 8. bounded queries ───────────────────────────────────────────────────────

def _statements_for(client, h, path):
    count = {"n": 0}

    def _count(*_args, **_kwargs):
        count["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        assert client.get(path, headers=h).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    return count["n"]


def test_tag_projection_does_not_grow_with_the_page(client, db_session, scene):
    make_seeder("w10viewer@w10atest.com")
    others = [_character(client, scene["h_viewer"], f"Extra {i}") for i in range(3)]
    for _ in range(2):
        _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"], *others])
    small = _statements_for(client, scene["h_viewer"], "/posts/feed")
    for _ in range(6):
        _post(client, scene["h_author"], scene["realm_id"], scene["author_char"], [scene["target"], *others])
    large = _statements_for(client, scene["h_viewer"], "/posts/feed")
    assert large == small, (small, large)


# ── 9. legacy /users/{username}/mentions ─────────────────────────────────────

def test_legacy_user_mentions_respect_realm_access(client, db_session, scene):
    """Only pre-Sprint-33 rows carry ``mentioned_user_id``; written directly."""
    open_realm = scene["realm_id"]
    closed_realm = _realm(client, scene["h_author"], "Old Closed", is_public=False)
    open_post = _post(client, scene["h_author"], open_realm, scene["author_char"], [])
    closed_post = _post(client, scene["h_author"], closed_realm, scene["author_char"], [])
    for pid in (open_post["id"], closed_post["id"]):
        db_session.add(PostMention(post_id=pid, mention_text="@w10owner", mentioned_user_id=scene["owner_id"]))
    db_session.commit()

    seen = [p["id"] for p in client.get("/users/w10owner/mentions", headers=scene["h_viewer"]).json()]
    assert open_post["id"] in seen
    assert closed_post["id"] not in seen
    _grant(db_session, closed_realm, scene["viewer_id"])
    seen = [p["id"] for p in client.get("/users/w10owner/mentions", headers=scene["h_viewer"]).json()]
    assert closed_post["id"] in seen


# ── 10. migration ────────────────────────────────────────────────────────────

def test_w10a_is_the_single_head_on_top_of_ak01():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    script = ScriptDirectory.from_config(Config(str(ini)))
    assert script.get_heads() == ["w10a_post_character_tags"]
    assert script.get_revision("w10a_post_character_tags").down_revision == "ak01_author_kind"


def test_migration_is_additive_ids_only_and_has_no_backfill():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "alembic/versions/w10a_post_character_tags.py").read_text()
    upgrade = src[src.index("def upgrade"):src.index("def downgrade")]
    assert "op.create_table" in upgrade and "op.create_index" in upgrade
    for forbidden in ("op.execute", "UPDATE", "INSERT", "drop_", "alter_column", "name\"", "user_id"):
        assert forbidden not in upgrade, forbidden


def test_model_matches_the_migration():
    table = PostCharacterTag.__table__
    assert set(table.columns.keys()) == {"id", "post_id", "character_id", "created_at"}
    fks = {fk.parent.name: (fk.column.table.name, fk.ondelete) for fk in table.foreign_keys}
    assert fks == {"post_id": ("posts", "CASCADE"), "character_id": ("characters", "CASCADE")}
    uniques = [c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert [sorted(col.name for col in u.columns) for u in uniques] == [["character_id", "post_id"]]
