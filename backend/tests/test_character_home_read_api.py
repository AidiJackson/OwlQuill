"""Character Home Step 4 — the anonymous read API.

The first Ficshon surface that answers without a token, so these tests carry
more weight than usual. Three things are pinned:

1. **The gate.** ``GET /characters/{id}/public-home`` answers only for a
   publishable character, and every other case — missing, PRIVATE, FRIENDS,
   PUBLIC-without-the-grant — is the *same* 404. A visitor walking the id space
   must not be able to tell an unpublished character from one that was never
   created.
2. **The projection.** The response is an allowlist, asserted as an exact key
   set rather than a handful of ``not in`` checks, so a field added to the
   character model or to the internal schema cannot arrive here unnoticed.
3. **The gallery.** ``GET /characters/{id}/images`` moved its ANONYMOUS branch
   onto the same predicate — it previously served any PUBLIC character, which
   published a character's media while its Home stayed unpublished — while its
   authenticated branch is untouched. Step 6.5 added creator selection on top of
   that branch, and Step 6.6 moved the surface out altogether: the anonymous
   gallery is now ``GET /characters/{id}/public-home/images`` and the old route
   is authenticated-only. The curation layer is pinned in
   ``test_character_home_gallery_selection.py`` and the projection in
   ``test_character_home_gallery_projection.py``; what stays here is the
   publication rule they both answer to.
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
from app.models.user import User
from tests.conftest import auth_headers, get_auth_token


#: Every field the anonymous profile may contain — the contract, in one place.
PUBLIC_HOME_FIELDS = {
    "id", "name", "alias", "role", "era", "species",
    "short_bio", "long_bio", "tags",
    "avatar_url", "avatar_position_x", "avatar_position_y", "avatar_scale",
    "cover_url", "cover_position_x", "cover_position_y", "cover_scale",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_character(client, token, name="Summer", visibility="public", **extra):
    body = {"name": name, "species": "human", "visibility": visibility}
    body.update(extra)
    resp = client.post("/characters/", json=body, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _row(db_session, character_id) -> Character:
    db_session.expire_all()
    return db_session.query(Character).filter(Character.id == character_id).first()


def _publish(db_session, character_id, enabled=True):
    """Grant the founder half of the publication rule, as the admin route does."""
    row = db_session.query(Character).filter(Character.id == character_id).first()
    row.public_home_enabled = enabled
    db_session.commit()


def _set_visibility(db_session, character_id, visibility):
    row = db_session.query(Character).filter(Character.id == character_id).first()
    row.visibility = visibility
    db_session.commit()


def _user_id(db_session, email) -> int:
    return db_session.query(User).filter(User.email == email).first().id


def _insert_image(db_session, character_id, user_id, *, file_path,
                  kind=ImageKindEnum.GENERATED, provider="fal", metadata=None,
                  selected=False):
    """``selected`` is the Step 6.5 Character Home gallery choice.

    False by default, as a real image is. The avatar/cover tests leave it alone
    — those surfaces do not answer to it — and only the anonymous gallery tests
    below set it.
    """
    img = CharacterImage(
        character_id=character_id,
        user_id=user_id,
        kind=kind,
        status=ImageStatusEnum.ACTIVE,
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


def _set_media(db_session, character_id, *, avatar_url=None, cover_url=None):
    row = db_session.query(Character).filter(Character.id == character_id).first()
    if avatar_url is not None:
        row.avatar_url = avatar_url
    if cover_url is not None:
        row.cover_url = cover_url
    db_session.commit()


@pytest.fixture()
def published(client, db_session):
    """A PUBLIC character whose Home the founder has enabled."""
    token = get_auth_token(client, email="home-own@test.com", username="homeown")
    cid = _create_character(client, token, "Summer", age="27")
    _publish(db_session, cid)
    return {
        "token": token,
        "character_id": cid,
        "owner_id": _user_id(db_session, "home-own@test.com"),
    }


# ── A. The publication gate ───────────────────────────────────────────────────

def test_nonexistent_character_is_404(client):
    assert client.get("/characters/999999/public-home").status_code == 404


def test_public_but_unpublished_is_404_anonymously(client, db_session):
    """PUBLIC visibility alone does not publish a Home."""
    token = get_auth_token(client, email="home-off@test.com", username="homeoff")
    cid = _create_character(client, token, "Summer")
    assert _row(db_session, cid).public_home_enabled is False

    assert client.get(f"/characters/{cid}/public-home").status_code == 404


def test_published_home_is_returned_anonymously(client, published):
    resp = client.get(f"/characters/{published['character_id']}/public-home")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == published["character_id"]
    assert resp.json()["name"] == "Summer"


def test_private_with_the_flag_set_is_still_404(client, db_session):
    """The regression that matters: permission never overrides privacy."""
    token = get_auth_token(client, email="home-priv@test.com", username="homepriv")
    cid = _create_character(client, token, "Hidden", visibility="private")
    _publish(db_session, cid)

    row = _row(db_session, cid)
    assert row.public_home_enabled is True
    assert row.visibility == VisibilityEnum.PRIVATE

    assert client.get(f"/characters/{cid}/public-home").status_code == 404


def test_friends_with_the_flag_set_is_404(client, db_session):
    """Every non-PUBLIC visibility, not just PRIVATE."""
    token = get_auth_token(client, email="home-fr@test.com", username="homefr")
    cid = _create_character(client, token, "Circle", visibility="friends")
    _publish(db_session, cid)

    assert _row(db_session, cid).visibility == VisibilityEnum.FRIENDS
    assert client.get(f"/characters/{cid}/public-home").status_code == 404


def test_unpublished_and_nonexistent_are_indistinguishable(client, db_session):
    """Same status AND same body — the whole point of using 404 over 403."""
    token = get_auth_token(client, email="home-ind@test.com", username="homeind")
    cid = _create_character(client, token, "Hidden", visibility="private")
    _publish(db_session, cid)

    hidden = client.get(f"/characters/{cid}/public-home")
    missing = client.get("/characters/999999/public-home")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_revoking_the_grant_closes_the_home_again(client, db_session, published):
    cid = published["character_id"]
    assert client.get(f"/characters/{cid}/public-home").status_code == 200

    _publish(db_session, cid, enabled=False)
    assert client.get(f"/characters/{cid}/public-home").status_code == 404


def test_endpoint_needs_no_token(client, published):
    """No Authorization header, and none demanded — not a 401/403 anywhere."""
    resp = client.get(f"/characters/{published['character_id']}/public-home")
    assert resp.status_code == 200, resp.text
    assert "WWW-Authenticate" not in resp.headers


# ── B. The public projection ──────────────────────────────────────────────────

def test_response_contains_exactly_the_allowlisted_fields(client, published):
    resp = client.get(f"/characters/{published['character_id']}/public-home")
    assert set(resp.json().keys()) == PUBLIC_HOME_FIELDS


def test_age_is_absent(client, published):
    """Set on the character, and still not on the wire."""
    resp = client.get(f"/characters/{published['character_id']}/public-home")
    assert "age" not in resp.json()


def test_owner_and_internal_fields_are_absent(client, db_session, published):
    """Ownership, publication mechanics, canon and generation metadata.

    Asserted by name as well as by the exact key set above, so the failure
    message names the field that leaked.
    """
    cid = published["character_id"]
    row = _row(db_session, cid)
    row.identity_spec_json = '{"secret": true}'
    row.identity_anchor_json = '{"anchor": true}'
    row.body_canon_json = '{"marks": []}'
    db_session.commit()

    body = client.get(f"/characters/{cid}/public-home").json()
    for field in (
        "owner_id", "owner_username", "owner", "email",
        "public_home_enabled", "visibility",
        "visual_locked", "identity_spec_json", "identity_spec_version",
        "identity_anchor_json", "body_canon_json", "identity_health",
        "has_identity_canon", "portrait_url",
        "created_at", "updated_at",
    ):
        assert field not in body, f"{field} leaked to the anonymous profile"

    # And nothing anywhere in the payload carries the owner's account.
    assert "home-own@test.com" not in json.dumps(body)


def test_identity_and_presentation_fields_are_carried(client, db_session, published):
    """The allowlist is not empty by accident — the real values come through."""
    cid = published["character_id"]
    row = _row(db_session, cid)
    row.alias = "The Ember"
    row.role = "assassin"
    row.era = "medieval"
    row.short_bio = "A tagline."
    row.long_bio = "A much longer description."
    row.tags = "fire,knives"
    row.cover_position_x = 0.25
    row.cover_position_y = 0.75
    row.cover_scale = 1.5
    row.avatar_position_x = 0.4
    row.avatar_position_y = 0.6
    row.avatar_scale = 1.2
    db_session.commit()

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["alias"] == "The Ember"
    assert body["role"] == "assassin"
    assert body["era"] == "medieval"
    assert body["species"] == "human"
    assert body["short_bio"] == "A tagline."
    assert body["long_bio"] == "A much longer description."
    assert body["tags"] == "fire,knives"
    assert body["cover_position_x"] == 0.25
    assert body["cover_position_y"] == 0.75
    assert body["cover_scale"] == 1.5
    assert body["avatar_position_x"] == 0.4
    assert body["avatar_position_y"] == 0.6
    assert body["avatar_scale"] == 1.2


# ── C. Avatar / cover resolution ──────────────────────────────────────────────

def test_resolvable_safe_avatar_and_cover_are_returned(client, db_session, published):
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(db_session, cid, uid, file_path="static/generated/safe-avatar.png")
    _insert_image(db_session, cid, uid, file_path="static/generated/safe-cover.png")
    _set_media(
        db_session, cid,
        avatar_url="/static/generated/safe-avatar.png",
        cover_url="/static/generated/safe-cover.png",
    )

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["avatar_url"] == "/static/generated/safe-avatar.png"
    assert body["cover_url"] == "/static/generated/safe-cover.png"


def test_resolvable_unsafe_avatar_becomes_null(client, db_session, published):
    """Adult Studio provenance behind the avatar pointer — suppressed on read.

    The write guards added in Step 1.5 stop this being created today; the
    pointer can still be historical, so the read path must not trust it.
    """
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(
        db_session, cid, uid, file_path="static/generated/adult-avatar.png",
        provider="replicate_nsfw", metadata={"adult_studio": True},
    )
    _set_media(db_session, cid, avatar_url="/static/generated/adult-avatar.png")

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["avatar_url"] is None
    # The character's own row is untouched — presentation, never possession.
    assert _row(db_session, cid).avatar_url == "/static/generated/adult-avatar.png"


def test_resolvable_unsafe_cover_becomes_null(client, db_session, published):
    """Editor Studio provenance behind the cover pointer — the dev 1787 shape."""
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(
        db_session, cid, uid, file_path="static/generated/editor-cover.png",
        kind=ImageKindEnum.SCENE_ONLY, provider="gpt-image",
        metadata={"editor_generated": True, "provider": "gpt-image"},
    )
    _set_media(db_session, cid, cover_url="/static/generated/editor-cover.png")

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["cover_url"] is None
    assert _row(db_session, cid).cover_url == "/static/generated/editor-cover.png"


def test_suppressed_media_keeps_its_positioning_fields(client, db_session, published):
    """Only the URL is withheld; the frame the Home renders in is unchanged."""
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(
        db_session, cid, uid, file_path="static/generated/adult-cover.png",
        provider="replicate_nsfw", metadata={"adult_studio": True},
    )
    _set_media(db_session, cid, cover_url="/static/generated/adult-cover.png")

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["cover_url"] is None
    assert body["cover_position_x"] == 0.5
    assert body["cover_position_y"] == 0.5


def test_unresolvable_historical_media_is_returned_unchanged(client, db_session, published):
    """The temporary V1 exception, and the reason it exists.

    ``POST /characters/{id}/avatar`` crops its source and saves a NEW file with
    no image row behind it, so most historical avatars resolve to nothing.
    Blanking them would suppress a large number of legitimate portraits, and
    doing so buys nothing while no Home is enabled. Pinned explicitly so the
    day this rule tightens, it tightens deliberately.
    """
    cid = published["character_id"]
    _set_media(
        db_session, cid,
        avatar_url="/static/generated/deadbeefdeadbeef.png",
        cover_url="https://cdn.example.test/legacy/cover.png",
    )

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["avatar_url"] == "/static/generated/deadbeefdeadbeef.png"
    assert body["cover_url"] == "https://cdn.example.test/legacy/cover.png"


def test_media_absent_on_the_character_stays_null(client, published):
    body = client.get(f"/characters/{published['character_id']}/public-home").json()
    assert body["avatar_url"] is None
    assert body["cover_url"] is None


def test_alternate_file_path_spellings_still_resolve(client, db_session, published):
    """``file_path_to_url`` is many-to-one, so the inverse must enumerate.

    A row stored as ``generated/x.png`` serves the same URL as one stored as
    ``static/generated/x.png``. If resolution only tried one spelling, an
    unsafe image stored in the other would be published.
    """
    cid, uid = published["character_id"], published["owner_id"]
    _insert_image(
        db_session, cid, uid, file_path="generated/spelling.png",
        provider="replicate_nsfw", metadata={"adult_studio": True},
    )
    _set_media(db_session, cid, avatar_url="/static/generated/spelling.png")

    assert client.get(f"/characters/{cid}/public-home").json()["avatar_url"] is None


def test_unsafe_user_image_behind_a_cover_is_also_caught(client, db_session, published):
    """Covers may be set from a user image, so both tables are searched."""
    from app.models.user_image import UserImage

    cid = published["character_id"]
    db_session.add(UserImage(
        user_id=published["owner_id"],
        kind="profile_cover",
        status="active",
        provider="replicate_nsfw",
        metadata_json={"adult_studio": True},
        file_path="static/generated/user-cover.png",
    ))
    db_session.commit()
    _set_media(db_session, cid, cover_url="/static/generated/user-cover.png")

    assert client.get(f"/characters/{cid}/public-home").json()["cover_url"] is None


# ── D. The anonymous gallery ──────────────────────────────────────────────────
#
# Step 6.6 moved this surface to ``GET /characters/{id}/public-home/images`` and
# made the old route authenticated-only; the publication rule these tests pin is
# unchanged, and the projection itself is covered in
# ``test_character_home_gallery_projection.py``.

def test_anonymous_gallery_is_404_when_home_is_disabled(client, db_session):
    """The bypass Step 4 closes: PUBLIC alone used to be enough here."""
    token = get_auth_token(client, email="gal-off@test.com", username="galoff")
    cid = _create_character(client, token, "Summer")
    uid = _user_id(db_session, "gal-off@test.com")
    _insert_image(db_session, cid, uid, file_path="static/generated/g1.png")
    assert _row(db_session, cid).public_home_enabled is False

    assert client.get(f"/characters/{cid}/public-home/images").status_code == 404


def test_anonymous_gallery_works_when_home_is_publishable(client, db_session, published):
    """A published Home serves the images the creator selected (Step 6.5)."""
    cid, uid = published["character_id"], published["owner_id"]
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/g2.png",
                             selected=True)

    resp = client.get(f"/characters/{cid}/public-home/images")
    assert resp.status_code == 200, resp.text
    assert [i["id"] for i in resp.json()] == [image_id]


def test_anonymous_gallery_still_filters_unsafe_media(client, db_session, published):
    """The publication gate is added ON TOP of Step 1/1.5, not instead of it.

    Every row here is selected, so the exclusions are the safety rule's doing
    and not the curation layer's — creator selection cannot reach past it.
    """
    cid, uid = published["character_id"], published["owner_id"]
    clean = _insert_image(db_session, cid, uid, file_path="static/generated/g3.png",
                          selected=True)
    _insert_image(
        db_session, cid, uid, file_path="static/generated/g4.png",
        provider="replicate_nsfw", metadata={"adult_studio": True}, selected=True,
    )
    _insert_image(
        db_session, cid, uid, file_path="static/generated/g5.png",
        kind=ImageKindEnum.ANCHOR_FRONT, selected=True,
    )

    resp = client.get(f"/characters/{cid}/public-home/images")
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()} == {clean}


def test_anonymous_gallery_hides_private_characters_as_404(client, db_session):
    """Previously 403, which confirmed the character existed."""
    token = get_auth_token(client, email="gal-priv@test.com", username="galpriv")
    cid = _create_character(client, token, "Hidden", visibility="private")
    _publish(db_session, cid)

    assert client.get(f"/characters/{cid}/public-home/images").status_code == 404


def test_the_old_images_route_is_no_longer_anonymous(client, db_session, published):
    """Step 6.6: the second public gallery was retired, not kept as an alias."""
    cid = published["character_id"]
    assert client.get(f"/characters/{cid}/public-home/images").status_code == 200
    assert client.get(f"/characters/{cid}/images").status_code in (401, 403)


# ── E. Authenticated behaviour is unchanged ───────────────────────────────────

def test_authenticated_stranger_gallery_unchanged_when_home_disabled(client, db_session):
    """A signed-in member reads a PUBLIC character's gallery as before."""
    owner = get_auth_token(client, email="auth-own@test.com", username="authown")
    cid = _create_character(client, owner, "Summer")
    uid = _user_id(db_session, "auth-own@test.com")
    image_id = _insert_image(db_session, cid, uid, file_path="static/generated/a1.png")
    assert _row(db_session, cid).public_home_enabled is False

    stranger = get_auth_token(client, email="auth-str@test.com", username="authstr")
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(stranger))
    assert resp.status_code == 200, resp.text
    assert [i["id"] for i in resp.json()] == [image_id]


