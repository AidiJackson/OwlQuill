"""Public gallery safety — studio imagery must never reach an anonymous viewer.

Adult Studio output (explicit imagery) and Editor Studio output (uncensored
transform pod, launch-ineligible pending review) are both excluded from public
character galleries, while ordinary public media and the owner's own full view
are left exactly as they were.

The regression this file exists for is real, not hypothetical. An audit of the
dev database found one row already being served to unauthenticated callers:

    id=1787  character=60 (PUBLIC)  kind=scene_only  status=active
    provider='gpt-image'  metadata_json.editor_generated=true

Note the provider. Sixteen of the seventeen editor rows in that database were
'self_hosted' and all were archived and therefore already harmless; the single
row that actually leaked was 'gpt-image'. A rule keyed on the provider alone
would have excluded sixteen dead rows and published the live one. That shape is
pinned below in `test_dev_image_1787_shape_is_excluded`.
"""
import pytest

from app.models.character_image import ImageKindEnum, ImageStatusEnum
from app.schemas.character_image import is_public_gallery_image
from tests.conftest import get_auth_token, auth_headers


class _FakeImage:
    """Minimal stand-in carrying only what the eligibility rule reads."""

    def __init__(self, kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
                 provider="fal", metadata_json=None):
        self.kind = kind
        self.status = status
        self.provider = provider
        self.metadata_json = metadata_json if metadata_json is not None else {}


# ── Adult Studio ──────────────────────────────────────────────────────────

def test_adult_studio_active_generated_is_excluded():
    """The shape the founder replicate-test route writes: GENERATED + ACTIVE."""
    assert not is_public_gallery_image(_FakeImage(
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        provider="replicate_nsfw",
        metadata_json={"adult_studio": True, "provider": "replicate_nsfw",
                       "experimental": True},
    ))


def test_adult_studio_excluded_on_provider_alone_without_metadata_marker():
    """The provider column stands on its own if the metadata marker is gone."""
    assert not is_public_gallery_image(_FakeImage(
        kind=ImageKindEnum.GENERATED, provider="replicate_nsfw", metadata_json={},
    ))


def test_adult_studio_excluded_on_metadata_marker_alone_without_provider():
    """And the metadata marker stands on its own if the column is empty."""
    assert not is_public_gallery_image(_FakeImage(
        kind=ImageKindEnum.GENERATED, provider=None,
        metadata_json={"adult_studio": True},
    ))


# ── Editor Studio ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("provider", ["gpt-image", "grok", "self_hosted", None])
def test_editor_generated_is_excluded_regardless_of_provider(provider):
    """editor_generated is the primary identifier — every provider it uses."""
    assert not is_public_gallery_image(_FakeImage(
        kind=ImageKindEnum.SCENE_ONLY, provider=provider,
        metadata_json={"editor_generated": True, "provider": provider},
    ))


def test_self_hosted_excluded_as_defence_in_depth_without_the_flag():
    """provider='self_hosted' alone excludes, even with no editor flag."""
    assert not is_public_gallery_image(_FakeImage(
        kind=ImageKindEnum.SCENE_ONLY, provider="self_hosted", metadata_json={},
    ))


def test_non_public_provider_inside_metadata_is_honoured():
    """A path that records the provider only in metadata is still caught."""
    assert not is_public_gallery_image(_FakeImage(
        kind=ImageKindEnum.SCENE_ONLY, provider=None,
        metadata_json={"provider": "self_hosted"},
    ))


def test_dev_image_1787_shape_is_excluded():
    """The exact shape proven to be leaking in the dev database."""
    assert not is_public_gallery_image(_FakeImage(
        kind=ImageKindEnum.SCENE_ONLY,
        status=ImageStatusEnum.ACTIVE,
        provider="gpt-image",
        metadata_json={"editor_generated": True, "editor_version": "e1",
                       "provider": "gpt-image", "editor_mode": "edit"},
    ))


# ── Ordinary media stays eligible (no over-blocking) ──────────────────────

@pytest.mark.parametrize("kind", [
    ImageKindEnum.GENERATED, ImageKindEnum.COVER, ImageKindEnum.SCENE_ONLY,
])
def test_ordinary_media_remains_eligible(kind):
    """The change must not empty existing galleries."""
    assert is_public_gallery_image(_FakeImage(
        kind=kind, status=ImageStatusEnum.ACTIVE, provider="fal",
        metadata_json={"library": True, "prompt": "a quiet room"},
    ))


def test_ordinary_media_with_no_metadata_remains_eligible():
    assert is_public_gallery_image(_FakeImage(metadata_json=None))


# ── Pre-existing exclusions still hold ────────────────────────────────────

def test_temp_pack_preview_still_excluded():
    assert not is_public_gallery_image(_FakeImage(metadata_json={"is_temp": True}))


def test_archived_still_excluded():
    assert not is_public_gallery_image(_FakeImage(status=ImageStatusEnum.ARCHIVED))


