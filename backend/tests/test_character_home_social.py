"""Social Pan — the social context on a public Character Home timeline.

Each anonymous timeline entry carries ``social``: aggregate reaction totals,
the exact comment count and the latest three comments with safe attribution.
These tests pin the publication matrix for commenters, the aggregate-only
reaction contract, the realm boundary (social data rides only on posts the
timeline already admitted) and the absence of account identity at any depth.
"""
import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models.character import Character, VisibilityEnum
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.comment import Comment
from app.models.post import Post
from app.models.reaction import Reaction
from app.models.realm import Realm
from app.models.user import User
from tests.conftest import auth_headers, engine, get_auth_token

SOCIAL_FIELDS = {"comment_count", "reactions", "comments"}
PREVIEW_FIELDS = {"id", "content", "provenance", "created_at", "author"}
AUTHOR_FIELDS = {"kind", "name", "avatar_url", "character_id", "linkable"}
ACCOUNT_KEYS = {
    "user_id", "author_user_id", "author_username", "author_avatar_url",
    "owner_id", "owner_username", "email", "username",
}
T0 = datetime(2026, 1, 1, 12, 0, 0)


# ── helpers ─────────────────────────────────────────────────────────────────

def _user(client, db, slug: str) -> tuple[str, int]:
    email = f"{slug}@socialpan.com"
    token = get_auth_token(client, email=email, username=f"acct_{slug}")
    return token, db.query(User).filter(User.email == email).one().id


def _character(db, owner_id, name, *, visibility=VisibilityEnum.PUBLIC,
               published=False, avatar_url=None) -> int:
    char = Character(owner_id=owner_id, name=name, species="human",
                     visibility=visibility, public_home_enabled=published,
                     avatar_url=avatar_url)
    db.add(char)
    db.commit()
    return char.id


def _realm(db, owner_id, *, is_public=True) -> int:
    realm = Realm(owner_id=owner_id, name="Open Square" if is_public else "Hidden Hall",
                  slug=f"soc-{uuid4().hex[:8]}", is_public=is_public)
    db.add(realm)
    db.commit()
    return realm.id


def _post(db, author_id, character_id, realm_id, *, content="A scene.", at=T0) -> int:
    post = Post(author_user_id=author_id, character_id=character_id, realm_id=realm_id,
                content=content, created_at=at)
    db.add(post)
    db.commit()
    return post.id


def _comment(db, post_id, author_id, character_id, content, *, at=T0) -> int:
    row = Comment(post_id=post_id, author_user_id=author_id, character_id=character_id,
                  content=content, created_at=at, updated_at=at)
    db.add(row)
    db.commit()
    return row.id


def _react(db, post_id, user_id, type_):
    db.add(Reaction(post_id=post_id, user_id=user_id, type=type_))
    db.commit()


def _safe_avatar(db, character_id, owner_id) -> str:
    """An avatar the public-media rule admits: a real, active studio image."""
    path = f"static/generated/{uuid4().hex}.png"
    db.add(CharacterImage(
        character_id=character_id, user_id=owner_id, kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE, visibility=ImageVisibilityEnum.PRIVATE,
        provider="fal", prompt_summary="fixture", metadata_json={"library": True},
        file_path=path,
    ))
    url = f"/{path}"
    db.query(Character).filter(Character.id == character_id).update({"avatar_url": url})
    db.commit()
    return url


def _timeline(client, cid, token=None):
    headers = auth_headers(token) if token else {}
    resp = client.get(f"/characters/{cid}/public-home/posts", headers=headers)
    return resp


def _entry(client, cid, post_id, token=None) -> dict:
    resp = _timeline(client, cid, token)
    assert resp.status_code == 200, resp.text
    [entry] = [e for e in resp.json() if e["id"] == post_id]
    return entry


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


@pytest.fixture
def pan(client, db_session):
    """A published Pan with one post in a public realm."""
    token, uid = _user(client, db_session, "pan")
    cid = _character(db_session, uid, "Pan", published=True)
    realm = _realm(db_session, uid)
    return {"token": token, "uid": uid, "cid": cid, "realm": realm,
            "post": _post(db_session, uid, cid, realm)}


# ── 1–3. Shape and reaction totals ──────────────────────────────────────────

