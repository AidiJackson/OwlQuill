"""W-07A — an author can always remove what they published.

Two endpoints, one rule: ``author_user_id`` is the only thing that grants
deletion. Seeing the content, belonging to its realm, owning its realm or
owning some other character grants nothing.

* ``DELETE /comments/{id}`` — new. Hard delete; nothing references a comment.
* ``DELETE /posts/{id}`` — existing hard delete, pinned here over HTTP for the
  first time, plus the cleanup it now does: mention notifications snapshot a
  preview of the post body, so they are removed with it, matched by parsed
  ``post_id`` and never by text.

Both are checked through the reads that matter, including the anonymous
Public Character Home, which has no controls of its own and must simply stop
returning what was deleted.
"""
import json

import pytest

from app.models.character import Character, VisibilityEnum
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.comment import Comment
from app.models.notification import Notification
from app.models.post import Post
from app.models.post_mention import PostMention
from app.models.reaction import Reaction
from app.models.realm import Realm, RealmMembership
from app.models.user import User
from app.services.notifications import create_notification
from tests.conftest import auth_headers, get_auth_token


# ── fixtures ────────────────────────────────────────────────────────────────

def _user_id(db, email: str) -> int:
    return db.query(User).filter(User.email == email).one().id


def _character(db, owner_id: int, name: str, *, published: bool = False) -> int:
    char = Character(owner_id=owner_id, name=name, species="human",
                     visibility=VisibilityEnum.PUBLIC, public_home_enabled=published)
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


def _join(db, realm_id: int, user_id: int) -> None:
    db.add(RealmMembership(realm_id=realm_id, user_id=user_id, role="member"))
    db.commit()


def _post(db, author_id: int, character_id, realm_id, **over) -> int:
    post = Post(author_user_id=author_id, character_id=character_id, realm_id=realm_id,
                content=over.pop("content", "A post."), **over)
    db.add(post)
    db.commit()
    return post.id


