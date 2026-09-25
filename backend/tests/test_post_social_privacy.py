"""Post social surfaces: privacy and access-control containment.

``GET /comments/posts/{id}/comments`` and ``GET /reactions/posts/{id}/reactions``
authenticate optionally, so they reach readers with no token at all. These
tests pin the contract those endpoints now keep:

* an ANONYMOUS response never carries account infrastructure — no
  ``author_user_id``, ``author_username``, account sigil or reaction
  ``user_id`` — whatever kind of comment it is, including a Writer's comment
  whose character has since been deleted (``ON DELETE SET NULL``);
* an anonymous reader sees a commenting character only when that character is
  PUBLIC; PRIVATE and FRIENDS characters are not published by commenting;
* a signed-in reader sees only their OWN reaction ``user_id``;
* reads AND writes follow the post's visibility: a private realm's post is 404
  to a non-member for reading, commenting and reacting alike, and a realm-less
  post is 404 to an anonymous reader;
* reactions are limited to ``heart``, ``star`` and ``eyes`` on write, and a
  historical row outside that set is dropped on read.
"""
import pytest

from app.models.character import Character, VisibilityEnum
from app.models.comment import Comment
from app.models.post import Post
from app.models.reaction import Reaction
from app.models.realm import Realm, RealmMembership
from app.models.user import User
from tests.conftest import auth_headers, get_auth_token

ACCOUNT_KEYS = ("author_user_id", "author_username", "author_avatar_url")


# ── fixtures ────────────────────────────────────────────────────────────────

def _user_id(db, email: str) -> int:
    return db.query(User).filter(User.email == email).one().id


def _character(db, owner_id: int, name: str, visibility=VisibilityEnum.PUBLIC) -> int:
    char = Character(owner_id=owner_id, name=name, species="human", visibility=visibility)
    db.add(char)
    db.commit()
    return char.id


def _realm(db, owner_id: int, slug: str, *, is_public: bool) -> int:
    realm = Realm(owner_id=owner_id, name=f"Realm {slug}", slug=slug, is_public=is_public)
    db.add(realm)
    db.commit()
    db.add(RealmMembership(realm_id=realm.id, user_id=owner_id, role="owner"))
    db.commit()
    return realm.id


def _post(db, author_id: int, character_id, realm_id) -> int:
    post = Post(author_user_id=author_id, character_id=character_id, realm_id=realm_id,
                content="A post.")
    db.add(post)
    db.commit()
    return post.id


def _comments(client, post_id: int, token: str | None = None):
    headers = auth_headers(token) if token else {}
    return client.get(f"/comments/posts/{post_id}/comments", headers=headers)


def _reactions(client, post_id: int, token: str | None = None):
    headers = auth_headers(token) if token else {}
    return client.get(f"/reactions/posts/{post_id}/reactions", headers=headers)


def _comment(client, token: str, post_id: int, character_id: int | None = None,
             content: str = "A comment."):
    body = {"content": content}
    if character_id is not None:
        body["character_id"] = character_id
    return client.post(f"/comments/posts/{post_id}/comments", json=body,
                       headers=auth_headers(token))


def _react(client, token: str, post_id: int, type_: str = "heart"):
    return client.post(f"/reactions/posts/{post_id}/reactions", json={"type": type_},
                       headers=auth_headers(token))


@pytest.fixture
def world(client, db_session):
    """A realm owner with a PUBLIC character, a public and a private realm, a
    post in each, a private-realm member and an unrelated outsider."""
    owner = get_auth_token(client, email="sp_owner@test.com", username="sp_owner_acct")
    member = get_auth_token(client, email="sp_member@test.com", username="sp_member_acct")
    outsider = get_auth_token(client, email="sp_out@test.com", username="sp_outsider_acct")
    owner_id = _user_id(db_session, "sp_owner@test.com")
    member_id = _user_id(db_session, "sp_member@test.com")

    owner_char = _character(db_session, owner_id, "Owner Public")
    member_char = _character(db_session, member_id, "Member Public")
    pub_realm = _realm(db_session, owner_id, "sp-pub", is_public=True)
    priv_realm = _realm(db_session, owner_id, "sp-priv", is_public=False)
    db_session.add(RealmMembership(realm_id=priv_realm, user_id=member_id, role="member"))
    db_session.commit()

    return {
        "owner": owner, "member": member, "outsider": outsider,
        "owner_id": owner_id, "member_id": member_id,
        "owner_char": owner_char, "member_char": member_char,
        "pub_post": _post(db_session, owner_id, owner_char, pub_realm),
        "priv_post": _post(db_session, owner_id, owner_char, priv_realm),
        "realmless_post": _post(db_session, owner_id, owner_char, None),
    }


