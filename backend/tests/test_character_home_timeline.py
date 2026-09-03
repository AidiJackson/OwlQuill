"""Character Home Step 5 — the anonymous public timeline.

The second anonymous surface, and the one where a mistake is widest: a post
carries someone's writing, the realm it was written in, and an attachment whose
provenance the post itself knows nothing about.

Three things are pinned:

1. **Admission** — the timeline is reachable exactly when the profile is, on
   the same predicate and with the same 404.
2. **Realm privacy** — load-bearing. Publishing a Character Home must not
   publish the private realms that character posts in. The authenticated
   character timeline decides this by the VIEWER'S MEMBERSHIPS, which is
   meaningless for a visitor who has none; the anonymous one decides it by
   ``realms.is_public``, and these tests prove membership is not quietly
   standing in for visibility.
3. **Attachment provenance** — ``Post.image_url`` is a denormalised string. A
   public post does not make its image public, and an image that was
   attachable when the post was written may since have been archived or had its
   kind changed. Every failure mode suppresses the IMAGE and keeps the TEXT.
"""
import json
from datetime import datetime
from uuid import uuid4

import pytest

from app.models.character import Character, VisibilityEnum
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.post import ContentTypeEnum, Post
from app.models.realm import Realm, RealmMembership
from app.models.user import User
from app.models.user_image import UserImage
from tests.conftest import auth_headers, get_auth_token


#: Every field one anonymous timeline entry may contain.
PUBLIC_POST_FIELDS = {
    "id", "title", "content", "content_type", "post_kind", "provenance",
    "created_at", "image_url", "realm_id", "realm_name",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_character(client, token, name="Summer", visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _publish(db_session, character_id, enabled=True):
    row = db_session.query(Character).filter(Character.id == character_id).first()
    row.public_home_enabled = enabled
    db_session.commit()


def _user_id(db_session, email) -> int:
    return db_session.query(User).filter(User.email == email).first().id


def _realm(db_session, owner_id, name, *, is_public):
    """Create a realm with a collision-proof slug.

    Registration auto-joins The Commons and creates it if missing, so the
    fixture database already holds realms before a test writes one; the slug is
    UNIQUE, and a fixture that assumes an empty table errors rather than fails.
    """
    slug = f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}"
    realm = Realm(
        owner_id=owner_id,
        name=name,
        slug=slug,
        is_public=is_public,
    )
    db_session.add(realm)
    db_session.commit()
    db_session.refresh(realm)
    return realm


def _post(db_session, *, author_user_id, character_id, realm_id, content="A scene.",
          title=None, image_url=None, content_type=ContentTypeEnum.IC,
          created_at=None, post_kind="general"):
    post = Post(
        realm_id=realm_id,
        author_user_id=author_user_id,
        character_id=character_id,
        title=title,
        content=content,
        content_type=content_type,
        post_kind=post_kind,
        image_url=image_url,
        created_at=created_at or datetime(2026, 1, 1, 12, 0, 0),
    )
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)
    return post