def _comment(client, token: str, post_id: int, character_id: int | None = None,
             content: str = "A comment.") -> int:
    body = {"content": content}
    if character_id is not None:
        body["character_id"] = character_id
    resp = client.post(f"/comments/posts/{post_id}/comments", json=body,
                       headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _delete_comment(client, comment_id: int, token: str | None = None):
    headers = auth_headers(token) if token else {}
    return client.delete(f"/comments/{comment_id}", headers=headers)


def _delete_post(client, post_id: int, token: str | None = None):
    headers = auth_headers(token) if token else {}
    return client.delete(f"/posts/{post_id}", headers=headers)


def _comment_ids(client, post_id: int, token: str | None = None) -> list[int]:
    headers = auth_headers(token) if token else {}
    resp = client.get(f"/comments/posts/{post_id}/comments", headers=headers)
    assert resp.status_code == 200, resp.text
    return [c["id"] for c in resp.json()]


def _home_posts(client, character_id: int) -> list[dict]:
    resp = client.get(f"/characters/{character_id}/public-home/posts")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def world(client, db_session):
    """A realm owner, a post author, a fellow realm member and an outsider.

    The AUTHOR is deliberately not the realm owner, so "owns the realm" and
    "wrote the content" can be told apart. The author's character has a
    published Home, so the anonymous projection can be checked too.
    """
    realm_owner = get_auth_token(client, email="w7_owner@test.com", username="w7_owner")
    author = get_auth_token(client, email="w7_author@test.com", username="w7_author")
    member = get_auth_token(client, email="w7_member@test.com", username="w7_member")
    outsider = get_auth_token(client, email="w7_out@test.com", username="w7_outsider")
    ids = {k: _user_id(db_session, f"w7_{k}@test.com")
           for k in ("owner", "author", "member", "out")}

    author_char = _character(db_session, ids["author"], "Author Char", published=True)
    member_char = _character(db_session, ids["member"], "Mira")
    owner_char = _character(db_session, ids["owner"], "Owner Char")

    pub_realm = _realm(db_session, ids["owner"], "w7-pub", is_public=True)
    priv_realm = _realm(db_session, ids["owner"], "w7-priv", is_public=False)
    for realm in (pub_realm, priv_realm):
        _join(db_session, realm, ids["author"])
        _join(db_session, realm, ids["member"])

    return {
        "realm_owner": realm_owner, "author": author, "member": member,
        "outsider": outsider, "ids": ids,
        "author_char": author_char, "member_char": member_char, "owner_char": owner_char,
        "pub_realm": pub_realm, "priv_realm": priv_realm,
        "pub_post": _post(db_session, ids["author"], author_char, pub_realm),
        "priv_post": _post(db_session, ids["author"], author_char, priv_realm),
    }


# ── comment delete: who may ────────────────────────────────────────────────

def test_author_can_delete_their_own_wanderer_comment(client, db_session, world):
    wanderer = get_auth_token(client, email="w7_wand@test.com", username="w7_wanderer")
    cid = _comment(client, wanderer, world["pub_post"])

    assert _delete_comment(client, cid, wanderer).status_code == 204
    assert db_session.query(Comment).filter(Comment.id == cid).first() is None


def test_author_can_delete_a_comment_written_as_their_character(client, db_session, world):
    cid = _comment(client, world["member"], world["pub_post"], world["member_char"])

    assert _delete_comment(client, cid, world["member"]).status_code == 204
    assert cid not in _comment_ids(client, world["pub_post"], world["member"])


def test_author_keeps_delete_after_their_character_is_deleted(client, db_session, world):
    """``character_id`` goes NULL on character delete; ``author_user_id`` does not."""
    cid = _comment(client, world["member"], world["pub_post"], world["member_char"])
    assert client.delete(f"/characters/{world['member_char']}",
                         headers=auth_headers(world["member"])).status_code == 204

    assert _delete_comment(client, cid, world["member"]).status_code == 204


def test_author_keeps_delete_after_leaving_a_private_realm(client, db_session, world):
    cid = _comment(client, world["member"], world["priv_post"], world["member_char"])
    db_session.query(RealmMembership).filter(
        RealmMembership.realm_id == world["priv_realm"],
        RealmMembership.user_id == world["ids"]["member"],
    ).delete()
    db_session.commit()

    assert _delete_comment(client, cid, world["member"]).status_code == 204


def test_non_author_cannot_delete(client, db_session, world):
    cid = _comment(client, world["member"], world["pub_post"], world["member_char"])

    assert _delete_comment(client, cid, world["outsider"]).status_code == 403
    assert cid in _comment_ids(client, world["pub_post"])


def test_realm_member_gains_no_delete_permission(client, db_session, world):
    cid = _comment(client, world["member"], world["priv_post"], world["member_char"])

    # The post's author is also a member of this realm and can see the comment.
    assert _delete_comment(client, cid, world["author"]).status_code == 403
    assert db_session.query(Comment).filter(Comment.id == cid).first() is not None


def test_realm_owner_gains_no_delete_permission(client, db_session, world):
    cid = _comment(client, world["member"], world["pub_post"], world["member_char"])

    assert _delete_comment(client, cid, world["realm_owner"]).status_code == 403
    assert db_session.query(Comment).filter(Comment.id == cid).first() is not None


def test_owning_another_character_gains_no_delete_permission(client, db_session, world):
    """The realm owner commenting as their own character cannot remove someone
    else's character comment either — character ownership is per comment."""
    mine = _comment(client, world["realm_owner"], world["pub_post"], world["owner_char"])
    theirs = _comment(client, world["member"], world["pub_post"], world["member_char"])

    assert _delete_comment(client, theirs, world["realm_owner"]).status_code == 403
    assert _delete_comment(client, mine, world["realm_owner"]).status_code == 204


def test_anonymous_caller_cannot_delete(client, db_session, world):
    cid = _comment(client, world["member"], world["pub_post"], world["member_char"])

    assert _delete_comment(client, cid).status_code in (401, 403)
    assert db_session.query(Comment).filter(Comment.id == cid).first() is not None


def test_private_realm_comment_is_404_to_an_outsider(client, db_session, world):
    """A caller who cannot read the post learns nothing about its comment ids —
    the same answer as a comment that never existed."""
    cid = _comment(client, world["member"], world["priv_post"], world["member_char"])

    assert _delete_comment(client, cid, world["outsider"]).status_code == 404
    assert _delete_comment(client, 999_999, world["outsider"]).status_code == 404
    assert db_session.query(Comment).filter(Comment.id == cid).first() is not None


# ── comment delete: what readers see ───────────────────────────────────────

def test_deleted_comment_leaves_the_read_path_and_the_count(client, db_session, world):
    keep = _comment(client, world["member"], world["pub_post"], world["member_char"], "Keep.")
    gone = _comment(client, world["member"], world["pub_post"], world["member_char"], "Gone.")

    assert _delete_comment(client, gone, world["member"]).status_code == 204

    assert _comment_ids(client, world["pub_post"]) == [keep]
    post = client.get(f"/posts/{world['pub_post']}", headers=auth_headers(world["member"]))
    assert post.json()["comment_count"] == 1


def test_public_home_social_projection_reflects_comment_deletion(client, db_session, world):
    keep = _comment(client, world["member"], world["pub_post"], world["member_char"], "Keep.")
    gone = _comment(client, world["member"], world["pub_post"], world["member_char"], "Gone.")
    [before] = _home_posts(client, world["author_char"])
    assert before["social"]["comment_count"] == 2

    assert _delete_comment(client, gone, world["member"]).status_code == 204

    [after] = _home_posts(client, world["author_char"])
    assert after["social"]["comment_count"] == 1
    assert [c["id"] for c in after["social"]["comments"]] == [keep]
    assert "Gone." not in json.dumps(after)


# ── post delete over HTTP ──────────────────────────────────────────────────

def test_author_can_delete_their_post(client, db_session, world):
    assert _delete_post(client, world["pub_post"], world["author"]).status_code == 204
    assert db_session.query(Post).filter(Post.id == world["pub_post"]).first() is None
    assert client.get(f"/posts/{world['pub_post']}",
                      headers=auth_headers(world["author"])).status_code == 404


@pytest.mark.parametrize("who", ["member", "realm_owner", "outsider"])
def test_non_author_cannot_delete_a_post(client, db_session, world, who):
    assert _delete_post(client, world["pub_post"], world[who]).status_code == 403
    assert db_session.query(Post).filter(Post.id == world["pub_post"]).first() is not None


def test_anonymous_caller_cannot_delete_a_post(client, db_session, world):
    assert _delete_post(client, world["pub_post"]).status_code in (401, 403)
    assert db_session.query(Post).filter(Post.id == world["pub_post"]).first() is not None


def test_post_delete_cascades_comments_reactions_and_mentions(client, db_session, world):
    pid = world["pub_post"]
    _comment(client, world["member"], pid, world["member_char"])
    assert client.post(f"/reactions/posts/{pid}/reactions", json={"type": "heart"},
                       headers=auth_headers(world["member"])).status_code == 201
    db_session.add(PostMention(post_id=pid, mention_text="@Member",
                               mentioned_character_id=world["member_char"]))
    db_session.commit()

    assert _delete_post(client, pid, world["author"]).status_code == 204

    db_session.expire_all()
    assert db_session.query(Comment).filter(Comment.post_id == pid).count() == 0
    assert db_session.query(Reaction).filter(Reaction.post_id == pid).count() == 0
    assert db_session.query(PostMention).filter(PostMention.post_id == pid).count() == 0


def test_post_delete_leaves_the_attached_image_in_the_library(client, db_session, world):
    path = "static/generated/w7-attached.png"
    image = CharacterImage(
        character_id=world["author_char"], user_id=world["ids"]["author"],
        kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE, provider="stub", file_path=path,
    )
    db_session.add(image)
    db_session.commit()
    image_id = image.id
    pid = _post(db_session, world["ids"]["author"], world["author_char"],
                world["pub_realm"], image_url=f"/{path}")

    assert _delete_post(client, pid, world["author"]).status_code == 204

    db_session.expire_all()
    survivor = db_session.query(CharacterImage).filter(CharacterImage.id == image_id).first()
    assert survivor is not None
    assert survivor.status == ImageStatusEnum.ACTIVE


def test_public_home_no_longer_returns_the_deleted_post(client, db_session, world):
    assert [p["id"] for p in _home_posts(client, world["author_char"])] == [world["pub_post"]]

    assert _delete_post(client, world["pub_post"], world["author"]).status_code == 204

    assert _home_posts(client, world["author_char"]) == []


# ── post delete: mention notification cleanup ──────────────────────────────

def _notify(db, user_id: int, type_: str, payload) -> int:
    if isinstance(payload, dict):
        row = create_notification(db, user_id=user_id, type=type_, payload=payload)
    else:  # a raw, possibly malformed payload string
        row = Notification(user_id=user_id, type=type_, payload=payload)
        db.add(row)
    db.commit()
    return row.id


def _surviving(db, ids: list[int]) -> set[int]:
    db.expire_all()
    return {n.id for n in db.query(Notification).filter(Notification.id.in_(ids)).all()}


def test_a_real_tag_notification_is_removed_with_its_post(client, db_session, world):
    """End to end: the tag path writes the preview, the delete removes it.

    W-10A: typed @mentions no longer notify, so the live producer of a
    preview-carrying post notification is an explicit character tag."""
    resp = client.post(
        f"/posts/realms/{world['pub_realm']}/posts",
        json={"content": "Wrong words for @Mira to read.",
              "character_id": world["author_char"],
              "tagged_character_ids": [world["member_char"]]},
        headers=auth_headers(world["author"]),
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    rows = db_session.query(Notification).filter(
        Notification.user_id == world["ids"]["member"], Notification.type == "character_tagged"
    ).all()
    assert rows and json.loads(rows[0].payload)["post_id"] == pid
    assert "Wrong words" in rows[0].payload

    assert _delete_post(client, pid, world["author"]).status_code == 204

    db_session.expire_all()
    leftovers = db_session.query(Notification).filter(
        Notification.user_id == world["ids"]["member"]
    ).all()
    assert all("Wrong words" not in (n.payload or "") for n in leftovers)
    assert not any(json.loads(n.payload).get("post_id") == pid for n in leftovers)


def test_only_the_exact_post_mention_notifications_are_removed(client, db_session, world):
    pid = world["pub_post"]
    uid = world["ids"]["member"]
    # A post id that shares the deleted id's leading digits: "1" vs "12".
    similar = int(f"{pid}2")

    exact = _notify(db_session, uid, "mention", {"post_id": pid, "post_preview": "Bye."})
    exact_other_user = _notify(db_session, world["ids"]["owner"], "mention",
                               {"post_id": pid, "post_preview": "Bye."})
    lookalike = _notify(db_session, uid, "mention", {"post_id": similar, "post_preview": "Hi."})
    as_string = _notify(db_session, uid, "mention", {"post_id": str(pid)})
    as_bool = _notify(db_session, uid, "mention", {"post_id": True})
    tagged = _notify(db_session, uid, "character_tagged", {"post_id": pid, "post_preview": "Bye."})
    tagged_lookalike = _notify(db_session, uid, "character_tagged", {"post_id": similar})
    other_type = _notify(db_session, uid, "comment", {"post_id": pid})
    malformed = _notify(db_session, uid, "mention", f'{{"post_id":{pid}')
    empty = _notify(db_session, uid, "mention", None)

    assert _delete_post(client, pid, world["author"]).status_code == 204

    assert _surviving(db_session, [
        exact, exact_other_user, lookalike, as_string, as_bool, other_type, malformed, empty,
        tagged, tagged_lookalike,
    ]) == {lookalike, as_string, as_bool, other_type, malformed, empty, tagged_lookalike}


def test_a_refused_delete_removes_no_notifications(client, db_session, world):
    pid = world["pub_post"]
    nid = _notify(db_session, world["ids"]["member"], "mention", {"post_id": pid})

    assert _delete_post(client, pid, world["outsider"]).status_code == 403

    assert _surviving(db_session, [nid]) == {nid}