def _assert_no_account_identity(payload: dict, label: str = "") -> None:
    for key in ACCOUNT_KEYS:
        assert payload.get(key) is None, f"{label}: {key}={payload.get(key)!r} leaked"


# ── comment privacy (anonymous) ─────────────────────────────────────────────

def test_public_commenter_character_is_visible_anonymously(client, db_session, world):
    assert _comment(client, world["member"], world["pub_post"], world["member_char"]).status_code == 201

    [c] = _comments(client, world["pub_post"]).json()
    assert c["character_id"] == world["member_char"]
    assert c["character_name"] == "Member Public"
    _assert_no_account_identity(c, "public character comment")


@pytest.mark.parametrize("visibility", [VisibilityEnum.PRIVATE, VisibilityEnum.FRIENDS])
def test_non_public_commenter_character_is_withheld_anonymously(
    client, db_session, world, visibility
):
    uid = _user_id(db_session, "sp_member@test.com")
    hidden = _character(db_session, uid, "Hidden Name", visibility=visibility)
    assert _comment(client, world["member"], world["pub_post"], hidden).status_code == 201

    [c] = _comments(client, world["pub_post"]).json()
    assert c["content"] == "A comment.", "the comment itself is still served"
    assert c["character_id"] is None
    assert c["character_name"] is None
    assert c["character_avatar_url"] is None
    _assert_no_account_identity(c, visibility.value)
    assert "Hidden Name" not in _comments(client, world["pub_post"]).text


def test_wanderer_comment_carries_no_account_identity_anonymously(client, db_session, world):
    wanderer = get_auth_token(client, email="sp_w@test.com", username="sp_wanderer_acct")
    assert _comment(client, wanderer, world["pub_post"]).status_code == 201

    resp = _comments(client, world["pub_post"])
    [c] = resp.json()
    _assert_no_account_identity(c, "wanderer")
    assert c["character_id"] is None
    assert "sp_wanderer_acct" not in resp.text


def test_wanderer_attribution_is_unchanged_for_signed_in_readers(client, db_session, world):
    """The Wanderer username stays the public identity inside the product."""
    wanderer = get_auth_token(client, email="sp_w@test.com", username="sp_wanderer_acct")
    assert _comment(client, wanderer, world["pub_post"]).status_code == 201

    [c] = _comments(client, world["pub_post"], world["outsider"]).json()
    assert c["author_username"] == "sp_wanderer_acct"


def test_author_still_sees_their_own_identity(client, db_session, world):
    assert _comment(client, world["member"], world["pub_post"], world["member_char"]).status_code == 201

    [own] = _comments(client, world["pub_post"], world["member"]).json()
    assert own["author_user_id"] == world["member_id"]
    assert own["author_username"] == "sp_member_acct"
    [other] = _comments(client, world["pub_post"], world["outsider"]).json()
    _assert_no_account_identity(other, "signed-in non-author")


def test_no_account_sigil_reaches_an_anonymous_reader(client, db_session, world):
    from app.core.account_sigils import ACCOUNT_SIGILS

    wanderer = get_auth_token(client, email="sp_w@test.com", username="sp_wanderer_acct")
    sigil = next(iter(ACCOUNT_SIGILS.values()))
    assert client.patch("/users/me", json={"avatar_url": sigil},
                        headers=auth_headers(wanderer)).status_code == 200
    assert _comment(client, wanderer, world["pub_post"]).status_code == 201

    [c] = _comments(client, world["pub_post"]).json()
    assert c["author_avatar_url"] is None


