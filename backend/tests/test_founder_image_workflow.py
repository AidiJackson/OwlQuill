"""Founder image workflow — character-first library, public gallery privacy,
entitlement gating, and safe image assignment.

Companion to test_images.py (quota) — this file covers the Sprint additions:
  * viewer-aware GET /characters/{id}/images (public gallery vs owner workshop)
  * server-side character_id filtering on /users/me/character-images
  * cross-owner isolation
  * require_creator gating (Wanderer cannot generate)
  * image assignment cannot target the wrong character
"""
from tests.conftest import get_auth_token, auth_headers


# ── helpers ───────────────────────────────────────────────────────────────

def _create_character(client, token, name="Shadow", visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _insert_image(db_session, character_id, user_id, kind, prompt="secret prompt"):
    """Insert a CharacterImage directly (bypasses generation/quota)."""
    from app.models.character_image import (
        CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum,
    )
    img = CharacterImage(
        character_id=character_id,
        user_id=user_id,
        kind=ImageKindEnum(kind),
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="stub",
        prompt_summary=prompt,
        seed="12345",
        metadata_json={"library": True, "prompt": prompt},
        file_path="static/generated/test.png",
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img.id


def _user_id(db_session, email):
    from app.models.user import User
    return db_session.query(User).filter(User.email == email).first().id


def _make_seeder(db_session, email):
    """Exempt an account from the one-character-per-account limit (multi-char tests)."""
    from app.models.user import User
    user = db_session.query(User).filter(User.email == email).first()
    user.is_seeder = True
    db_session.commit()


# ── The allowlist itself ────────────────────────────────────────────────────

def test_public_gallery_allowlist_is_exactly_the_three_shareable_kinds():
    """Server-side half of a two-sided pin.

    The client mirrors this list in frontend/src/features/images/galleryKinds.ts
    (pinned by its own test). Both must be edited together — a kind added here
    alone silently widens what the public sees; a kind added there alone shows
    creators a filter that returns nothing.
    """
    from app.models.character_image import ImageKindEnum
    from app.schemas.character_image import PUBLIC_GALLERY_KINDS

    assert PUBLIC_GALLERY_KINDS == frozenset({
        ImageKindEnum.GENERATED,
        ImageKindEnum.COVER,
        ImageKindEnum.SCENE_ONLY,
    })
    assert {k.value for k in PUBLIC_GALLERY_KINDS} == {"generated", "cover", "scene_only"}


def test_public_image_schema_exposes_only_the_five_safe_fields():
    """Guards the shape at the schema level, not just through one endpoint.

    A field added to CharacterImagePublic leaks on every public gallery at
    once, so the field set is asserted directly rather than inferred from a
    sample response.
    """
    from app.schemas.character_image import CharacterImagePublic

    assert set(CharacterImagePublic.model_fields) == {
        "id", "character_id", "kind", "created_at", "url",
    }


# ── Public gallery vs owner workshop ────────────────────────────────────────

def test_public_media_returns_only_allowlisted_kinds_without_metadata(client, db_session):
    owner = get_auth_token(client, email="pmowner@test.com", username="pmowner")
    cid = _create_character(client, owner, "Shadow")
    uid = _user_id(db_session, "pmowner@test.com")

    _insert_image(db_session, cid, uid, "generated", prompt="a real gallery piece")
    _insert_image(db_session, cid, uid, "identity_sketch", prompt="private working sketch")
    _insert_image(db_session, cid, uid, "anchor_front", prompt="anchor reference")

    # A different, unrelated viewer (a Wanderer) hits the public character.
    viewer = get_auth_token(client, email="pmviewer@test.com", username="pmviewer")
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(viewer))
    assert resp.status_code == 200, resp.text
    imgs = resp.json()

    # Only the allowlisted 'generated' image is visible.
    assert len(imgs) == 1
    assert imgs[0]["kind"] == "generated"

    # And no private metadata leaked in the public shape.
    for forbidden in ("prompt_summary", "provider", "seed", "metadata_json", "user_id", "visibility", "status"):
        assert forbidden not in imgs[0], f"public payload leaked {forbidden}"
    assert set(imgs[0].keys()) == {"id", "character_id", "kind", "url", "created_at"}


def test_owner_sees_full_working_set_with_metadata(client, db_session):
    owner = get_auth_token(client, email="fullowner@test.com", username="fullowner")
    cid = _create_character(client, owner, "Shadow")
    uid = _user_id(db_session, "fullowner@test.com")
    _insert_image(db_session, cid, uid, "generated")
    _insert_image(db_session, cid, uid, "identity_sketch")

    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    imgs = resp.json()
    # Owner sees BOTH kinds (working references included)...
    kinds = {i["kind"] for i in imgs}
    assert "generated" in kinds and "identity_sketch" in kinds
    # ...with full metadata present.
    assert any("prompt_summary" in i for i in imgs)


def test_anonymous_visitor_gets_the_curated_public_shape(client, db_session):
    """The gallery of a public character is readable with no credentials at all.

    This is the case most likely to regress: the viewer-aware branch keys off
    ``current_user``, and an unauthenticated request is the one path where that
    is None. If the branch is ever rewritten to assume a user, this test fails
    rather than the whole workshop being served to the open internet.
    """
    owner = get_auth_token(client, email="anonowner@test.com", username="anonowner")
    cid = _create_character(client, owner, "Public Face", visibility="public")
    uid = _user_id(db_session, "anonowner@test.com")
    _insert_image(db_session, cid, uid, "generated", prompt="gallery piece")
    _insert_image(db_session, cid, uid, "anchor_front", prompt="anchor reference")

    resp = client.get(f"/characters/{cid}/images")  # no Authorization header
    assert resp.status_code == 200, resp.text
    imgs = resp.json()
    assert len(imgs) == 1
    assert imgs[0]["kind"] == "generated"
    assert set(imgs[0].keys()) == {"id", "character_id", "kind", "url", "created_at"}


def test_private_character_gallery_is_closed_to_outsiders(client, db_session):
    """Kind-allowlisting is the SECOND line of defence, not the first.

    A private character's images must not be reachable at all — not even in the
    narrow public shape — by an anonymous visitor or a logged-in stranger.
    """
    owner = get_auth_token(client, email="privowner@test.com", username="privowner")
    cid = _create_character(client, owner, "Hidden", visibility="private")
    uid = _user_id(db_session, "privowner@test.com")
    _insert_image(db_session, cid, uid, "generated")

    assert client.get(f"/characters/{cid}/images").status_code == 403

    stranger = get_auth_token(client, email="privstranger@test.com", username="privstranger")
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(stranger))
    assert resp.status_code == 403, resp.text

    # ...but the owner still sees their own material.
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