def _char_image(db_session, character_id, user_id, *, file_path,
                kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
                provider="fal", metadata=None):
    img = CharacterImage(
        character_id=character_id,
        user_id=user_id,
        kind=kind,
        status=status,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider,
        prompt_summary="fixture",
        metadata_json=metadata if metadata is not None else {"library": True},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


def _user_image(db_session, user_id, *, file_path, provider="fal",
                status="active", metadata=None):
    img = UserImage(
        user_id=user_id,
        kind="profile_cover",
        status=status,
        provider=provider,
        metadata_json=metadata if metadata is not None else {},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


@pytest.fixture()
def home(client, db_session):
    """A published character with a public realm to post in."""
    token = get_auth_token(client, email="tl-own@test.com", username="tlown")
    cid = _create_character(client, token, "Summer")
    _publish(db_session, cid)
    uid = _user_id(db_session, "tl-own@test.com")
    return {
        "token": token,
        "character_id": cid,
        "owner_id": uid,
        "realm": _realm(db_session, uid, "Open Square", is_public=True),
    }


def _timeline(client, character_id, **params):
    return client.get(f"/characters/{character_id}/public-home/posts", params=params)


# ── A. Admission ──────────────────────────────────────────────────────────────

def test_nonexistent_character_is_404(client):
    assert _timeline(client, 999999).status_code == 404


def test_unpublished_public_character_is_404(client, db_session):
    token = get_auth_token(client, email="tl-off@test.com", username="tloff")
    cid = _create_character(client, token, "Summer")
    uid = _user_id(db_session, "tl-off@test.com")
    realm = _realm(db_session, uid, "Open Realm", is_public=True)
    _post(db_session, author_user_id=uid, character_id=cid, realm_id=realm.id)

    assert client.get(f"/characters/{cid}/public-home").status_code == 404
    assert _timeline(client, cid).status_code == 404


def test_private_character_with_the_flag_is_404(client, db_session):
    token = get_auth_token(client, email="tl-priv@test.com", username="tlpriv")
    cid = _create_character(client, token, "Hidden", visibility="private")
    _publish(db_session, cid)
    uid = _user_id(db_session, "tl-priv@test.com")
    realm = _realm(db_session, uid, "Open One", is_public=True)
    _post(db_session, author_user_id=uid, character_id=cid, realm_id=realm.id)

    assert _timeline(client, cid).status_code == 404


def test_friends_character_with_the_flag_is_404(client, db_session):
    token = get_auth_token(client, email="tl-fr@test.com", username="tlfr")
    cid = _create_character(client, token, "Circle", visibility="friends")
    _publish(db_session, cid)
    db_session.expire_all()
    assert db_session.query(Character).filter(
        Character.id == cid).first().visibility == VisibilityEnum.FRIENDS

    assert _timeline(client, cid).status_code == 404


def test_published_timeline_works_without_a_token(client, db_session, home):
    _post(db_session, author_user_id=home["owner_id"],
          character_id=home["character_id"], realm_id=home["realm"].id)

    resp = _timeline(client, home["character_id"])
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    assert "WWW-Authenticate" not in resp.headers


def test_revoking_the_grant_closes_the_timeline(client, db_session, home):
    cid = home["character_id"]
    _post(db_session, author_user_id=home["owner_id"], character_id=cid,
          realm_id=home["realm"].id)
    assert _timeline(client, cid).status_code == 200

    _publish(db_session, cid, enabled=False)
    assert _timeline(client, cid).status_code == 404


def test_timeline_and_profile_refuse_identically(client, db_session):
    """Same status and same body as a nonexistent id, on both surfaces."""
    token = get_auth_token(client, email="tl-ind@test.com", username="tlind")
    cid = _create_character(client, token, "Hidden", visibility="private")
    _publish(db_session, cid)

    hidden = _timeline(client, cid)
    missing = _timeline(client, 999999)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_timeline_is_mirrored_under_api(client, db_session, home):
    _post(db_session, author_user_id=home["owner_id"],
          character_id=home["character_id"], realm_id=home["realm"].id)

    resp = client.get(f"/api/characters/{home['character_id']}/public-home/posts")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


# ── B. Realm privacy — load-bearing ───────────────────────────────────────────

def test_only_public_realm_posts_cross_the_boundary(client, db_session, home):
    """The same published character posting in a public and a private realm."""
    cid, uid = home["character_id"], home["owner_id"]
    private_realm = _realm(db_session, uid, "Inner Circle", is_public=False)

    public_post = _post(db_session, author_user_id=uid, character_id=cid,
                        realm_id=home["realm"].id, content="Said in the open.")
    _post(db_session, author_user_id=uid, character_id=cid,
          realm_id=private_realm.id, content="Said behind a door.")

    body = _timeline(client, cid).json()
    assert [p["id"] for p in body] == [public_post.id]
    assert "behind a door" not in json.dumps(body)
    assert "Inner Circle" not in json.dumps(body)


def test_membership_is_not_a_substitute_for_realm_visibility(client, db_session, home):
    """Everyone who could see it is a member — and it still stays private.

    The authenticated endpoint answers this question with memberships. If that
    logic were reused here, the owner's own membership row would be enough to
    publish a private realm's posts to the open internet.
    """
    cid, uid = home["character_id"], home["owner_id"]
    private_realm = _realm(db_session, uid, "Members Only", is_public=False)
    db_session.add(RealmMembership(realm_id=private_realm.id, user_id=uid, role="owner"))
    db_session.commit()
    _post(db_session, author_user_id=uid, character_id=cid,
          realm_id=private_realm.id, content="Members only.")

    assert _timeline(client, cid).json() == []


def test_a_post_with_no_realm_is_excluded(client, db_session, home):
    """``realm_id`` is nullable; a post in no realm is in no PUBLIC realm."""
    cid, uid = home["character_id"], home["owner_id"]
    _post(db_session, author_user_id=uid, character_id=cid, realm_id=None,
          content="Adrift.")

    assert _timeline(client, cid).json() == []


def test_realm_turning_private_closes_its_posts_immediately(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    _post(db_session, author_user_id=uid, character_id=cid, realm_id=home["realm"].id)
    assert len(_timeline(client, cid).json()) == 1

    home["realm"].is_public = False
    db_session.commit()
    assert _timeline(client, cid).json() == []


# ── C. Which posts belong to this character ───────────────────────────────────

def test_another_characters_posts_do_not_appear(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    other_token = get_auth_token(client, email="tl-oth@test.com", username="tloth")
    other_cid = _create_character(client, other_token, "Autumn")
    other_uid = _user_id(db_session, "tl-oth@test.com")
    db_session.add(RealmMembership(realm_id=home["realm"].id, user_id=other_uid))
    db_session.commit()

    mine = _post(db_session, author_user_id=uid, character_id=cid,
                 realm_id=home["realm"].id, content="Mine.")
    _post(db_session, author_user_id=other_uid, character_id=other_cid,
          realm_id=home["realm"].id, content="Theirs.")

    body = _timeline(client, cid).json()
    assert [p["id"] for p in body] == [mine.id]


def test_characterless_account_posts_do_not_appear(client, db_session, home):
    """The DEV post-22 shape: an account post in a public realm, no character.

    Worth pinning on its own. The audit assumed post 22 would publish text-only
    through the image rule; in fact ``character_id`` is NULL, so it never
    reaches a character timeline at all.
    """
    cid, uid = home["character_id"], home["owner_id"]
    _post(db_session, author_user_id=uid, character_id=None,
          realm_id=home["realm"].id, content="Account speaking.")

    assert _timeline(client, cid).json() == []


def test_a_deleted_post_disappears(client, db_session, home):
    """The Post model has no soft-delete or hidden column — deletion is the row
    going away, so post-state eligibility is exactly 'still selectable'."""
    cid, uid = home["character_id"], home["owner_id"]
    post = _post(db_session, author_user_id=uid, character_id=cid,
                 realm_id=home["realm"].id)
    assert len(_timeline(client, cid).json()) == 1

    db_session.delete(post)
    db_session.commit()
    assert _timeline(client, cid).json() == []


@pytest.mark.parametrize(
    "content_type",
    [ContentTypeEnum.IC, ContentTypeEnum.OOC, ContentTypeEnum.NARRATION],
)
def test_every_content_type_publishes_and_is_labelled(client, db_session, home, content_type):
    """No OOC visibility policy is invented here.

    Nothing in the product treats an OOC post as private: it is created,
    stored, listed and read by exactly the same paths as an IC post, and the
    authenticated character timeline returns it. Inventing a rule from the
    label alone would be a product decision taken by accident. The type IS
    carried so a client can render it differently.
    """
    cid, uid = home["character_id"], home["owner_id"]
    _post(db_session, author_user_id=uid, character_id=cid,
          realm_id=home["realm"].id, content_type=content_type)

    body = _timeline(client, cid).json()
    assert len(body) == 1
    assert body[0]["content_type"] == content_type.value


# ── D. The public projection ──────────────────────────────────────────────────

def test_entry_contains_exactly_the_allowlisted_fields(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    _post(db_session, author_user_id=uid, character_id=cid,
          realm_id=home["realm"].id, title="A Title")

    body = _timeline(client, cid).json()
    assert set(body[0].keys()) == PUBLIC_POST_FIELDS


def test_account_and_internal_fields_are_absent(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    # Content deliberately free of the account username, so the string check
    # below is testing the serializer rather than the fixture's own text.
    _post(db_session, author_user_id=uid, character_id=cid,
          realm_id=home["realm"].id, content="Hello there.")

    body = _timeline(client, cid).json()
    for field in (
        "author_user_id", "author_username", "author", "email",
        "character_id", "character_name", "character_avatar_url",
        "mentions", "comment_count", "reactions",
        "provenance_evidence", "provenance_rule_version", "provenance_decided_at",
        "source_type", "updated_at",
    ):
        assert field not in body[0], f"{field} leaked to the anonymous timeline"
    assert "tl-own@test.com" not in json.dumps(body)
    assert "tlown" not in json.dumps(body)


def test_useful_fields_survive(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    post = _post(db_session, author_user_id=uid, character_id=cid,
                 realm_id=home["realm"].id, title="Nightfall",
                 content="The lamps went out one by one.", post_kind="open_starter")

    entry = _timeline(client, cid).json()[0]
    assert entry["id"] == post.id
    assert entry["title"] == "Nightfall"
    assert entry["content"] == "The lamps went out one by one."
    assert entry["post_kind"] == "open_starter"
    assert entry["provenance"] == "unknown"
    assert entry["realm_id"] == home["realm"].id
    assert entry["realm_name"] == "Open Square"
    assert entry["created_at"].startswith("2026-01-01")


# ── E. Ordering and limit ─────────────────────────────────────────────────────

def test_newest_first_ordering(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    old = _post(db_session, author_user_id=uid, character_id=cid,
                realm_id=home["realm"].id, content="First",
                created_at=datetime(2026, 1, 1))
    mid = _post(db_session, author_user_id=uid, character_id=cid,
                realm_id=home["realm"].id, content="Second",
                created_at=datetime(2026, 2, 1))
    new = _post(db_session, author_user_id=uid, character_id=cid,
                realm_id=home["realm"].id, content="Third",
                created_at=datetime(2026, 3, 1))

    assert [p["id"] for p in _timeline(client, cid).json()] == [new.id, mid.id, old.id]


def test_identical_timestamps_order_stably_by_id(client, db_session, home):
    """Seeded rows share a timestamp; without a tie-break the page shuffles."""
    cid, uid = home["character_id"], home["owner_id"]
    stamp = datetime(2026, 5, 5, 9, 0, 0)
    ids = [
        _post(db_session, author_user_id=uid, character_id=cid,
              realm_id=home["realm"].id, content=f"n{i}", created_at=stamp).id
        for i in range(3)
    ]

    returned = [p["id"] for p in _timeline(client, cid).json()]
    assert returned == sorted(ids, reverse=True)
    assert returned == [p["id"] for p in _timeline(client, cid).json()]


def test_limit_defaults_to_twenty_and_is_bounded(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    for i in range(25):
        _post(db_session, author_user_id=uid, character_id=cid,
              realm_id=home["realm"].id, content=f"n{i}",
              created_at=datetime(2026, 1, 1, 0, i))

    assert len(_timeline(client, cid).json()) == 20
    assert len(_timeline(client, cid, limit=5).json()) == 5
    assert _timeline(client, cid, limit=0).status_code == 422
    assert _timeline(client, cid, limit=101).status_code == 422


# ── F. Attachment provenance ──────────────────────────────────────────────────

def _post_with_image(db_session, home, url, content="Look at this."):
    return _post(db_session, author_user_id=home["owner_id"],
                 character_id=home["character_id"], realm_id=home["realm"].id,
                 content=content, image_url=url)


def test_safe_character_image_attachment_survives(client, db_session, home):
    _char_image(db_session, home["character_id"], home["owner_id"],
                file_path="static/generated/post-safe.png")
    _post_with_image(db_session, home, "/static/generated/post-safe.png")

    assert _timeline(client, home["character_id"]).json()[0]["image_url"] == \
        "/static/generated/post-safe.png"


def test_absolute_r2_url_resolves(client, db_session, home):
    """DEV stores post attachments as absolute R2 URLs, matched verbatim."""
    url = "https://pub-abc.r2.dev/generated/deadbeef.png"
    _char_image(db_session, home["character_id"], home["owner_id"], file_path=url)
    _post_with_image(db_session, home, url)

    assert _timeline(client, home["character_id"]).json()[0]["image_url"] == url


@pytest.mark.parametrize(
    "provider,metadata",
    [
        ("fal", {"adult_studio": True}),
        ("gpt-image", {"editor_generated": True, "provider": "gpt-image"}),
        ("replicate_nsfw", {}),
        ("self_hosted", {}),
        ("fal", {"provider": "replicate_nsfw"}),
    ],
)
def test_unsafe_attachment_is_suppressed_and_text_remains(
    client, db_session, home, provider, metadata
):
    """Every exclusion layer, and none of them removes the post."""
    _char_image(db_session, home["character_id"], home["owner_id"],
                file_path="static/generated/post-unsafe.png",
                provider=provider, metadata=metadata)
    _post_with_image(db_session, home, "/static/generated/post-unsafe.png",
                     content="The text must survive.")

    entry = _timeline(client, home["character_id"]).json()[0]
    assert entry["image_url"] is None
    assert entry["content"] == "The text must survive."


def test_unresolvable_attachment_is_suppressed_and_text_remains(client, db_session, home):
    """The DEV post-22 image shape, reproduced rather than borrowed.

    Stricter than the avatar/cover rule on purpose: nothing derives a post
    attachment, so a url matching no row is a url whose provenance cannot be
    established.
    """
    _post_with_image(db_session, home,
                     "https://pub-abc.r2.dev/generated/5fc1376186864018b42d1cc6611c15a6.png",
                     content="Post 22 shape.")

    entry = _timeline(client, home["character_id"]).json()[0]
    assert entry["image_url"] is None
    assert entry["content"] == "Post 22 shape."


def test_archived_image_row_is_suppressed(client, db_session, home):
    """Archiving IS the owner's delete, and the post's url keeps pointing at it."""
    img = _char_image(db_session, home["character_id"], home["owner_id"],
                      file_path="static/generated/post-archived.png")
    _post_with_image(db_session, home, "/static/generated/post-archived.png")
    assert _timeline(client, home["character_id"]).json()[0]["image_url"] is not None

    img.status = ImageStatusEnum.ARCHIVED
    db_session.commit()

    entry = _timeline(client, home["character_id"]).json()[0]
    assert entry["image_url"] is None
    assert entry["content"] == "Look at this."


def test_image_whose_kind_left_the_attachable_allowlist_is_suppressed(client, db_session, home):
    """``kind`` is mutable — the identity-pack accept path rewrites it."""
    img = _char_image(db_session, home["character_id"], home["owner_id"],
                      file_path="static/generated/post-kind.png")
    _post_with_image(db_session, home, "/static/generated/post-kind.png")
    assert _timeline(client, home["character_id"]).json()[0]["image_url"] is not None

    img.kind = ImageKindEnum.ANCHOR_FRONT
    db_session.commit()

    assert _timeline(client, home["character_id"]).json()[0]["image_url"] is None


def test_safe_user_image_attachment_survives(client, db_session, home):
    """Account images can back a post — the attachment route accepts them."""
    _user_image(db_session, home["owner_id"], file_path="static/generated/post-ui.png")
    _post_with_image(db_session, home, "/static/generated/post-ui.png")

    assert _timeline(client, home["character_id"]).json()[0]["image_url"] == \
        "/static/generated/post-ui.png"


def test_unsafe_user_image_attachment_is_suppressed(client, db_session, home):
    _user_image(db_session, home["owner_id"],
                file_path="static/generated/post-ui-bad.png",
                provider="replicate_nsfw", metadata={"adult_studio": True})
    _post_with_image(db_session, home, "/static/generated/post-ui-bad.png",
                     content="Text survives here too.")

    entry = _timeline(client, home["character_id"]).json()[0]
    assert entry["image_url"] is None
    assert entry["content"] == "Text survives here too."


def test_ambiguous_resolution_fails_closed(client, db_session, home):
    """One url, two rows, one of them unsafe — the image is withheld.

    A file_path can be shared: promoting or copying media between records
    produces exactly this. The safe match must not vouch for the unsafe one.
    """
    shared = "static/generated/post-shared.png"
    _char_image(db_session, home["character_id"], home["owner_id"], file_path=shared)
    _char_image(db_session, home["character_id"], home["owner_id"], file_path=shared,
                provider="replicate_nsfw", metadata={"adult_studio": True})
    _post_with_image(db_session, home, "/static/generated/post-shared.png")

    assert _timeline(client, home["character_id"]).json()[0]["image_url"] is None


def test_text_only_post_is_normal(client, db_session, home):
    _post(db_session, author_user_id=home["owner_id"],
          character_id=home["character_id"], realm_id=home["realm"].id,
          content="Just words.")

    entry = _timeline(client, home["character_id"]).json()[0]
    assert entry["image_url"] is None
    assert entry["content"] == "Just words."


# ── G. Authenticated behaviour is unchanged ───────────────────────────────────

def test_authenticated_character_posts_endpoint_is_unchanged(client, db_session, home):
    """``GET /characters/{id}/posts`` keeps its auth requirement, its
    membership rule and its wrapper shape — including the part the anonymous
    timeline deliberately does NOT copy: a member sees a PRIVATE realm's posts.
    """
    cid, uid = home["character_id"], home["owner_id"]
    private_realm = _realm(db_session, uid, "Back Room", is_public=False)
    db_session.add(RealmMembership(realm_id=private_realm.id, user_id=uid, role="owner"))
    db_session.add(RealmMembership(realm_id=home["realm"].id, user_id=uid))
    db_session.commit()
    _post(db_session, author_user_id=uid, character_id=cid,
          realm_id=home["realm"].id, content="Open.")
    _post(db_session, author_user_id=uid, character_id=cid,
          realm_id=private_realm.id, content="Closed.")

    # Still requires a token.
    assert client.get(f"/characters/{cid}/posts").status_code in (401, 403)

    # The member still sees both, in the wrapper shape it has always returned.
    body = client.get(f"/characters/{cid}/posts", headers=auth_headers(home["token"])).json()
    assert {e["payload"]["content"] for e in body} == {"Open.", "Closed."}
    assert set(body[0].keys()) == {"type", "created_at", "realm_id", "realm_name", "payload"}

    # And the anonymous surface publishes only the public-realm half.
    assert [p["content"] for p in _timeline(client, cid).json()] == ["Open."]


def test_authenticated_endpoint_is_not_gated_by_the_publication_flag(client, db_session):
    """Publishing a Home is not a precondition for internal browsing."""
    token = get_auth_token(client, email="tl-int@test.com", username="tlint")
    cid = _create_character(client, token, "Summer")
    uid = _user_id(db_session, "tl-int@test.com")
    realm = _realm(db_session, uid, "Shared Ground", is_public=True)
    db_session.add(RealmMembership(realm_id=realm.id, user_id=uid))
    db_session.commit()
    _post(db_session, author_user_id=uid, character_id=cid, realm_id=realm.id)

    assert client.get(
        f"/characters/{cid}/posts", headers=auth_headers(token)
    ).status_code == 200
    assert _timeline(client, cid).status_code == 404