def test_owner_gallery_unchanged_when_home_disabled(client, db_session):
    """Including on a PRIVATE character, and including the working set."""
    owner = get_auth_token(client, email="auth-own2@test.com", username="authown2")
    cid = _create_character(client, owner, "Hidden", visibility="private")
    uid = _user_id(db_session, "auth-own2@test.com")
    gallery_piece = _insert_image(db_session, cid, uid, file_path="static/generated/a2.png")
    anchor = _insert_image(
        db_session, cid, uid, file_path="static/generated/a3.png",
        kind=ImageKindEnum.ANCHOR_FRONT,
    )

    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()} == {gallery_piece, anchor}


def test_authenticated_stranger_still_gets_403_on_a_private_gallery(client, db_session):
    """The signed-in refusal keeps its old status code."""
    owner = get_auth_token(client, email="auth-own3@test.com", username="authown3")
    cid = _create_character(client, owner, "Hidden", visibility="private")
    _publish(db_session, cid)

    stranger = get_auth_token(client, email="auth-str3@test.com", username="authstr3")
    resp = client.get(f"/characters/{cid}/images", headers=auth_headers(stranger))
    assert resp.status_code == 403, resp.text


def test_authenticated_get_character_is_unchanged(client, db_session, published):
    """``GET /characters/{id}`` keeps its own rule, schema and 401.

    It is NOT the public projection: it still requires a token, still carries
    the internal fields, and is still ungated by ``public_home_enabled``.
    """
    cid = published["character_id"]

    # Still requires authentication.
    assert client.get(f"/characters/{cid}").status_code in (401, 403)

    # Owner sees the full internal shape, age and all.
    owner_body = client.get(
        f"/characters/{cid}", headers=auth_headers(published["token"])
    ).json()
    assert owner_body["age"] == "27"
    assert owner_body["owner_id"] == published["owner_id"]
    assert "public_home_enabled" not in owner_body

    # And an unpublished PUBLIC character is still readable to a stranger.
    other = get_auth_token(client, email="auth-str4@test.com", username="authstr4")
    off = _create_character(client, other, "Autumn")
    third = get_auth_token(client, email="auth-str5@test.com", username="authstr5")
    assert client.get(
        f"/characters/{off}", headers=auth_headers(third)
    ).status_code == 200


def test_public_home_route_is_also_mounted_under_api(client, published):
    """Both mounts, like every other router in main.py."""
    resp = client.get(f"/api/characters/{published['character_id']}/public-home")
    assert resp.status_code == 200, resp.text