def test_unaccepted_pack_previews_stay_out_of_the_public_gallery(client, db_session):
    """A temp image can carry an allowlisted kind, so the kind check alone is
    not enough — ``is_public_gallery_image`` must also reject ``is_temp``.
    Otherwise a preview the owner never accepted appears in the public gallery.
    """
    from app.models.character_image import CharacterImage

    owner = get_auth_token(client, email="tempowner@test.com", username="tempowner")
    cid = _create_character(client, owner, "Draftsman")
    uid = _user_id(db_session, "tempowner@test.com")
    keeper = _insert_image(db_session, cid, uid, "generated")
    temp_id = _insert_image(db_session, cid, uid, "generated")

    temp = db_session.query(CharacterImage).filter(CharacterImage.id == temp_id).first()
    temp.metadata_json = {**(temp.metadata_json or {}), "is_temp": True}
    db_session.commit()

    viewer = get_auth_token(client, email="tempviewer@test.com", username="tempviewer")
    imgs = client.get(f"/characters/{cid}/images", headers=auth_headers(viewer)).json()
    assert [i["id"] for i in imgs] == [keeper]

    # The owner doesn't see it either — it's an unaccepted preview, not content.
    own = client.get(f"/characters/{cid}/images", headers=auth_headers(owner)).json()
    assert [i["id"] for i in own] == [keeper]


