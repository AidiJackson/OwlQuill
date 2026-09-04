"""Character Home Step 6.6 — the dedicated public gallery projection.

``GET /characters/{id}/public-home/images`` is now THE Character Home gallery,
and the property that makes it a *projection* rather than a view is that its
output does not depend on who is asking. Four callers — logged out, a signed-in
stranger, the creator, an admin — must receive byte-identical bodies. A creator
who cannot see exactly what a visitor sees has no way to answer "what have I
actually published?", and a route that widens for a token is precisely how an
unselected working image reaches a public page.

That equality is section C and it is the point of this file. Everything else
supports it:

* the three admission layers, all required and none substitutable;
* creator selection never overriding safety — a selected image that is unsafe,
  archived, temp or of a non-gallery kind stays absent;
* the response carrying no owner or internal field;
* the creator's own full working library still reachable, unchanged, through the
  authenticated routes;
* the neighbouring public surfaces — avatar, cover, post attachments — behaving
  exactly as they did before this endpoint existed.

Step 6.6 also retired the anonymous branch of ``GET /characters/{id}/images``.
That decision is pinned in section F: it is now authenticated-only, so there is
one public gallery rule rather than two that can drift.
"""
import pytest

from app.models.character import Character, VisibilityEnum
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.post import ContentTypeEnum, Post
from app.models.realm import Realm
from app.models.user import User
from tests.conftest import auth_headers, get_auth_token
from uuid import uuid4