def test_a_post_with_no_activity_carries_an_empty_social_block(client, pan):
    social = _entry(client, pan["cid"], pan["post"])["social"]
    assert social == {"comment_count": 0, "reactions": {}, "comments": []}


def test_social_block_has_exactly_the_allowlisted_fields(client, db_session, pan):
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    _comment(db_session, pan["post"], uid, grace, "Morning, Pan.")
    _react(db_session, pan["post"], uid, "heart")

    social = _entry(client, pan["cid"], pan["post"])["social"]
    assert set(social) == SOCIAL_FIELDS
    assert set(social["comments"][0]) == PREVIEW_FIELDS
    assert set(social["comments"][0]["author"]) == AUTHOR_FIELDS


def test_exact_reaction_totals_per_type(client, db_session, pan):
    users = [_user(client, db_session, f"r{i}")[1] for i in range(4)]
    for uid in users[:3]:
        _react(db_session, pan["post"], uid, "heart")
    _react(db_session, pan["post"], users[0], "star")
    for uid in users[:2]:
        _react(db_session, pan["post"], uid, "eyes")

    reactions = _entry(client, pan["cid"], pan["post"])["social"]["reactions"]
    assert reactions == {"heart": 3, "star": 1, "eyes": 2}


def test_zero_totals_and_unknown_types_never_appear(client, db_session, pan):
    _, uid = _user(client, db_session, "r0")
    _react(db_session, pan["post"], uid, "star")
    _react(db_session, pan["post"], uid, "legacy-like")
    _react(db_session, pan["post"], uid, "HEART")

    reactions = _entry(client, pan["cid"], pan["post"])["social"]["reactions"]
    assert reactions == {"star": 1}


# ── 4. No account identity at any depth ─────────────────────────────────────

def test_no_account_identity_at_any_depth(client, db_session, pan):
    from app.core.account_sigils import ACCOUNT_SIGILS

    sigil = next(iter(ACCOUNT_SIGILS.values()))
    w_token, w_uid = _user(client, db_session, "wand")
    db_session.query(User).filter(User.id == w_uid).update({"avatar_url": sigil})
    db_session.commit()
    _, g_uid = _user(client, db_session, "grace")
    grace = _character(db_session, g_uid, "Grace", published=True)
    _, h_uid = _user(client, db_session, "hidden")
    hidden = _character(db_session, h_uid, "Hidden", visibility=VisibilityEnum.PRIVATE)
    _comment(db_session, pan["post"], w_uid, None, "Hello.", at=T0)
    _comment(db_session, pan["post"], g_uid, grace, "Hi.", at=T0 + timedelta(minutes=1))
    _comment(db_session, pan["post"], h_uid, hidden, "Hey.", at=T0 + timedelta(minutes=2))
    for uid in (w_uid, g_uid, h_uid):
        _react(db_session, pan["post"], uid, "heart")

    body = _timeline(client, pan["cid"]).json()
    assert not ACCOUNT_KEYS & set(_walk_keys(body))
    text = json.dumps(body)
    for leaked in ("acct_wand", "acct_grace", "acct_hidden", "acct_pan", sigil,
                   "@socialpan.com", "Hidden"):
        assert leaked not in text, f"{leaked!r} reached the anonymous Home"


# ── 5–11. Commenter publication matrix ──────────────────────────────────────

def test_public_published_commenter_is_linkable(client, db_session, pan):
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    avatar = _safe_avatar(db_session, grace, uid)
    _comment(db_session, pan["post"], uid, grace, "Morning, Pan.")

    [c] = _entry(client, pan["cid"], pan["post"])["social"]["comments"]
    assert c["content"] == "Morning, Pan."
    assert c["author"] == {"kind": "character", "name": "Grace", "avatar_url": avatar,
                           "character_id": grace, "linkable": True}
    # The link it enables really is a Home.
    assert client.get(f"/characters/{grace}/public-home").status_code == 200