# ── deleted-character lifecycle ─────────────────────────────────────────────

def test_deleted_commenter_character_never_falls_back_to_the_account(
    client, db_session, world
):
    """Writer comments as Character A → A is deleted → the comment remains →
    an anonymous read must not reveal the Writer's account."""
    assert _comment(client, world["member"], world["pub_post"], world["member_char"]).status_code == 201

    assert client.delete(f"/characters/{world['member_char']}",
                         headers=auth_headers(world["member"])).status_code == 204
    db_session.expire_all()
    row = db_session.query(Comment).filter(Comment.post_id == world["pub_post"]).one()
    assert row.character_id is None, "precondition: ON DELETE SET NULL orphaned the comment"

    resp = _comments(client, world["pub_post"])
    assert resp.status_code == 200
    [c] = resp.json()
    assert c["content"] == "A comment."
    _assert_no_account_identity(c, "deleted-character comment")
    assert c["character_id"] is None and c["character_name"] is None
    assert "sp_member_acct" not in resp.text


def test_deleted_character_posts_leave_the_public_home_timeline(client, db_session, world):
    """The equivalent anonymous POST projection: the Public Character Home is
    keyed on the character, so a deleted character's orphaned posts are simply
    unreachable anonymously — there is no account fallback to leak."""
    db_session.query(Character).filter(Character.id == world["owner_char"]).update(
        {"public_home_enabled": True})
    db_session.commit()
    assert client.get(f"/characters/{world['owner_char']}/public-home/posts").status_code == 200

    assert client.delete(f"/characters/{world['owner_char']}",
                         headers=auth_headers(world["owner"])).status_code == 204
    assert client.get(f"/characters/{world['owner_char']}/public-home/posts").status_code == 404


# ── reaction privacy and allowlist ──────────────────────────────────────────

def test_reactions_expose_no_account_id_anonymously(client, db_session, world):
    for token in (world["owner"], world["member"]):
        assert _react(client, token, world["pub_post"]).status_code == 201

    resp = _reactions(client, world["pub_post"])
    assert resp.status_code == 200
    assert [r["type"] for r in resp.json()] == ["heart", "heart"]
    assert all(r["user_id"] is None for r in resp.json())


def test_signed_in_reader_sees_only_their_own_reaction_user_id(client, db_session, world):
    assert _react(client, world["owner"], world["pub_post"], "star").status_code == 201
    created = _react(client, world["member"], world["pub_post"], "star")
    assert created.status_code == 201
    assert created.json()["user_id"] == world["member_id"]

    rows = _reactions(client, world["pub_post"], world["member"]).json()
    mine = [r for r in rows if r["user_id"] is not None]
    assert [r["id"] for r in mine] == [created.json()["id"]]
    assert mine[0]["user_id"] == world["member_id"]
    assert len(rows) == 2

    # And the toggle-off path the client uses still works on its own reaction.
    assert client.delete(f"/reactions/{created.json()['id']}",
                         headers=auth_headers(world["member"])).status_code == 204


@pytest.mark.parametrize("type_", ["heart", "star", "eyes"])
def test_allowed_reaction_types_are_accepted(client, db_session, world, type_):
    resp = _react(client, world["member"], world["pub_post"], type_)
    assert resp.status_code == 201, resp.text
    assert resp.json()["type"] == type_


@pytest.mark.parametrize("type_", ["like", "HEART", "", "<script>", "x" * 50])
def test_unknown_reaction_types_are_rejected(client, db_session, world, type_):
    assert _react(client, world["member"], world["pub_post"], type_).status_code == 422
    assert db_session.query(Reaction).count() == 0


def test_historical_unknown_reaction_type_is_not_served(client, db_session, world):
    db_session.add(Reaction(post_id=world["pub_post"], user_id=world["owner_id"], type="legacy-label"))
    db_session.commit()
    assert _react(client, world["member"], world["pub_post"], "eyes").status_code == 201

    for token in (None, world["owner"]):
        assert [r["type"] for r in _reactions(client, world["pub_post"], token).json()] == ["eyes"]


