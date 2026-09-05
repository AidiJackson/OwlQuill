"""Post image attachment is scoped to the ACTING character, not the account.

A post is authored by one character. Owning Shadow does not entitle a post
authored by Pan to Shadow's media, and the picker must not offer it. The server
is the boundary: the acting character comes from the verified post payload, so a
forged image path cannot cross characters.

Also covers the kind allowlist — identity sketches, anchors, face/body refs and
accessory sheets are private production material and are never publishable.
"""
import pytest

from app.models.character_image import (
    POST_ATTACHABLE_IMAGE_KINDS,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
)
from app.models.provenance import Provenance
from tests.conftest import auth_headers, get_auth_token


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_character(client, token, name):
    resp = client.post(
        "/characters/", json={"name": name, "species": "human"}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_image(db, character_id, file_path, kind=ImageKindEnum.GENERATED,
                status=ImageStatusEnum.ACTIVE):
    """Seed an image OWNED by the character's owner.

    ``user_id`` is stamped from ``Character.owner_id`` because that is what
    every real write path does, and since Phase 4B1 it is what ownership means:
    a row with no ``user_id`` belongs to nobody and correctly appears in no
    account's library. Leaving it NULL here would test a state the application
    cannot produce.
    """
    from app.models.character import Character

    owner_id = db.query(Character.owner_id).filter(
        Character.id == character_id
    ).scalar()
    img = CharacterImage(
        character_id=character_id,
        user_id=owner_id,
        file_path=file_path,
        kind=kind,
        status=status,
        visibility="public",
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


def _commons_realm(client, token):
    created = client.post(
        "/realms/",
        json={"name": "Scope Realm", "slug": "scope-realm", "is_public": True},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _post_with_image(client, token, realm_id, character_id, image_url):
    return client.post(
        f"/posts/realms/{realm_id}/posts",
        json={
            "content": "A post with an attachment.",
            "character_id": character_id,
            "image_url": image_url,
        },
        headers=auth_headers(token),
    )


@pytest.fixture
def two_characters(client, db_session):
    """One account owning Pan and Shadow, each with one attachable image.

    Uses a seeder account so both characters can exist on one owner — the
    one-character limit is not what these tests are about.
    """
    from app.models.user import User

    token = get_auth_token(client, email="scope@test.com", username="scopeuser")
    user = db_session.query(User).filter(User.email == "scope@test.com").first()
    user.is_seeder = True
    db_session.commit()

    pan = _make_character(client, token, "Pan")
    shadow = _make_character(client, token, "Shadow")
    pan_img = _seed_image(db_session, pan, "static/generated/pan-one.png")
    shadow_img = _seed_image(db_session, shadow, "static/generated/shadow-new.png")
    return {
        "token": token,
        "pan": pan,
        "shadow": shadow,
        "pan_img": pan_img,
        "shadow_img": shadow_img,
        "realm": _commons_realm(client, token),
    }


# ── picker scope ──────────────────────────────────────────────────────────────

def test_picker_returns_only_pan_images(client, two_characters):
    resp = client.get(
        f"/users/me/character-images?character_id={two_characters['pan']}",
        headers=auth_headers(two_characters["token"]),
    )
    assert resp.status_code == 200, resp.text
    paths = {i["file_path"] for i in resp.json()}
    assert paths == {"static/generated/pan-one.png"}
    assert "static/generated/shadow-new.png" not in paths


def test_picker_returns_only_shadow_images(client, two_characters):
    resp = client.get(
        f"/users/me/character-images?character_id={two_characters['shadow']}",
        headers=auth_headers(two_characters["token"]),
    )
    assert resp.status_code == 200, resp.text
    paths = {i["file_path"] for i in resp.json()}
    assert paths == {"static/generated/shadow-new.png"}


def test_identity_refs_and_anchors_are_never_offered(client, db_session, two_characters):
    """The private production material must not be publishable."""
    private_kinds = [
        ImageKindEnum.IDENTITY_SKETCH,
        ImageKindEnum.IDENTITY_FACE_REF,
        ImageKindEnum.IDENTITY_BODY_FRONT,
        ImageKindEnum.ANCHOR_FRONT,
        ImageKindEnum.ACCESSORY_DESIGN,
    ]
    for i, kind in enumerate(private_kinds):
        _seed_image(db_session, two_characters["pan"], f"static/generated/private-{i}.png", kind=kind)

    kinds = "&".join(f"kind={k}" for k in sorted(POST_ATTACHABLE_IMAGE_KINDS))
    resp = client.get(
        f"/users/me/character-images?character_id={two_characters['pan']}&{kinds}",
        headers=auth_headers(two_characters["token"]),
    )
    assert resp.status_code == 200, resp.text
    returned = {i["kind"] for i in resp.json()}
    assert returned <= POST_ATTACHABLE_IMAGE_KINDS
    for kind in private_kinds:
        assert kind.value not in returned


def test_another_writer_cannot_read_your_characters_media(client, two_characters):
    other = get_auth_token(client, email="nosy@test.com", username="nosyuser")
    resp = client.get(
        f"/users/me/character-images?character_id={two_characters['pan']}",
        headers=auth_headers(other),
    )
    assert resp.status_code == 403


# ── server-side attachment enforcement ────────────────────────────────────────

def test_pan_may_attach_its_own_image(client, two_characters):
    resp = _post_with_image(
        client, two_characters["token"], two_characters["realm"],
        two_characters["pan"], "/static/generated/pan-one.png",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["image_url"] == "/static/generated/pan-one.png"


def test_pan_cannot_attach_shadows_image(client, two_characters):
    """The reported leak, at the boundary that matters.

    The account owns both characters, so the old account-level ownership check
    accepted this. Posting as Pan must not reach Shadow's media even when the
    client names the path directly.
    """
    resp = _post_with_image(
        client, two_characters["token"], two_characters["realm"],
        two_characters["pan"], "/static/generated/shadow-new.png",
    )
    assert resp.status_code == 403, resp.text


def test_cannot_attach_an_identity_reference(client, db_session, two_characters):
    _seed_image(
        db_session, two_characters["pan"], "static/generated/pan-face-ref.png",
        kind=ImageKindEnum.IDENTITY_FACE_REF,
    )
    resp = _post_with_image(
        client, two_characters["token"], two_characters["realm"],
        two_characters["pan"], "/static/generated/pan-face-ref.png",
    )
    assert resp.status_code == 403, resp.text


def test_cannot_attach_an_inactive_image(client, db_session, two_characters):
    _seed_image(
        db_session, two_characters["pan"], "static/generated/pan-archived.png",
        status=ImageStatusEnum.ARCHIVED,
    )
    resp = _post_with_image(
        client, two_characters["token"], two_characters["realm"],
        two_characters["pan"], "/static/generated/pan-archived.png",
    )
    assert resp.status_code == 403, resp.text


def test_cannot_attach_another_accounts_image(client, db_session, two_characters):
    stranger = get_auth_token(client, email="stranger@test.com", username="strangeruser")
    stranger_char = _make_character(client, stranger, "Outsider")
    _seed_image(db_session, stranger_char, "static/generated/outsider.png")

    resp = _post_with_image(
        client, two_characters["token"], two_characters["realm"],
        two_characters["pan"], "/static/generated/outsider.png",
    )
    assert resp.status_code == 403, resp.text


def test_attached_post_still_gets_correct_provenance(client, two_characters):
    """The image fix must not disturb the provenance decision."""
    token = two_characters["token"]
    session = client.post(
        "/composition/sessions",
        json={"surface": "commons_composer", "target_kind": "post"},
        headers=auth_headers(token),
    ).json()["id"]
    content = "A post with an attachment."
    client.patch(
        f"/composition/sessions/{session}",
        json={"metrics": {"typed_chars": len(content), "inserted_chars": 0,
                          "internal_insert_chars": 0, "largest_insertion": 0,
                          "insertion_count": 0, "edit_duration_ms": 30000}},
        headers=auth_headers(token),
    )
    resp = client.post(
        f"/posts/realms/{two_characters['realm']}/posts",
        json={
            "content": content,
            "character_id": two_characters["pan"],
            "image_url": "/static/generated/pan-one.png",
            "composition_session_id": session,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["provenance"] == Provenance.USER_WRITTEN.value


# ── founder Image Library is a different surface and stays as it was ──────────

def test_founder_library_still_supports_all_characters(client, two_characters):
    """No character_id → the account-wide library, which is correct *here*.

    The founder Image Library is a workspace, not a post composer. Scoping the
    composer must not have narrowed this.
    """
    resp = client.get(
        "/users/me/character-images", headers=auth_headers(two_characters["token"])
    )
    assert resp.status_code == 200, resp.text
    paths = {i["file_path"] for i in resp.json()}
    assert "static/generated/pan-one.png" in paths
    assert "static/generated/shadow-new.png" in paths


def test_founder_library_still_supports_character_filter(client, two_characters):
    resp = client.get(
        f"/users/me/character-images?character_id={two_characters['shadow']}",
        headers=auth_headers(two_characters["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert {i["file_path"] for i in resp.json()} == {"static/generated/shadow-new.png"}


# ── the address the client is expected to send ────────────────────────────────

def test_the_stored_address_is_what_the_server_accepts(client, two_characters):
    """The picker's ``url`` is what a composer must send, unmodified.

    ``/static/generated/x.png`` is how the API addresses the stored path
    ``static/generated/x.png``, and the ownership check strips the leading
    slash to match. Anything a client does to that string on the way through —
    prefixing an API origin for rendering being the case that actually
    happened — no longer matches the image the user just picked, and the post
    is refused with a message about someone else's images.
    """
    ctx = two_characters
    stored = _post_with_image(
        client, ctx["token"], ctx["realm"], ctx["pan"], "/static/generated/pan-one.png"
    )
    assert stored.status_code == 201, stored.text

    rendered = _post_with_image(
        client, ctx["token"], ctx["realm"], ctx["pan"],
        "https://api.ficshon.example/static/generated/pan-one.png",
    )
    assert rendered.status_code == 403


def test_a_post_without_a_character_is_refused_outright(client, two_characters):
    """Posts are authored by characters — a composer that omits one gets no post.

    Pinned because a composer really did omit it: the gallery's "Use in Post"
    action opened a modal that never sent ``character_id``, so every attempt
    from it failed with a message about creating a character the user already
    had.
    """
    ctx = two_characters
    resp = client.post(
        f"/posts/realms/{ctx['realm']}/posts",
        json={"content": "No identity attached.", "image_url": "/static/generated/pan-one.png"},
        headers=auth_headers(ctx["token"]),
    )
    assert resp.status_code == 403