def test_public_unpublished_commenter_is_named_but_not_linkable(client, db_session, pan):
    _, uid = _user(client, db_session, "shadow")
    shadow = _character(db_session, uid, "Shadow", published=False)
    avatar = _safe_avatar(db_session, shadow, uid)
    _comment(db_session, pan["post"], uid, shadow, "Watching.")

    [c] = _entry(client, pan["cid"], pan["post"])["social"]["comments"]
    assert c["author"] == {"kind": "character", "name": "Shadow", "avatar_url": avatar,
                           "character_id": None, "linkable": False}
    assert client.get(f"/characters/{shadow}/public-home").status_code == 404


@pytest.mark.parametrize("visibility", [VisibilityEnum.PRIVATE, VisibilityEnum.FRIENDS])
def test_private_and_friends_commenters_are_hidden(client, db_session, pan, visibility):
    _, uid = _user(client, db_session, "secret")
    # Even with the founder flag set: visibility stays authoritative.
    secret = _character(db_session, uid, "Secretname", visibility=visibility, published=True)
    _safe_avatar(db_session, secret, uid)
    _comment(db_session, pan["post"], uid, secret, "Quietly.")

    entry = _entry(client, pan["cid"], pan["post"])
    [c] = entry["social"]["comments"]
    assert c["content"] == "Quietly."
    assert c["author"] == {"kind": "hidden_character", "name": None, "avatar_url": None,
                           "character_id": None, "linkable": False}
    assert "Secretname" not in json.dumps(entry)
    assert f'"{secret}"' not in json.dumps(entry["social"])


def test_deleted_commenter_never_falls_back_to_the_account(client, db_session, pan):
    token, uid = _user(client, db_session, "gone")
    gone = _character(db_session, uid, "Gonename", published=True)
    _comment(db_session, pan["post"], uid, gone, "Before I left.")
    assert client.delete(f"/characters/{gone}", headers=auth_headers(token)).status_code == 204
    db_session.expire_all()
    assert db_session.query(Comment).filter(Comment.post_id == pan["post"]).one().character_id is None

    entry = _entry(client, pan["cid"], pan["post"])
    [c] = entry["social"]["comments"]
    assert c["content"] == "Before I left."
    assert c["author"] == {"kind": "wanderer", "name": None, "avatar_url": None,
                           "character_id": None, "linkable": False}
    assert "acct_gone" not in json.dumps(entry)
    assert "Gonename" not in json.dumps(entry)


def test_wanderer_comment_carries_no_account_identity(client, db_session, pan):
    _, uid = _user(client, db_session, "roam")
    _comment(db_session, pan["post"], uid, None, "Passing through.")

    entry = _entry(client, pan["cid"], pan["post"])
    [c] = entry["social"]["comments"]
    assert c["author"]["kind"] == "wanderer"
    assert c["author"]["name"] is None and c["author"]["linkable"] is False
    assert "acct_roam" not in json.dumps(entry)


def test_unsafe_commenter_avatar_is_withheld_but_the_comment_renders(client, db_session, pan):
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True,
                       avatar_url="https://evil.example/tracker.png")
    _comment(db_session, pan["post"], uid, grace, "Still here.")

    [c] = _entry(client, pan["cid"], pan["post"])["social"]["comments"]
    assert c["content"] == "Still here."
    assert c["author"]["name"] == "Grace"
    assert c["author"]["avatar_url"] is None


def test_archived_commenter_avatar_is_withheld(client, db_session, pan):
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    _safe_avatar(db_session, grace, uid)
    db_session.query(CharacterImage).filter(CharacterImage.character_id == grace).update(
        {"status": ImageStatusEnum.ARCHIVED})
    db_session.commit()
    _comment(db_session, pan["post"], uid, grace, "Hi.")

    [c] = _entry(client, pan["cid"], pan["post"])["social"]["comments"]
    assert c["author"]["avatar_url"] is None


# ── 12–13. Latest three, exact count ────────────────────────────────────────

def test_latest_three_comments_in_reading_order_with_exact_count(client, db_session, pan):
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    for i in range(7):
        _comment(db_session, pan["post"], uid, grace, f"c{i}", at=T0 + timedelta(minutes=i))

    social = _entry(client, pan["cid"], pan["post"])["social"]
    assert social["comment_count"] == 7
    assert [c["content"] for c in social["comments"]] == ["c4", "c5", "c6"]


