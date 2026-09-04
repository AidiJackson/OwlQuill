"""Character Home Step 6.5 — creator selection for the public gallery.

Publishing a Character Home never published a creator's whole gallery. Which
images appear there is now an explicit per-image choice, and reaching an
anonymous viewer takes THREE independent layers, all required:

1. the Character Home is published — ``character_home_is_publishable``;
2. the creator selected this image — ``public_gallery_enabled``;
3. Ficshon is willing to expose it — ``is_public_gallery_image``.

What these tests pin, in order of what would hurt most if it broke:

* **Selection never overrides safety.** A selected image that is Adult Studio
  output, Editor Studio output, an anchor, archived or a temp preview stays
  withheld. Layer 2 can only ever subtract from layer 3, never add to it.
* **Nothing is published by default.** Existing rows and newly created rows are
  both ``false``, so shipping the column publishes no image anywhere.
* **The owner's own Media is untouched.** A creator sees their whole library
  whatever they have selected, and toggling changes nothing else about the row.
* **``visibility`` is untouched.** The existing enum column keeps its values and
  its meaning; selection is a separate column answering a separate question.
* **Avatar, cover and post attachments are unaffected.** They are different
  surfaces with their own rules, and the gallery flag says nothing about them.
"""
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
from app.models.realm import Realm
from app.models.user import User
from app.schemas.character_image import (
    is_public_gallery_image,
    is_public_gallery_visible,
    is_selected_for_public_gallery,
)
from tests.conftest import auth_headers, get_auth_token


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
        prompt_summary="fixture",
        metadata_json=metadata if metadata is not None else {"library": True},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img.id


def _image(db_session, image_id) -> CharacterImage:
    db_session.expire_all()
    return db_session.query(CharacterImage).filter(CharacterImage.id == image_id).first()


def _make_admin(db_session, email):
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None, f"no such fixture user: {email}"
    user.is_admin = True
    db_session.commit()
    return user


def _select(client, token, character_id, image_id, enabled=True):
    return client.post(
        f"/characters/{character_id}/images/{image_id}/public-gallery",
        json={"enabled": enabled},
        headers=auth_headers(token),
    )


def _realm(db_session, owner_id, name, *, is_public=True):
    """Create a realm with a collision-proof slug, as the timeline tests do."""
    realm = Realm(
        owner_id=owner_id,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        is_public=is_public,
    )
    db_session.add(realm)
    db_session.commit()
    db_session.refresh(realm)
    return realm


def _post(db_session, *, author_user_id, character_id, realm_id, image_url=None):
    post = Post(
        realm_id=realm_id,
        author_user_id=author_user_id,
        character_id=character_id,
        content="A post with an image.",
        content_type=ContentTypeEnum.IC,
        post_kind="general",
        image_url=image_url,
    )
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)
    return post


class _FakeImage:
    """Minimal stand-in carrying only what the eligibility rules read."""

    def __init__(self, kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
                 provider="fal", metadata_json=None, public_gallery_enabled=True):
        self.kind = kind
        self.status = status
        self.provider = provider
        self.metadata_json = metadata_json if metadata_json is not None else {}
        self.public_gallery_enabled = public_gallery_enabled


@pytest.fixture()
def published(client, db_session):
    """A PUBLIC character whose Home the founder has enabled."""
    token = get_auth_token(client, email="sel-own@test.com", username="selown")
    cid = _create_character(client, token, "Summer")
    _publish(db_session, cid)
    return {
        "token": token,
        "character_id": cid,
        "owner_id": _user_id(db_session, "sel-own@test.com"),
    }


# ── A. Defaults: nothing is selected by shipping the column ───────────────────