# ── read access ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reader", ["anonymous", "outsider", "member", "owner"])
def test_public_realm_social_reads_are_open(client, world, reader):
    token = None if reader == "anonymous" else world[reader]
    assert _comments(client, world["pub_post"], token).status_code == 200
    assert _reactions(client, world["pub_post"], token).status_code == 200


@pytest.mark.parametrize("reader,expected", [
    ("anonymous", 404), ("outsider", 404), ("member", 200), ("owner", 200),
])
def test_private_realm_social_reads_follow_membership(client, world, reader, expected):
    token = None if reader == "anonymous" else world[reader]
    assert _comments(client, world["priv_post"], token).status_code == expected
    assert _reactions(client, world["priv_post"], token).status_code == expected


@pytest.mark.parametrize("reader,expected", [
    ("anonymous", 404), ("outsider", 200), ("owner", 200),
])
def test_realmless_post_is_not_public(client, world, reader, expected):
    """Anonymous fails closed, as the Character Home timeline does; signed-in
    access matches ``GET /posts/{id}``, which serves realm-less posts."""
    token = None if reader == "anonymous" else world[reader]
    assert _comments(client, world["realmless_post"], token).status_code == expected
    assert _reactions(client, world["realmless_post"], token).status_code == expected
    if token:
        assert client.get(f"/posts/{world['realmless_post']}",
                          headers=auth_headers(token)).status_code == 200


def test_missing_post_is_indistinguishable_from_an_inaccessible_one(client, world):
    for token in (None, world["outsider"]):
        assert _comments(client, 999_999, token).status_code == 404
        assert _reactions(client, 999_999, token).status_code == 404


# ── write access ────────────────────────────────────────────────────────────

def test_private_realm_non_member_cannot_comment(client, db_session, world):
    resp = _comment(client, world["outsider"], world["priv_post"])
    assert resp.status_code == 404
    assert db_session.query(Comment).count() == 0


def test_private_realm_non_member_cannot_react(client, db_session, world):
    resp = _react(client, world["outsider"], world["priv_post"])
    assert resp.status_code == 404
    assert db_session.query(Reaction).count() == 0


def test_private_realm_member_can_comment_and_react(client, db_session, world):
    assert _comment(client, world["member"], world["priv_post"], world["member_char"]).status_code == 201
    assert _react(client, world["member"], world["priv_post"], "eyes").status_code == 201

    comments = _comments(client, world["priv_post"], world["owner"]).json()
    reactions = _reactions(client, world["priv_post"], world["owner"]).json()
    assert [c["character_name"] for c in comments] == ["Member Public"]
    assert [r["type"] for r in reactions] == ["eyes"]


def test_public_realm_writes_still_work_for_any_signed_in_account(client, db_session, world):
    outsider_id = _user_id(db_session, "sp_out@test.com")
    outsider_char = _character(db_session, outsider_id, "Outsider Public")
    assert _comment(client, world["outsider"], world["pub_post"], outsider_char).status_code == 201
    assert _react(client, world["outsider"], world["pub_post"], "star").status_code == 201


def test_realmless_post_writes_follow_signed_in_read_access(client, db_session, world):
    assert _comment(client, world["member"], world["realmless_post"], world["member_char"]).status_code == 201
    assert _react(client, world["member"], world["realmless_post"]).status_code == 201


def test_writes_to_a_missing_post_are_404(client, world):
    assert _comment(client, world["member"], 999_999, world["member_char"]).status_code == 404
    assert _react(client, world["member"], 999_999).status_code == 404


def test_anonymous_writes_are_refused(client, world):
    assert client.post(f"/comments/posts/{world['pub_post']}/comments",
                       json={"content": "hi"}).status_code in (401, 403)
    assert client.post(f"/reactions/posts/{world['pub_post']}/reactions",
                       json={"type": "heart"}).status_code in (401, 403)