def test_identical_timestamps_select_deterministically_by_id(client, db_session, pan):
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    ids = [_comment(db_session, pan["post"], uid, grace, f"same{i}") for i in range(5)]

    first = _entry(client, pan["cid"], pan["post"])["social"]["comments"]
    again = _entry(client, pan["cid"], pan["post"])["social"]["comments"]
    assert [c["id"] for c in first] == ids[-3:]
    assert first == again


def test_each_post_gets_only_its_own_social_data(client, db_session, pan):
    other = _post(db_session, pan["uid"], pan["cid"], pan["realm"], content="Second.",
                  at=T0 + timedelta(hours=1))
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    _comment(db_session, other, uid, grace, "On the second.")
    _react(db_session, pan["post"], uid, "eyes")

    first = _entry(client, pan["cid"], pan["post"])["social"]
    second = _entry(client, pan["cid"], other)["social"]
    assert first == {"comment_count": 0, "reactions": {"eyes": 1}, "comments": []}
    assert second["comment_count"] == 1 and second["reactions"] == {}


# ── 14–17. Realm and publication boundaries ─────────────────────────────────

def test_private_realm_and_realmless_posts_bring_no_social_data(client, db_session, pan):
    hidden_realm = _realm(db_session, pan["uid"], is_public=False)
    private_post = _post(db_session, pan["uid"], pan["cid"], hidden_realm, content="Private.")
    realmless = _post(db_session, pan["uid"], pan["cid"], None, content="Nowhere.")
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    for pid, text in ((private_post, "Private reply"), (realmless, "Realmless reply")):
        _comment(db_session, pid, uid, grace, text)
        _react(db_session, pid, uid, "heart")

    body = _timeline(client, pan["cid"]).json()
    assert [e["id"] for e in body] == [pan["post"]]
    assert body[0]["social"] == {"comment_count": 0, "reactions": {}, "comments": []}
    text = json.dumps(body)
    assert "Private reply" not in text and "Realmless reply" not in text


def test_unpublished_pan_home_is_still_404(client, db_session, pan):
    db_session.query(Character).filter(Character.id == pan["cid"]).update(
        {"public_home_enabled": False})
    db_session.commit()
    assert _timeline(client, pan["cid"]).status_code == 404
    assert client.get(f"/characters/{pan['cid']}/public-home").status_code == 404


@pytest.mark.parametrize("visibility", [VisibilityEnum.PRIVATE, VisibilityEnum.FRIENDS])
def test_non_public_pan_home_is_still_404(client, db_session, pan, visibility):
    db_session.query(Character).filter(Character.id == pan["cid"]).update(
        {"visibility": visibility})
    db_session.commit()
    assert _timeline(client, pan["cid"]).status_code == 404


# ── 18. One projection for every viewer ─────────────────────────────────────

def test_owner_stranger_and_anonymous_see_the_identical_social_projection(
    client, db_session, pan
):
    g_token, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    _comment(db_session, pan["post"], uid, grace, "Morning.")
    _react(db_session, pan["post"], uid, "star")
    stranger, _ = _user(client, db_session, "stranger")

    views = [_timeline(client, pan["cid"], t).json() for t in (None, stranger, pan["token"], g_token)]
    assert all(v == views[0] for v in views)


# ── Performance: query count does not grow with the page ───────────────────

def _count_queries(fn) -> int:
    seen = []

    def before(conn, cursor, statement, *a):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return len(seen)


def test_social_context_costs_a_constant_number_of_queries(client, db_session, pan):
    _, uid = _user(client, db_session, "grace")
    grace = _character(db_session, uid, "Grace", published=True)
    _safe_avatar(db_session, grace, uid)

    def populate(n):
        for i in range(n):
            pid = _post(db_session, pan["uid"], pan["cid"], pan["realm"],
                        at=T0 + timedelta(hours=len(str(i)) + i))
            for j in range(4):
                _comment(db_session, pid, uid, grace, f"p{pid}c{j}", at=T0 + timedelta(minutes=j))
            _react(db_session, pid, uid, "heart")

    populate(2)
    small = _count_queries(lambda: _timeline(client, pan["cid"]))
    populate(10)
    large = _count_queries(lambda: _timeline(client, pan["cid"]))
    assert large == small, (small, large)