def test_kind_filter_narrows_the_owner_library(client, db_session):
    """Server-side ``kind`` filtering — the library must not pull the whole
    archive down and filter in the browser."""
    owner = get_auth_token(client, email="kindowner@test.com", username="kindowner")
    uid = _user_id(db_session, "kindowner@test.com")
    cid = _create_character(client, owner, "Assorted")
    gen = _insert_image(db_session, cid, uid, "generated")
    _insert_image(db_session, cid, uid, "cover")
    _insert_image(db_session, cid, uid, "identity_sketch")

    resp = client.get(
        f"/users/me/character-images?character_id={cid}&kind=generated",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert [i["id"] for i in resp.json()] == [gen]

    # Repeatable — the library asks for its whole allowlist in one call.
    resp = client.get(
        f"/users/me/character-images?character_id={cid}&kind=generated&kind=cover",
        headers=auth_headers(owner),
    )
    assert {i["kind"] for i in resp.json()} == {"generated", "cover"}


def test_limit_and_offset_paginate_after_temp_filtering(client, db_session):
    """Pagination is applied AFTER temp rows are dropped, so a page is never
    short-changed by rows the caller can't see."""
    from app.models.character_image import CharacterImage

    owner = get_auth_token(client, email="pageowner@test.com", username="pageowner")
    uid = _user_id(db_session, "pageowner@test.com")
    cid = _create_character(client, owner, "Paginated")
    ids = [_insert_image(db_session, cid, uid, "generated") for _ in range(4)]

    # Make the NEWEST row temp — a naive LIMIT 2 would return only one visible row.
    temp = db_session.query(CharacterImage).filter(CharacterImage.id == ids[-1]).first()
    temp.metadata_json = {**(temp.metadata_json or {}), "is_temp": True}
    db_session.commit()

    resp = client.get(
        f"/users/me/character-images?character_id={cid}&sort=newest&limit=2",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert len(page) == 2
    assert [i["id"] for i in page] == [ids[2], ids[1]]

    resp = client.get(
        f"/users/me/character-images?character_id={cid}&sort=newest&limit=2&offset=2",
        headers=auth_headers(owner),
    )
    assert [i["id"] for i in resp.json()] == [ids[0]]


# ── Server-side character filter + cross-owner isolation ────────────────────

def test_character_id_filter_scopes_to_that_character(client, db_session):
    owner = get_auth_token(client, email="filterowner@test.com", username="filterowner")
    _make_seeder(db_session, "filterowner@test.com")
    uid = _user_id(db_session, "filterowner@test.com")
    a = _create_character(client, owner, "CharA")
    b = _create_character(client, owner, "CharB")
    _insert_image(db_session, a, uid, "generated")
    _insert_image(db_session, a, uid, "generated")
    _insert_image(db_session, b, uid, "generated")

    resp = client.get(f"/users/me/character-images?character_id={a}", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    imgs = resp.json()
    assert len(imgs) == 2
    assert all(i["character_id"] == a for i in imgs)


def test_cannot_query_another_owners_character_images(client, db_session):
    owner = get_auth_token(client, email="iso-owner@test.com", username="isoowner")
    uid = _user_id(db_session, "iso-owner@test.com")
    cid = _create_character(client, owner, "Private")
    _insert_image(db_session, cid, uid, "generated")

    intruder = get_auth_token(client, email="iso-intruder@test.com", username="isointruder")
    # Asking for a character you don't own is a 403 — never a silent empty list
    # that could be used to probe which ids exist.
    resp = client.get(f"/users/me/character-images?character_id={cid}", headers=auth_headers(intruder))
    assert resp.status_code == 403, resp.text


def test_sort_order_respected(client, db_session):
    owner = get_auth_token(client, email="sortowner@test.com", username="sortowner")
    uid = _user_id(db_session, "sortowner@test.com")
    cid = _create_character(client, owner, "Sortie")
    first = _insert_image(db_session, cid, uid, "generated")
    second = _insert_image(db_session, cid, uid, "generated")

    newest = client.get(f"/users/me/character-images?character_id={cid}&sort=newest", headers=auth_headers(owner)).json()
    oldest = client.get(f"/users/me/character-images?character_id={cid}&sort=oldest", headers=auth_headers(owner)).json()
    assert [i["id"] for i in newest][0] == second
    assert [i["id"] for i in oldest][0] == first


# ── Safe image assignment ───────────────────────────────────────────────────

def test_assignment_cannot_target_wrong_character(client, db_session):
    owner = get_auth_token(client, email="assignowner@test.com", username="assignowner")
    _make_seeder(db_session, "assignowner@test.com")
    uid = _user_id(db_session, "assignowner@test.com")
    a = _create_character(client, owner, "Owner Of Image")
    b = _create_character(client, owner, "Wrong Target")
    img_id = _insert_image(db_session, a, uid, "generated")

    # Try to set character A's image as character B's avatar — the backend
    # scopes the image lookup by character, so B never gets A's image.
    resp = client.post(
        f"/characters/{b}/images/{img_id}/set-avatar",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404, resp.text


# ── Entitlement gating ──────────────────────────────────────────────────────

def test_wanderer_cannot_generate_images(client):
    """A Wanderer (no characters, no flags) is refused by require_creator."""
    wanderer = get_auth_token(client, email="wanderer@test.com", username="wanderer_one")
    resp = client.post(
        "/api/images/generate",
        json={"prompt": "anything"},
        headers=auth_headers(wanderer),
    )
    assert resp.status_code == 403, resp.text


def test_creator_with_character_can_generate(client):
    creator = get_auth_token(client, email="realcreator@test.com", username="realcreator")
    _create_character(client, creator, "Muse")
    resp = client.post(
        "/api/images/generate",
        json={"prompt": "a muse at dawn"},
        headers=auth_headers(creator),
    )
    assert resp.status_code == 200, resp.text