def test_model_default_is_false_without_an_explicit_value(db_session):
    """The path a migrated pre-Step-6.5 row takes: nothing set it, reads false."""
    user = User(email="sel-def@test.com", username="seldef", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    character = Character(owner_id=user.id, name="Unset", visibility=VisibilityEnum.PUBLIC)
    db_session.add(character)
    db_session.commit()

    image = CharacterImage(
        character_id=character.id,
        user_id=user.id,
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        file_path="static/generated/unset.png",
    )
    db_session.add(image)
    db_session.commit()
    db_session.refresh(image)

    assert image.public_gallery_enabled is False
    assert is_selected_for_public_gallery(image) is False
    assert is_public_gallery_visible(image) is False


def test_a_row_without_the_attribute_at_all_reads_unselected():
    """Fail-closed: a duck-typed stand-in that never had the column is not selected."""

    class _Legacy:
        kind = ImageKindEnum.GENERATED
        status = ImageStatusEnum.ACTIVE
        provider = "fal"
        metadata_json = {}

    legacy = _Legacy()
    assert is_public_gallery_image(legacy) is True
    assert is_selected_for_public_gallery(legacy) is False
    assert is_public_gallery_visible(legacy) is False


def test_generated_images_are_not_selected_by_default(client, db_session, published):
    """An image produced through the ordinary generation path is never born public."""
    cid, uid = published["character_id"], published["owner_id"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/d1.png")

    assert _image(db_session, image_id).public_gallery_enabled is False
    assert client.get(f"/characters/{cid}/images").json() == []


# ── B. The predicate: selection AND safety, never selection alone ─────────────

@pytest.mark.parametrize("selected,expected", [(True, True), (False, False)])
def test_selection_decides_for_an_otherwise_eligible_image(selected, expected):
    assert is_public_gallery_visible(
        _FakeImage(public_gallery_enabled=selected)
    ) is expected


@pytest.mark.parametrize("kind,provider,metadata", [
    (ImageKindEnum.GENERATED, "replicate_nsfw", {"adult_studio": True}),
    (ImageKindEnum.SCENE_ONLY, "gpt-image", {"editor_generated": True}),
    (ImageKindEnum.ANCHOR_FRONT, "fal", {}),
    (ImageKindEnum.IDENTITY_SKETCH, "fal", {}),
    (ImageKindEnum.UPLOADED, "fal", {}),
    (ImageKindEnum.GENERATED, "fal", {"is_temp": True}),
])
def test_selection_never_overrides_the_safety_rule(kind, provider, metadata):
    """Layer 2 can subtract from layer 3. It can never add to it."""
    image = _FakeImage(
        kind=kind, provider=provider, metadata_json=metadata,
        public_gallery_enabled=True,
    )
    assert is_selected_for_public_gallery(image) is True
    assert is_public_gallery_image(image) is False
    assert is_public_gallery_visible(image) is False


def test_selection_does_not_resurrect_an_archived_image():
    assert is_public_gallery_visible(_FakeImage(
        status=ImageStatusEnum.ARCHIVED, public_gallery_enabled=True,
    )) is False


def test_the_safety_predicate_itself_ignores_selection():
    """``is_public_gallery_image`` stays Ficshon's own rule, unmoved by curation.

    It governs surfaces that have no notion of gallery selection, so a
    creator-controlled flag must not be able to change its answer either way.
    """
    for selected in (True, False):
        assert is_public_gallery_image(
            _FakeImage(public_gallery_enabled=selected)
        ) is True


# ── C. The anonymous gallery ─────────────────────────────────────────────────

def test_anonymous_gallery_shows_only_selected_images(client, db_session, published):
    cid, uid = published["character_id"], published["owner_id"]
    shown = _insert_image(db_session, cid, uid, file_path="static/generated/c1.png",
                          selected=True)
    _insert_image(db_session, cid, uid, file_path="static/generated/c2.png")

    resp = client.get(f"/characters/{cid}/images")
    assert resp.status_code == 200, resp.text
    assert [i["id"] for i in resp.json()] == [shown]


def test_anonymous_gallery_still_withholds_selected_unsafe_media(client, db_session, published):
    """The regression that matters most: a creator cannot select past safety."""
    cid, uid = published["character_id"], published["owner_id"]
    clean = _insert_image(db_session, cid, uid, file_path="static/generated/c3.png",
                          selected=True)
    _insert_image(db_session, cid, uid, file_path="static/generated/c4.png",
                  provider="replicate_nsfw", metadata={"adult_studio": True},
                  selected=True)
    _insert_image(db_session, cid, uid, file_path="static/generated/c5.png",
                  kind=ImageKindEnum.SCENE_ONLY, provider="gpt-image",
                  metadata={"editor_generated": True}, selected=True)
    _insert_image(db_session, cid, uid, file_path="static/generated/c6.png",
                  kind=ImageKindEnum.ANCHOR_FRONT, selected=True)
    _insert_image(db_session, cid, uid, file_path="static/generated/c7.png",
                  metadata={"is_temp": True}, selected=True)

    resp = client.get(f"/characters/{cid}/images")
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()} == {clean}


def test_selection_does_not_publish_an_unpublished_home(client, db_session):
    """Layer 1 is still required: selecting images does not open a closed Home."""
    token = get_auth_token(client, email="sel-off@test.com", username="seloff")
    cid = _create_character(client, token, "Summer")
    uid = _user_id(db_session, "sel-off@test.com")
    _insert_image(db_session, cid, uid, file_path="static/generated/c8.png", selected=True)
    assert _row(db_session, cid).public_home_enabled is False

    assert client.get(f"/characters/{cid}/images").status_code == 404


def test_selection_does_not_publish_a_private_character(client, db_session):
    """Nor does it override the creator's own privacy choice."""
    token = get_auth_token(client, email="sel-priv@test.com", username="selpriv")
    cid = _create_character(client, token, "Hidden", visibility="private")
    _publish(db_session, cid)
    uid = _user_id(db_session, "sel-priv@test.com")
    _insert_image(db_session, cid, uid, file_path="static/generated/c9.png", selected=True)

    assert client.get(f"/characters/{cid}/images").status_code == 404


def test_unselecting_withdraws_an_image_from_the_anonymous_gallery(client, db_session, published):
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/c10.png",
                             selected=True)
    assert [i["id"] for i in client.get(f"/characters/{cid}/images").json()] == [image_id]

    assert _select(client, token, cid, image_id, enabled=False).status_code == 200
    assert client.get(f"/characters/{cid}/images").json() == []


