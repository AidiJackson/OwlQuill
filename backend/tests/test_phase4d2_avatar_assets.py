"""Phase 4D2 — the avatar crops become real assets, and cannot launder.

Both avatar routes crop locally and used to call ``save_image()``: new bytes
under a fresh uuid, and no row at all. That is where the rowless account avatars
and the five rowless character avatars in the bucket came from, and it is why
``resolve_public_media_url`` — which now suppresses any url it cannot resolve —
had nothing to judge and withheld locally-cropped avatars from the Character
Home, from posts and from comments.

4D2 gives the crop a row. That fixes the suppression AND creates a hazard in the
same step, because a row that resolves is a row the provenance predicate will
answer for: a crop written with ``provider=None`` and fresh metadata reads as
SAFE whatever it was cropped from. These tests are mostly about that hazard.

Route-level on purpose. The unit suite
(``test_phase4d2_writer_migration.py``) pins the primitive; what has to be
proven here is that the two routes actually reach it, that
``Character.avatar_url`` and ``User.avatar_url`` still hold exactly what their
readers expect, and that the end-to-end laundering path — crop an unsafe image
into an account avatar, then offer the clean crop as a character avatar — is
closed.
"""
import io
import uuid
from pathlib import Path

import pytest
from PIL import Image

from app.models.character import Character
from app.models.character_image import (
    SAFETY_POLICY_VERSION_NONE,
    SAFETY_STATE_UNREVIEWED,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User
from app.models.user_image import UserImage
from app.schemas.character_image import (
    PUBLIC_SURFACE_UNSAFE_MESSAGE,
    is_public_surface_safe,
)
from app.services.character_home_media import resolve_public_media_url
from tests.conftest import auth_headers, ensure_character, get_auth_token

#: Where the avatar routes read their SOURCE bytes from. They resolve the stored
#: path against the backend root themselves rather than through the storage
#: layer, so the session-wide ``generated_media_dir`` redirect (which repoints
#: writes) does not cover reads here — the source file has to be real.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_SOURCE_DIR = _BACKEND_ROOT / "static" / "generated"


def _png(colour=(80, 120, 200), size=(640, 480)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def source_file():
    """A real image on disk where the avatar routes look, removed afterwards."""
    written: list[Path] = []

    def _write() -> str:
        _SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        path = _SOURCE_DIR / f"p4d2-{uuid.uuid4().hex}.png"
        path.write_bytes(_png())
        written.append(path)
        return f"static/generated/{path.name}"

    yield _write
    for path in written:
        path.unlink(missing_ok=True)


def _character_image(db_session, *, user_id, character_id, file_path,
                     provider="fal", metadata=None):
    img = CharacterImage(
        user_id=user_id,
        character_id=character_id,
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider,
        prompt_summary="fixture source",
        metadata_json=metadata if metadata is not None else {"library": True},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


def _crop_rows(db_session):
    return (
        db_session.query(CharacterImage)
        .filter(CharacterImage.kind == ImageKindEnum.UPLOADED)
        .all()
    )


def _the_crop(db_session):
    crops = [r for r in _crop_rows(db_session)
             if (r.metadata_json or {}).get("avatar_crop")]
    assert len(crops) == 1, f"expected exactly one avatar crop, got {len(crops)}"
    return crops[0]


# ── character avatar ─────────────────────────────────────────────────────────


def test_character_avatar_crop_is_a_real_owned_asset(client, db_session, source_file):
    token = get_auth_token(client, "charav@4d2.example.com", "charav4d2")
    character_id = ensure_character(client, token, "Avatar Character")
    user = db_session.query(User).filter(User.email == "charav@4d2.example.com").first()
    source = _character_image(
        db_session, user_id=user.id, character_id=character_id,
        file_path=source_file(),
    )

    resp = client.post(
        f"/characters/{character_id}/avatar",
        json={"image_type": "character", "image_id": source.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    crop = _the_crop(db_session)
    assert crop.user_id == user.id
    assert crop.character_id == character_id
    assert crop.status == ImageStatusEnum.ACTIVE
    assert crop.visibility == ImageVisibilityEnum.PRIVATE
    assert crop.storage_key, "the crop must carry a storage key"
    assert crop.safety_state == SAFETY_STATE_UNREVIEWED
    assert crop.safety_policy_version == SAFETY_POLICY_VERSION_NONE
    # A crop of ONE image — the lineage column can name it, so it does.
    assert crop.derived_from_image_id == source.id
    assert crop.metadata_json["source"] == "character_avatar_crop"


def test_character_avatar_url_is_unchanged_in_shape_and_now_resolves(
    client, db_session, source_file
):
    """Compatibility AND the point of the migration, in one assertion pair.

    ``Character.avatar_url`` keeps the exact spelling every existing reader
    expects — ``file_path_to_url`` of the stored path — and that string now
    inverts back to a row, so the shared-surface resolver returns it instead of
    suppressing it for want of provenance.
    """
    token = get_auth_token(client, "charurl@4d2.example.com", "charurl4d2")
    character_id = ensure_character(client, token, "Resolvable Avatar")
    user = db_session.query(User).filter(User.email == "charurl@4d2.example.com").first()
    source = _character_image(
        db_session, user_id=user.id, character_id=character_id,
        file_path=source_file(),
    )

    resp = client.post(
        f"/characters/{character_id}/avatar",
        json={"image_type": "character", "image_id": source.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    avatar_url = resp.json()["avatar_url"]

    character = db_session.get(Character, character_id)
    db_session.refresh(character)
    assert character.avatar_url == avatar_url
    assert avatar_url.startswith("/static/generated/")

    crop = _the_crop(db_session)
    assert Path(crop.file_path).name == Path(avatar_url).name
    assert resolve_public_media_url(db_session, avatar_url) == avatar_url


def test_a_remote_source_still_points_straight_at_its_own_row(client, db_session):
    """The R2 branch is NOT a crop and 4D2 does not make it one.

    When the source is already an absolute url the route reuses it verbatim: no
    new bytes, nothing derived, and the avatar resolves to the SOURCE row. Only
    the local crop needed an asset of its own.
    """
    token = get_auth_token(client, "remote@4d2.example.com", "remote4d2")
    character_id = ensure_character(client, token, "Remote Avatar")
    user = db_session.query(User).filter(User.email == "remote@4d2.example.com").first()
    source = _character_image(
        db_session, user_id=user.id, character_id=character_id,
        file_path="https://cdn.example.test/generated/remote.png",
    )

    resp = client.post(
        f"/characters/{character_id}/avatar",
        json={"image_type": "character", "image_id": source.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"] == source.file_path
    assert _crop_rows(db_session) == []


# ── account avatar ───────────────────────────────────────────────────────────


def test_account_avatar_crop_is_owned_by_the_account_and_no_character(
    client, db_session, source_file
):
    """The case Phase 4C made representable, finally written by a real route.

    Every account avatar in the bucket today is rowless. This one has an owner,
    a storage key and no character association — filing an account sigil against
    whichever character happened to supply the pixels would misfile it into that
    character's scoped routes.
    """
    token = get_auth_token(client, "acctav@4d2.example.com", "acctav4d2")
    character_id = ensure_character(client, token, "Source Character")
    user = db_session.query(User).filter(User.email == "acctav@4d2.example.com").first()
    source = _character_image(
        db_session, user_id=user.id, character_id=character_id,
        file_path=source_file(),
    )

    resp = client.post(
        "/users/me/avatar",
        json={"image_type": "character", "image_id": source.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    crop = _the_crop(db_session)
    assert crop.user_id == user.id
    assert crop.character_id is None
    assert crop.storage_key
    assert crop.safety_state == SAFETY_STATE_UNREVIEWED
    assert crop.derived_from_image_id == source.id
    assert crop.metadata_json["source"] == "account_avatar_crop"

    db_session.refresh(user)
    assert user.avatar_url == resp.json()["avatar_url"]
    assert resolve_public_media_url(db_session, user.avatar_url) == user.avatar_url


def test_a_user_image_source_records_legacy_lineage_in_metadata(
    client, db_session, source_file
):
    """``UserImage`` is not migrated in 4D2, and is not pretended into the FK.

    ``derived_from_image_id`` references ``character_images``. A crop of a
    ``UserImage`` has a real source that column cannot name, so the record goes
    in metadata — and no FK to ``user_images`` is added to make the two cases
    look alike.
    """
    token = get_auth_token(client, "uimg@4d2.example.com", "uimg4d2")
    ensure_character(client, token, "Irrelevant Character")
    user = db_session.query(User).filter(User.email == "uimg@4d2.example.com").first()
    source = UserImage(
        user_id=user.id, kind="profile_cover", status="active", provider="stub",
        metadata_json={"is_temp": False}, file_path=source_file(),
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    resp = client.post(
        "/users/me/avatar",
        json={"image_type": "user", "image_id": source.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    crop = _the_crop(db_session)
    assert crop.derived_from_image_id is None
    assert crop.metadata_json["derived_from"] == {
        "table": "user_images", "id": source.id,
    }


def test_a_data_uri_avatar_is_left_alone(client, db_session):
    """The account sigils are not persisted bytes and must not be made into any.

    ``PATCH /users/me`` stores a ``data:image/svg+xml,...`` string generated in
    the browser. There is no object to own and nothing for a lifecycle or a
    safety state to describe; decoding and storing one purely so that every
    ``avatar_url`` looked alike would manufacture an asset to satisfy a
    uniformity nobody asked for.
    """
    token = get_auth_token(client, "sigil@4d2.example.com", "sigil4d2")
    sigil = "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%2F%3E"

    resp = client.patch("/users/me", json={"avatar_url": sigil},
                        headers=auth_headers(token))
    assert resp.status_code == 200, resp.text

    user = db_session.query(User).filter(User.email == "sigil@4d2.example.com").first()
    db_session.refresh(user)
    assert user.avatar_url == sigil
    assert db_session.query(CharacterImage).count() == 0


# ── the laundering path, end to end ──────────────────────────────────────────


def test_cropping_an_unsafe_image_into_an_account_avatar_does_not_launder_it(
    client, db_session, source_file
):
    """The complete path 4D2 would have opened, proven closed.

    ``POST /users/me/avatar`` has never applied ``is_public_surface_safe`` to
    its source — it did not have to, because its crop was rowless and therefore
    unresolvable everywhere. Once the crop is a real ``CharacterImage`` the
    owner can select, an Adult Studio image could be laundered in two steps:
    crop it into an account avatar, then offer the clean crop to
    ``POST /characters/{id}/avatar``, which DOES check provenance and would have
    refused the original.

    The crop inherits its source's provider and markers, so step two fails on
    the crop exactly as it would have on the source.
    """
    token = get_auth_token(client, "launder@4d2.example.com", "launder4d2")
    character_id = ensure_character(client, token, "Launder Character")
    user = db_session.query(User).filter(User.email == "launder@4d2.example.com").first()
    unsafe = _character_image(
        db_session, user_id=user.id, character_id=character_id,
        file_path=source_file(), provider="replicate_nsfw",
        metadata={"library": True, "adult_studio": True,
                  "provider": "replicate_nsfw"},
    )
    assert not is_public_surface_safe(unsafe)

    # Step one succeeds — this route has never gated on provenance, and 4D2
    # deliberately does not add a gate it did not have.
    resp = client.post(
        "/users/me/avatar",
        json={"image_type": "character", "image_id": unsafe.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    crop = _the_crop(db_session)
    assert crop.provider == "replicate_nsfw"
    assert crop.metadata_json["adult_studio"] is True
    assert not is_public_surface_safe(crop)
    assert resolve_public_media_url(db_session, crop.file_path) is None

    # Step two: the crop is refused exactly as its source would have been.
    resp = client.post(
        f"/characters/{character_id}/avatar",
        json={"image_type": "character", "image_id": crop.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == PUBLIC_SURFACE_UNSAFE_MESSAGE


def test_the_character_avatar_route_still_refuses_an_unsafe_source_outright(
    client, db_session, source_file
):
    """Unchanged by 4D2, and asserted so the crop path cannot become a bypass."""
    token = get_auth_token(client, "refuse@4d2.example.com", "refuse4d2")
    character_id = ensure_character(client, token, "Refusing Character")
    user = db_session.query(User).filter(User.email == "refuse@4d2.example.com").first()
    unsafe = _character_image(
        db_session, user_id=user.id, character_id=character_id,
        file_path=source_file(), provider="self_hosted",
        metadata={"editor_generated": True},
    )

    resp = client.post(
        f"/characters/{character_id}/avatar",
        json={"image_type": "character", "image_id": unsafe.id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert _crop_rows(db_session) == []


def test_an_avatar_crop_is_not_gallery_or_post_material(client, db_session, source_file):
    """A crop must not reappear as if it were separate work.

    The kind it is written with is absent from ``PUBLIC_GALLERY_KINDS`` and from
    ``POST_ATTACHABLE_IMAGE_KINDS``, so the crop cannot be selected onto the
    Character Home gallery or attached to a post.
    """
    from app.models.character_image import POST_ATTACHABLE_IMAGE_KINDS
    from app.schemas.character_image import (
        PUBLIC_GALLERY_KINDS,
        is_public_gallery_image,
    )

    token = get_auth_token(client, "notgal@4d2.example.com", "notgal4d2")
    character_id = ensure_character(client, token, "Not Gallery")
    user = db_session.query(User).filter(User.email == "notgal@4d2.example.com").first()
    source = _character_image(
        db_session, user_id=user.id, character_id=character_id,
        file_path=source_file(),
    )
    client.post(
        f"/characters/{character_id}/avatar",
        json={"image_type": "character", "image_id": source.id},
        headers=auth_headers(token),
    )

    crop = _the_crop(db_session)
    assert crop.kind not in PUBLIC_GALLERY_KINDS
    assert crop.kind.value not in POST_ATTACHABLE_IMAGE_KINDS
    assert not is_public_gallery_image(crop)