#: The complete public gallery contract, asserted as an exact key set so a field
#: added to CharacterImagePublic cannot reach visitors unnoticed.
PUBLIC_IMAGE_FIELDS = {"id", "character_id", "kind", "created_at", "url"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_character(client, token, name="Summer", visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _row(db_session, character_id) -> Character:
    db_session.expire_all()
    return db_session.query(Character).filter(Character.id == character_id).first()


def _publish(db_session, character_id, enabled=True):
    row = db_session.query(Character).filter(Character.id == character_id).first()
    row.public_home_enabled = enabled
    db_session.commit()


def _user_id(db_session, email) -> int:
    return db_session.query(User).filter(User.email == email).first().id


def _make_admin(db_session, email):
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None, f"no such fixture user: {email}"
    user.is_admin = True
    db_session.commit()
    return user


def _insert_image(db_session, character_id, user_id, *, file_path,
                  kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
                  provider="fal", metadata=None, selected=False):
    img = CharacterImage(
        character_id=character_id,
        user_id=user_id,
        kind=kind,
        status=status,
        visibility=ImageVisibilityEnum.PRIVATE,
        public_gallery_enabled=selected,
        provider=provider,
        prompt_summary="fixture prompt",
        seed="12345",
        metadata_json=metadata if metadata is not None else {"library": True},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img.id


def _gallery(client, character_id, token=None, prefix=""):
    headers = auth_headers(token) if token else {}
    return client.get(f"{prefix}/characters/{character_id}/public-home/images",
                      headers=headers)


def _ids(resp):
    return [item["id"] for item in resp.json()]


@pytest.fixture()
def home(client, db_session):
    """A published Character Home with one selected, safe image."""
    token = get_auth_token(client, email="proj-own@test.com", username="projown")
    cid = _create_character(client, token, "Summer")
    _publish(db_session, cid)
    uid = _user_id(db_session, "proj-own@test.com")
    shown = _insert_image(db_session, cid, uid, file_path="static/generated/p1.png",
                          selected=True)
    return {"token": token, "character_id": cid, "owner_id": uid, "shown": shown}


# ── A. Admission: the Home must be published ─────────────────────────────────

def test_nonexistent_character_is_404(client):
    assert client.get("/characters/999999/public-home/images").status_code == 404


def test_unpublished_home_is_404_even_with_selected_images(client, db_session):
    """Selecting images does not open a Home that was never published."""
    token = get_auth_token(client, email="proj-off@test.com", username="projoff")
    cid = _create_character(client, token, "Summer")
    uid = _user_id(db_session, "proj-off@test.com")
    _insert_image(db_session, cid, uid, file_path="static/generated/a1.png", selected=True)
    assert _row(db_session, cid).public_home_enabled is False

    assert _gallery(client, cid).status_code == 404


def test_unpublished_and_nonexistent_are_indistinguishable(client, db_session):
    """Same status AND same body, so walking the id space reveals nothing."""
    token = get_auth_token(client, email="proj-ind@test.com", username="projind")
    cid = _create_character(client, token, "Hidden", visibility="private")
    _publish(db_session, cid)
    uid = _user_id(db_session, "proj-ind@test.com")
    _insert_image(db_session, cid, uid, file_path="static/generated/a2.png", selected=True)

    hidden = _gallery(client, cid)
    missing = client.get("/characters/999999/public-home/images")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


@pytest.mark.parametrize("visibility", [VisibilityEnum.PRIVATE, VisibilityEnum.FRIENDS])
def test_non_public_visibility_is_404_even_when_granted(client, db_session, visibility):
    """The grant is permission, never an override of the creator's privacy."""
    token = get_auth_token(client, email="proj-vis@test.com", username="projvis")
    cid = _create_character(client, token, "Hidden")
    _publish(db_session, cid)
    row = _row(db_session, cid)
    row.visibility = visibility
    db_session.commit()

    assert _gallery(client, cid).status_code == 404


def test_revoking_publication_closes_the_gallery_again(client, db_session, home):
    cid = home["character_id"]
    assert _gallery(client, cid).status_code == 200

    _publish(db_session, cid, enabled=False)
    assert _gallery(client, cid).status_code == 404


def test_gallery_needs_no_token(client, home):
    resp = _gallery(client, home["character_id"])
    assert resp.status_code == 200, resp.text
    assert "WWW-Authenticate" not in resp.headers


# ── B. Selection and safety, composed but never merged ───────────────────────

def test_selected_and_safe_image_appears(client, home):
    resp = _gallery(client, home["character_id"])
    assert resp.status_code == 200, resp.text
    assert _ids(resp) == [home["shown"]]


def test_unselected_safe_image_is_absent(client, db_session, home):
    """Publication does not publish the whole library."""
    cid, uid = home["character_id"], home["owner_id"]
    unselected = _insert_image(db_session, cid, uid, file_path="static/generated/b1.png")

    assert unselected not in _ids(_gallery(client, cid))
    assert _ids(_gallery(client, cid)) == [home["shown"]]


@pytest.mark.parametrize("label,kwargs", [
    ("adult studio provider", {"provider": "replicate_nsfw",
                               "metadata": {"adult_studio": True}}),
    ("editor studio metadata", {"kind": ImageKindEnum.SCENE_ONLY, "provider": "gpt-image",
                                "metadata": {"editor_generated": True}}),
    ("self-hosted pod", {"kind": ImageKindEnum.SCENE_ONLY, "provider": "self_hosted",
                         "metadata": {}}),
    ("non-gallery kind: anchor", {"kind": ImageKindEnum.ANCHOR_FRONT}),
    ("non-gallery kind: sketch", {"kind": ImageKindEnum.IDENTITY_SKETCH}),
    ("non-gallery kind: upload", {"kind": ImageKindEnum.UPLOADED}),
    ("unaccepted temp preview", {"metadata": {"is_temp": True}}),
    ("archived", {"status": ImageStatusEnum.ARCHIVED}),
])
def test_selection_never_overrides_safety(client, db_session, home, label, kwargs):
    """Every one of these is SELECTED and still withheld.

    The headline invariant: creator selection can subtract from what Ficshon
    allows, never add to it.
    """
    cid, uid = home["character_id"], home["owner_id"]
    blocked = _insert_image(db_session, cid, uid, file_path=f"static/generated/{uuid4().hex}.png",
                            selected=True, **kwargs)

    returned = _ids(_gallery(client, cid))
    assert blocked not in returned, f"{label} reached the public gallery"
    assert returned == [home["shown"]], "the clean image must still show"


def test_deselection_removes_the_image_immediately(client, db_session, home):
    """Withdrawal takes effect on the next read — no cache, no delay."""
    cid, token, shown = home["character_id"], home["token"], home["shown"]
    assert _ids(_gallery(client, cid)) == [shown]

    resp = client.post(
        f"/characters/{cid}/images/{shown}/public-gallery",
        json={"enabled": False}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert _gallery(client, cid).json() == []


def test_reselection_restores_the_image(client, db_session, home):
    cid, token, shown = home["character_id"], home["token"], home["shown"]
    client.post(f"/characters/{cid}/images/{shown}/public-gallery",
                json={"enabled": False}, headers=auth_headers(token))
    assert _gallery(client, cid).json() == []

    client.post(f"/characters/{cid}/images/{shown}/public-gallery",
                json={"enabled": True}, headers=auth_headers(token))
    assert _ids(_gallery(client, cid)) == [shown]


def test_images_of_another_character_never_appear(client, db_session, home):
    other_token = get_auth_token(client, email="proj-oth@test.com", username="projoth")
    other_cid = _create_character(client, other_token, "Autumn")
    other_uid = _user_id(db_session, "proj-oth@test.com")
    _publish(db_session, other_cid)
    foreign = _insert_image(db_session, other_cid, other_uid,
                            file_path="static/generated/b2.png", selected=True)

    assert foreign not in _ids(_gallery(client, home["character_id"]))


def test_gallery_is_newest_first(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    second = _insert_image(db_session, cid, uid, file_path="static/generated/b3.png",
                           selected=True)
    third = _insert_image(db_session, cid, uid, file_path="static/generated/b4.png",
                          selected=True)

    assert _ids(_gallery(client, cid)) == [third, second, home["shown"]]


def test_limit_is_bounded_and_honoured(client, db_session, home):
    cid, uid = home["character_id"], home["owner_id"]
    for n in range(3):
        _insert_image(db_session, cid, uid, file_path=f"static/generated/b5{n}.png",
                      selected=True)

    assert len(_gallery(client, cid).json()) == 4
    resp = client.get(f"/characters/{cid}/public-home/images?limit=2")
    assert len(resp.json()) == 2
    # An unauthenticated endpoint must not accept an unbounded page.
    assert client.get(f"/characters/{cid}/public-home/images?limit=0").status_code == 422
    assert client.get(f"/characters/{cid}/public-home/images?limit=9999").status_code == 422


# ── C. The projection does not depend on who is asking ───────────────────────
#
# The section this file exists for.

@pytest.fixture()
def mixed_home(client, db_session, home):
    """A published Home holding a selected-safe image plus everything that must
    stay private: unselected, unsafe-but-selected, wrong-kind and archived."""
    cid, uid = home["character_id"], home["owner_id"]
    private = {
        "unselected": _insert_image(db_session, cid, uid,
                                    file_path="static/generated/c1.png"),
        "adult": _insert_image(db_session, cid, uid, file_path="static/generated/c2.png",
                               provider="replicate_nsfw",
                               metadata={"adult_studio": True}, selected=True),
        "anchor": _insert_image(db_session, cid, uid, file_path="static/generated/c3.png",
                                kind=ImageKindEnum.ANCHOR_FRONT, selected=True),
        "archived": _insert_image(db_session, cid, uid, file_path="static/generated/c4.png",
                                  status=ImageStatusEnum.ARCHIVED, selected=True),
    }
    return {**home, "private": private}


def test_anonymous_and_signed_in_stranger_see_the_same_gallery(client, db_session, mixed_home):
    cid = mixed_home["character_id"]
    stranger = get_auth_token(client, email="proj-str@test.com", username="projstr")

    anonymous = _gallery(client, cid)
    signed_in = _gallery(client, cid, token=stranger)
    assert anonymous.status_code == signed_in.status_code == 200
    assert anonymous.json() == signed_in.json()


def test_anonymous_and_owner_see_the_same_gallery(client, mixed_home):
    """The creator's own token must not widen their own Home.

    Without this the creator sees a Home no visitor can see, and has no way to
    check what they actually published.
    """
    cid = mixed_home["character_id"]

    anonymous = _gallery(client, cid)
    owner = _gallery(client, cid, token=mixed_home["token"])
    assert anonymous.json() == owner.json()
    assert _ids(owner) == [mixed_home["shown"]]


def test_anonymous_and_admin_see_the_same_gallery(client, db_session, mixed_home):
    """Admin rights are not a public-surface exemption either."""
    cid = mixed_home["character_id"]
    admin_token = get_auth_token(client, email="proj-adm@test.com", username="projadm")
    _make_admin(db_session, "proj-adm@test.com")

    anonymous = _gallery(client, cid)
    admin = _gallery(client, cid, token=admin_token)
    assert anonymous.json() == admin.json()


def test_all_four_viewers_receive_identical_bodies(client, db_session, mixed_home):
    """Stated once as a single equality, because that is the actual contract."""
    cid = mixed_home["character_id"]
    stranger = get_auth_token(client, email="proj-str2@test.com", username="projstr2")
    admin_token = get_auth_token(client, email="proj-adm2@test.com", username="projadm2")
    _make_admin(db_session, "proj-adm2@test.com")

    bodies = [
        _gallery(client, cid).json(),
        _gallery(client, cid, token=stranger).json(),
        _gallery(client, cid, token=mixed_home["token"]).json(),
        _gallery(client, cid, token=admin_token).json(),
    ]
    assert all(body == bodies[0] for body in bodies)
    assert [item["id"] for item in bodies[0]] == [mixed_home["shown"]]

    # And none of the private material reached any of them.
    for body in bodies:
        returned = {item["id"] for item in body}
        for label, image_id in mixed_home["private"].items():
            assert image_id not in returned, f"{label} leaked"


def test_an_invalid_token_does_not_break_the_public_gallery(client, mixed_home):
    """The route takes no auth dependency, so a bad token is simply ignored."""
    resp = client.get(
        f"/characters/{mixed_home['character_id']}/public-home/images",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 200, resp.text
    assert _ids(resp) == [mixed_home["shown"]]


# ── D. The public schema stays narrow ────────────────────────────────────────

def test_response_contains_exactly_the_public_fields(client, home):
    body = _gallery(client, home["character_id"]).json()
    assert len(body) == 1
    assert set(body[0].keys()) == PUBLIC_IMAGE_FIELDS


def test_owner_and_internal_fields_are_absent(client, home):
    """Asserted by name as well as by the key set, so a failure names the leak."""
    item = _gallery(client, home["character_id"]).json()[0]
    for field in (
        "public_gallery_enabled", "visibility", "status", "provider",
        "prompt_summary", "seed", "metadata_json", "user_id", "owner_id",
        "file_path", "is_temp", "job_id", "generation_job",
    ):
        assert field not in item, f"{field} leaked to the public gallery"


def test_no_secret_values_appear_anywhere_in_the_payload(client, db_session, home):
    """The fixture writes a distinctive prompt, seed and provider — none of
    which may appear in the serialized body under any key."""
    import json

    payload = json.dumps(_gallery(client, home["character_id"]).json())
    for secret in ("fixture prompt", "12345", "fal", "proj-own@test.com", "library"):
        assert secret not in payload, f"{secret!r} leaked into the public payload"


def test_url_is_served_and_kind_is_carried(client, home):
    item = _gallery(client, home["character_id"]).json()[0]
    assert item["url"] == "/static/generated/p1.png"
    assert item["kind"] == "generated"
    assert item["character_id"] == home["character_id"]


# ── E. The /api mirror ───────────────────────────────────────────────────────

def test_api_mirror_is_identical(client, mixed_home):
    cid = mixed_home["character_id"]
    bare = _gallery(client, cid)
    mirrored = _gallery(client, cid, prefix="/api")
    assert bare.status_code == mirrored.status_code == 200
    assert bare.json() == mirrored.json()


def test_api_mirror_404s_for_an_unpublished_home(client, db_session):
    token = get_auth_token(client, email="proj-mir@test.com", username="projmir")
    cid = _create_character(client, token, "Summer")
    assert _gallery(client, cid, prefix="/api").status_code == 404


# ── F. The old route is now authenticated-only ───────────────────────────────
#
# Step 6.6's compatibility decision, pinned. Nothing consumed the anonymous
# branch — the sole client caller sits behind ProtectedRoute — so it was removed
# rather than kept as a delegating alias, leaving one public gallery rule.

def test_old_images_route_no_longer_answers_anonymously(client, home):
    """It was a second public gallery. It is now internal."""
    resp = client.get(f"/characters/{home['character_id']}/images")
    assert resp.status_code in (401, 403), resp.text


def test_old_images_route_is_authenticated_even_for_a_published_home(client, home):
    """Publication does not re-open it: the Home's gallery lives elsewhere."""
    assert _gallery(client, home["character_id"]).status_code == 200
    assert client.get(f"/characters/{home['character_id']}/images").status_code in (401, 403)


def test_owner_keeps_the_full_working_set_on_the_old_route(client, db_session, home):
    """The creator's library is unchanged — selection does not filter it."""
    cid, uid, token = home["character_id"], home["owner_id"], home["token"]
    unselected = _insert_image(db_session, cid, uid, file_path="static/generated/f1.png")
    anchor = _insert_image(db_session, cid, uid, file_path="static/generated/f2.png",
                           kind=ImageKindEnum.ANCHOR_FRONT)

    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()} == {home["shown"], unselected, anchor}
    # And with the metadata an owner is entitled to.
    by_id = {i["id"]: i for i in resp.json()}
    assert by_id[home["shown"]]["public_gallery_enabled"] is True
    assert by_id[unselected]["public_gallery_enabled"] is False


def test_signed_in_stranger_still_sees_the_kind_filtered_library(client, db_session, home):
    """In-product behaviour is unchanged: NOT narrowed by creator selection."""
    cid, uid = home["character_id"], home["owner_id"]
    unselected = _insert_image(db_session, cid, uid, file_path="static/generated/f3.png")
    _insert_image(db_session, cid, uid, file_path="static/generated/f4.png",
                  kind=ImageKindEnum.ANCHOR_FRONT)

    stranger = get_auth_token(client, email="proj-str3@test.com", username="projstr3")
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(stranger))
    assert resp.status_code == 200, resp.text
    # Both gallery-kind images, selected or not; the anchor stays private.
    assert {i["id"] for i in resp.json()} == {home["shown"], unselected}


def test_private_character_library_still_403s_for_a_stranger(client, db_session):
    owner = get_auth_token(client, email="proj-pv@test.com", username="projpv")
    cid = _create_character(client, owner, "Hidden", visibility="private")
    _publish(db_session, cid)

    stranger = get_auth_token(client, email="proj-pv2@test.com", username="projpv2")
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(stranger))
    assert resp.status_code == 403, resp.text


# ── G. Neighbouring public surfaces are untouched ────────────────────────────

def test_avatar_and_cover_do_not_answer_to_gallery_selection(client, db_session, home):
    """A Home's portrait is not a gallery piece and is not curated as one."""
    cid, uid = home["character_id"], home["owner_id"]
    _insert_image(db_session, cid, uid, file_path="static/generated/g1.png")
    _insert_image(db_session, cid, uid, file_path="static/generated/g2.png")
    row = _row(db_session, cid)
    row.avatar_url = "/static/generated/g1.png"
    row.cover_url = "/static/generated/g2.png"
    db_session.commit()

    body = client.get(f"/characters/{cid}/public-home").json()
    # Neither image is selected, and both still resolve.
    assert body["avatar_url"] == "/static/generated/g1.png"
    assert body["cover_url"] == "/static/generated/g2.png"
    # ...and neither appears in the curated gallery.
    assert _ids(_gallery(client, cid)) == [home["shown"]]


def test_unsafe_avatar_is_still_suppressed(client, db_session, home):
    """The Step 1.5 media rule is unaffected by the new endpoint."""
    cid, uid = home["character_id"], home["owner_id"]
    _insert_image(db_session, cid, uid, file_path="static/generated/g3.png",
                  provider="replicate_nsfw", metadata={"adult_studio": True})
    row = _row(db_session, cid)
    row.avatar_url = "/static/generated/g3.png"
    db_session.commit()

    assert client.get(f"/characters/{cid}/public-home").json()["avatar_url"] is None


def test_post_attachments_do_not_answer_to_gallery_selection(client, db_session, home):
    """A published post keeps its image whether or not it is a gallery piece."""
    cid, uid = home["character_id"], home["owner_id"]
    _insert_image(db_session, cid, uid, file_path="static/generated/g4.png")

    realm = Realm(owner_id=uid, name="Projection Realm",
                  slug=f"projection-{uuid4().hex[:8]}", is_public=True)
    db_session.add(realm)
    db_session.commit()
    db_session.refresh(realm)
    db_session.add(Post(
        realm_id=realm.id, author_user_id=uid, character_id=cid,
        content="A post with an image.", content_type=ContentTypeEnum.IC,
        post_kind="general", image_url="/static/generated/g4.png",
    ))
    db_session.commit()

    timeline = client.get(f"/characters/{cid}/public-home/posts")
    assert timeline.status_code == 200, timeline.text
    assert [p["image_url"] for p in timeline.json()] == ["/static/generated/g4.png"]
    # The same image is still absent from the curated gallery.
    assert _ids(_gallery(client, cid)) == [home["shown"]]


def test_selection_endpoint_behaviour_is_unchanged(client, db_session, home):
    """Owner-only, writes only the flag, still refuses an ineligible image."""
    cid, uid, token = home["character_id"], home["owner_id"], home["token"]
    anchor = _insert_image(db_session, cid, uid, file_path="static/generated/g5.png",
                           kind=ImageKindEnum.ANCHOR_FRONT)

    refused = client.post(f"/characters/{cid}/images/{anchor}/public-gallery",
                          json={"enabled": True}, headers=auth_headers(token))
    assert refused.status_code == 422, refused.text

    stranger = get_auth_token(client, email="proj-sel@test.com", username="projsel")
    forbidden = client.post(f"/characters/{cid}/images/{home['shown']}/public-gallery",
                            json={"enabled": False}, headers=auth_headers(stranger))
    assert forbidden.status_code == 403, forbidden.text