def test_the_anonymous_gallery_shape_carries_no_selection_field(client, db_session, published):
    """``CharacterImagePublic`` stays narrow — curation state is not visitor information."""
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(db_session, cid, uid, file_path="static/generated/c11.png", selected=True)

    body = client.get(f"/characters/{cid}/images").json()
    assert len(body) == 1
    assert set(body[0].keys()) == {"id", "character_id", "kind", "created_at", "url"}


# ── D. Authenticated views are unaffected by the flag ─────────────────────────

def test_owner_media_is_unaffected_by_selection(client, db_session, published):
    """The creator's own library is their whole library, selected or not."""
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    selected = _insert_image(db_session, cid, uid, file_path="static/generated/d2.png",
                             selected=True)
    unselected = _insert_image(db_session, cid, uid, file_path="static/generated/d3.png")
    anchor = _insert_image(db_session, cid, uid, file_path="static/generated/d4.png",
                           kind=ImageKindEnum.ANCHOR_FRONT)

    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()} == {selected, unselected, anchor}


def test_owner_media_reports_the_selection_state(client, db_session, published):
    """The Media UI has to know which images are already on the Home."""
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    selected = _insert_image(db_session, cid, uid, file_path="static/generated/d5.png",
                             selected=True)
    unselected = _insert_image(db_session, cid, uid, file_path="static/generated/d6.png")

    by_id = {i["id"]: i for i in
             client.get(f"/characters/{cid}/images", headers=auth_headers(token)).json()}
    assert by_id[selected]["public_gallery_enabled"] is True
    assert by_id[unselected]["public_gallery_enabled"] is False


def test_admin_media_is_unaffected_by_selection(client, db_session, published):
    cid, uid = published["character_id"], published["owner_id"]
    a = _insert_image(db_session, cid, uid, file_path="static/generated/d7.png")
    b = _insert_image(db_session, cid, uid, file_path="static/generated/d8.png", selected=True)

    admin_token = get_auth_token(client, email="sel-adm@test.com", username="seladm")
    _make_admin(db_session, "sel-adm@test.com")

    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()} == {a, b}


def test_signed_in_stranger_gallery_is_unchanged_by_selection(client, db_session, published):
    """Pinned deliberately: curation is an anonymous-surface rule for now.

    Applying it to the signed-in branch would empty every in-product gallery on
    the day the column ships, since no image has ever been selected. That is a
    product decision about Ficshon's own surfaces, separate from publishing the
    Character Home, and it must be taken explicitly rather than inherited here.
    """
    cid, uid = published["character_id"], published["owner_id"]
    selected = _insert_image(db_session, cid, uid, file_path="static/generated/d9.png",
                             selected=True)
    unselected = _insert_image(db_session, cid, uid, file_path="static/generated/d10.png")

    stranger = get_auth_token(client, email="sel-str@test.com", username="selstr")
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(stranger))
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()} == {selected, unselected}