@pytest.mark.parametrize("kind", [
    ImageKindEnum.UPLOADED, ImageKindEnum.IDENTITY_SKETCH,
    ImageKindEnum.ANCHOR_FRONT, ImageKindEnum.IDENTITY_FACE_REF,
])
def test_non_gallery_kinds_still_excluded(kind):
    assert not is_public_gallery_image(_FakeImage(kind=kind))


# ── Route level: anonymous vs owner ───────────────────────────────────────

def _create_character(client, token, name="Summer", visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _insert_image(db_session, character_id, user_id, *, kind, provider, metadata):
    from app.models.character_image import (
        CharacterImage, ImageStatusEnum as S, ImageVisibilityEnum,
    )
    img = CharacterImage(
        character_id=character_id,
        user_id=user_id,
        kind=kind,
        status=S.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        # Step 6.5: every fixture row is SELECTED for the Character Home
        # gallery, so what these tests exercise is the safety rule alone — and
        # each exclusion below is now also proof that a creator cannot select
        # past it.
        public_gallery_enabled=True,
        provider=provider,
        prompt_summary="fixture",
        metadata_json=metadata,
        file_path=f"static/generated/fixture-{kind.value}-{provider}.png",
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img.id


@pytest.fixture()
def gallery(client, db_session):
    """A PUBLIC character holding one clean image and three ineligible ones.

    Its Character Home is published, because since Step 4 that is what makes
    the gallery reachable anonymously at all. These tests are about WHICH
    images an anonymous viewer gets, not whether they get in — the gate itself
    is pinned in test_character_home_read_api.py.
    """
    from app.models.character import Character
    from app.models.user import User

    token = get_auth_token(client, email="gal-owner@test.com", username="galowner")
    owner_id = db_session.query(User).filter(
        User.email == "gal-owner@test.com").first().id
    character_id = _create_character(client, token)
    db_session.query(Character).filter(Character.id == character_id).first(
        ).public_home_enabled = True
    db_session.commit()

    clean = _insert_image(
        db_session, character_id, owner_id,
        kind=ImageKindEnum.GENERATED, provider="fal",
        metadata={"library": True},
    )
    adult = _insert_image(
        db_session, character_id, owner_id,
        kind=ImageKindEnum.GENERATED, provider="replicate_nsfw",
        metadata={"adult_studio": True, "provider": "replicate_nsfw"},
    )
    # The dev 1787 shape.
    editor = _insert_image(
        db_session, character_id, owner_id,
        kind=ImageKindEnum.SCENE_ONLY, provider="gpt-image",
        metadata={"editor_generated": True, "provider": "gpt-image"},
    )
    pod = _insert_image(
        db_session, character_id, owner_id,
        kind=ImageKindEnum.SCENE_ONLY, provider="self_hosted",
        metadata={"editor_generated": True, "provider": "self_hosted"},
    )
    return {
        "token": token, "character_id": character_id,
        "clean": clean, "adult": adult, "editor": editor, "pod": pod,
    }


def test_anonymous_gallery_excludes_studio_imagery(client, gallery):
    """The headline contract: no studio imagery reaches an anonymous viewer.

    Step 6.6 moved the anonymous gallery to
    ``GET /characters/{id}/public-home/images``; the old route is authenticated
    only. The rule under test is unchanged — every fixture row is selected, so
    what excludes these images is media safety alone.
    """
    resp = client.get(f"/characters/{gallery['character_id']}/public-home/images")
    assert resp.status_code == 200, resp.text
    returned = {item["id"] for item in resp.json()}

    assert gallery["clean"] in returned, "ordinary public media must still show"
    for key in ("adult", "editor", "pod"):
        assert gallery[key] not in returned, f"{key} image leaked to anonymous viewer"
    assert returned == {gallery["clean"]}


def test_anonymous_gallery_never_exposes_provider_or_metadata(client, gallery):
    """The public schema stays narrow — the exclusion signals are server-side."""
    resp = client.get(f"/characters/{gallery['character_id']}/public-home/images")
    for item in resp.json():
        for leaked in ("provider", "metadata_json", "prompt_summary", "seed",
                       "user_id", "status", "visibility"):
            assert leaked not in item


def test_owner_still_sees_their_own_studio_imagery(client, gallery):
    """Founder access is unchanged — this fix narrows the PUBLIC view only."""
    resp = client.get(
        f"/characters/{gallery['character_id']}/images",
        headers=auth_headers(gallery["token"]),
    )
    assert resp.status_code == 200, resp.text
    returned = {item["id"] for item in resp.json()}
    for key in ("clean", "adult", "editor", "pod"):
        assert gallery[key] in returned, f"owner lost access to their {key} image"


def test_authenticated_non_owner_gets_the_public_view(client, gallery, db_session):
    """A signed-in stranger is public, not owner — same exclusions apply."""
    other = get_auth_token(client, email="gal-other@test.com", username="galother")
    resp = client.get(
        f"/characters/{gallery['character_id']}/images",
        headers=auth_headers(other),
    )
    assert resp.status_code == 200, resp.text
    assert {item["id"] for item in resp.json()} == {gallery["clean"]}