# ── E. The selection endpoint ────────────────────────────────────────────────

def test_owner_can_select_and_unselect(client, db_session, published):
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e1.png")

    resp = _select(client, token, cid, image_id, enabled=True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_gallery_enabled"] is True
    assert _image(db_session, image_id).public_gallery_enabled is True

    resp = _select(client, token, cid, image_id, enabled=False)
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_gallery_enabled"] is False
    assert _image(db_session, image_id).public_gallery_enabled is False


def test_admin_can_select(client, db_session, published):
    cid, uid = published["character_id"], published["owner_id"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e2.png")

    admin_token = get_auth_token(client, email="sel-adm2@test.com", username="seladm2")
    _make_admin(db_session, "sel-adm2@test.com")

    assert _select(client, admin_token, cid, image_id).status_code == 200
    assert _image(db_session, image_id).public_gallery_enabled is True


def test_a_stranger_cannot_select(client, db_session, published):
    cid, uid = published["character_id"], published["owner_id"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e3.png")

    stranger = get_auth_token(client, email="sel-str2@test.com", username="selstr2")
    assert _select(client, stranger, cid, image_id).status_code == 403
    assert _image(db_session, image_id).public_gallery_enabled is False


def test_selection_requires_authentication(client, db_session, published):
    cid, uid = published["character_id"], published["owner_id"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e4.png")

    resp = client.post(
        f"/characters/{cid}/images/{image_id}/public-gallery", json={"enabled": True}
    )
    assert resp.status_code in (401, 403)
    assert _image(db_session, image_id).public_gallery_enabled is False


def test_unknown_character_and_image_are_404(client, db_session, published):
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e5.png")

    assert _select(client, token, 999999, image_id).status_code == 404
    assert _select(client, token, cid, 999999).status_code == 404


def test_an_image_belonging_to_another_character_is_404(client, db_session, published):
    """The image id is scoped to the character in the path, not global.

    The other character belongs to another account — one character per account —
    which also proves an owner cannot reach outside their own character by id.
    """
    other_token = get_auth_token(client, email="sel-oth@test.com", username="seloth")
    other_cid = _create_character(client, other_token, "Autumn")
    other_uid = _user_id(db_session, "sel-oth@test.com")
    image_id = _insert_image(db_session, other_cid, other_uid,
                             file_path="static/generated/e6.png")

    assert _select(client, published["token"], published["character_id"],
                   image_id).status_code == 404
    assert _image(db_session, image_id).public_gallery_enabled is False


@pytest.mark.parametrize("kwargs", [
    {"provider": "replicate_nsfw", "metadata": {"adult_studio": True}},
    {"kind": ImageKindEnum.SCENE_ONLY, "provider": "gpt-image",
     "metadata": {"editor_generated": True}},
    {"kind": ImageKindEnum.ANCHOR_FRONT},
    {"kind": ImageKindEnum.UPLOADED},
    {"metadata": {"is_temp": True}},
])
def test_selecting_an_ineligible_image_is_refused(client, db_session, published, kwargs):
    """Feedback, not the guarantee — the read path withholds these regardless."""
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e7.png",
                             **kwargs)

    resp = _select(client, token, cid, image_id, enabled=True)
    assert resp.status_code == 422, resp.text
    assert _image(db_session, image_id).public_gallery_enabled is False


def test_unselecting_an_ineligible_image_always_succeeds(client, db_session, published):
    """A creator must always be able to withdraw an image, whatever its state."""
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e8.png",
                             provider="replicate_nsfw", metadata={"adult_studio": True},
                             selected=True)

    resp = _select(client, token, cid, image_id, enabled=False)
    assert resp.status_code == 200, resp.text
    assert _image(db_session, image_id).public_gallery_enabled is False


def test_selecting_an_archived_image_is_404(client, db_session, published):
    """Archiving IS the owner's delete; the route scopes to ACTIVE like its siblings."""
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e9.png",
                             status=ImageStatusEnum.ARCHIVED)

    assert _select(client, token, cid, image_id).status_code == 404


def test_selection_works_before_the_home_is_published(client, db_session):
    """Curation is not gated on publication — a creator can prepare in advance."""
    token = get_auth_token(client, email="sel-pre@test.com", username="selpre")
    cid = _create_character(client, token, "Summer")
    uid = _user_id(db_session, "sel-pre@test.com")
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e10.png")

    assert _select(client, token, cid, image_id).status_code == 200
    # Still unpublished, so still invisible.
    assert client.get(f"/characters/{cid}/images").status_code == 404

    _publish(db_session, cid)
    assert [i["id"] for i in client.get(f"/characters/{cid}/images").json()] == [image_id]


def test_the_route_is_also_mounted_under_api(client, db_session, published):
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/e11.png")

    resp = client.post(
        f"/api/characters/{cid}/images/{image_id}/public-gallery",
        json={"enabled": True}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


# ── F. Toggling changes nothing else about the image ─────────────────────────

def test_toggling_leaves_visibility_kind_status_and_provenance_untouched(
    client, db_session, published
):
    """The whole point of a dedicated column: nothing else moves."""
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    metadata = {"library": True, "prompt": "a quiet room"}
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/f1.png",
                             provider="fal", metadata=metadata)

    before = _image(db_session, image_id)
    snapshot = (before.kind, before.status, before.visibility, before.provider,
                dict(before.metadata_json), before.file_path, before.user_id)

    assert _select(client, token, cid, image_id, enabled=True).status_code == 200
    after = _image(db_session, image_id)
    assert (after.kind, after.status, after.visibility, after.provider,
            dict(after.metadata_json), after.file_path, after.user_id) == snapshot
    assert after.public_gallery_enabled is True

    assert _select(client, token, cid, image_id, enabled=False).status_code == 200
    after = _image(db_session, image_id)
    assert (after.kind, after.status, after.visibility, after.provider,
            dict(after.metadata_json), after.file_path, after.user_id) == snapshot


def test_visibility_stays_private_and_keeps_its_own_meaning(client, db_session, published):
    """``visibility`` was not repurposed: selecting does not make it PUBLIC."""
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/f2.png")

    _select(client, token, cid, image_id, enabled=True)
    row = _image(db_session, image_id)
    assert row.visibility == ImageVisibilityEnum.PRIVATE
    assert row.public_gallery_enabled is True
    # And the enum itself still has exactly the two states it always had.
    assert {m.value for m in ImageVisibilityEnum} == {"private", "public"}


def test_a_public_visibility_row_is_still_not_selected(db_session):
    """The two columns are independent in both directions."""
    assert is_public_gallery_visible(_FakeImage(public_gallery_enabled=False)) is False


# ── G. Other public surfaces are unaffected ──────────────────────────────────

def test_avatar_and_cover_do_not_answer_to_the_gallery_flag(client, db_session, published):
    """A Home's portrait is not a gallery piece and is not curated as one."""
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(db_session, cid, uid, file_path="static/generated/g1.png")
    _insert_image(db_session, cid, uid, file_path="static/generated/g2.png")
    row = _row(db_session, cid)
    row.avatar_url = "/static/generated/g1.png"
    row.cover_url = "/static/generated/g2.png"
    db_session.commit()

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["avatar_url"] == "/static/generated/g1.png"
    assert body["cover_url"] == "/static/generated/g2.png"
    # ...and the gallery beside them is still empty, because nothing is selected.
    assert client.get(f"/characters/{cid}/images").json() == []


def test_set_avatar_still_works_for_an_unselected_image(client, db_session, published):
    cid, uid, token = published["character_id"], published["owner_id"], published["token"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/g3.png")

    resp = client.post(f"/characters/{cid}/images/{image_id}/set-avatar",
                       headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_gallery_enabled"] is False
    # Setting an avatar is not a gallery selection either.
    assert _image(db_session, image_id).public_gallery_enabled is False


def test_post_attachments_do_not_answer_to_the_gallery_flag(client, db_session, published):
    """A published post keeps its image whether or not it is a gallery piece."""
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(db_session, cid, uid, file_path="static/generated/g4.png")

    realm = _realm(db_session, uid, "Gallery Selection Realm", is_public=True)
    _post(db_session, author_user_id=uid, character_id=cid, realm_id=realm.id,
          image_url="/static/generated/g4.png")

    timeline = client.get(f"/characters/{cid}/public-home/posts")
    assert timeline.status_code == 200, timeline.text
    assert [p["image_url"] for p in timeline.json()] == ["/static/generated/g4.png"]
    # The same image is still absent from the curated gallery.
    assert client.get(f"/characters/{cid}/images").json() == []
