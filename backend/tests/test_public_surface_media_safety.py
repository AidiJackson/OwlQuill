"""Public surface media safety — the rule shared by every anonymous presentation.

Step 1 closed the public gallery. It then turned out the gallery was only one of
three ways an image reaches an anonymous viewer:

    1. the public gallery              — closed in Step 1
    2. the character's avatar / cover  — closed here
    3. a post's attached image         — anonymous timeline does not exist yet

Paths 2 and 3 never consulted the gallery rule, so guarding only the gallery left
a founder free to promote Adult Studio output to a character's avatar and have it
render on every public surface the character appears on.

These tests pin the shared predicate and the avatar/cover writes that now use it.
Owner access to the underlying rows is unchanged and is asserted here too — the
rule governs PRESENTATION, never possession.
"""
import pytest

from app.models.character_image import ImageKindEnum, ImageStatusEnum
from app.schemas.character_image import (
    is_public_gallery_image,
    is_public_surface_safe,
)
from tests.conftest import get_auth_token, auth_headers


class _Row:
    """Duck-typed image row: the predicate reads only these two attributes."""

    def __init__(self, provider="fal", metadata_json=None,
                 kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE):
        self.provider = provider
        self.metadata_json = metadata_json if metadata_json is not None else {}
        self.kind = kind
        self.status = status


# ── A. the shared predicate ───────────────────────────────────────────────

def test_shared_helper_rejects_adult_studio_marker():
    assert not is_public_surface_safe(_Row(provider=None,
                                           metadata_json={"adult_studio": True}))


def test_shared_helper_rejects_replicate_nsfw_provider():
    assert not is_public_surface_safe(_Row(provider="replicate_nsfw",
                                           metadata_json={}))


@pytest.mark.parametrize("provider", ["gpt-image", "grok", "self_hosted", None])
def test_shared_helper_rejects_editor_generated_for_any_provider(provider):
    assert not is_public_surface_safe(
        _Row(provider=provider, metadata_json={"editor_generated": True}))


def test_shared_helper_applies_self_hosted_defence_in_depth():
    """provider='self_hosted' excludes on its own, with no metadata flag."""
    assert not is_public_surface_safe(_Row(provider="self_hosted",
                                           metadata_json={}))


def test_shared_helper_reads_provider_from_metadata_too():
    assert not is_public_surface_safe(
        _Row(provider=None, metadata_json={"provider": "replicate_nsfw"}))


@pytest.mark.parametrize("provider", ["fal", "openai", "stub", "gpt-image"])
def test_shared_helper_accepts_ordinary_images(provider):
    assert is_public_surface_safe(
        _Row(provider=provider, metadata_json={"library": True}))


def test_shared_helper_accepts_missing_metadata():
    assert is_public_surface_safe(_Row(metadata_json=None))


def test_shared_helper_encodes_no_gallery_semantics():
    """Kind, status and is_temp are gallery rules and must not leak in here.

    Avatar, cover and post attachment each have their own rules about kind and
    lifecycle; only studio provenance is shared. A row that the gallery rejects
    on kind alone is still public-surface safe.
    """
    assert is_public_surface_safe(
        _Row(kind=ImageKindEnum.UPLOADED, status=ImageStatusEnum.ARCHIVED,
             metadata_json={"is_temp": True}))


# ── B. Step 1 gallery behaviour is unchanged by the refactor ─────────────

def test_gallery_rule_still_enforces_its_own_kind_status_temp_rules():
    assert not is_public_gallery_image(_Row(kind=ImageKindEnum.UPLOADED))
    assert not is_public_gallery_image(_Row(status=ImageStatusEnum.ARCHIVED))
    assert not is_public_gallery_image(_Row(metadata_json={"is_temp": True}))


def test_gallery_rule_still_composes_the_safety_rule():
    assert not is_public_gallery_image(
        _Row(kind=ImageKindEnum.SCENE_ONLY, provider="gpt-image",
             metadata_json={"editor_generated": True}))
    assert is_public_gallery_image(
        _Row(kind=ImageKindEnum.GENERATED, provider="fal"))


# ── C. avatar / cover write protection ───────────────────────────────────

def _create_character(client, token, name="Summer", visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _insert(db_session, character_id, user_id, *, provider, metadata,
            kind=ImageKindEnum.GENERATED, name="img"):
    from app.models.character_image import (
        CharacterImage, ImageStatusEnum as S, ImageVisibilityEnum,
    )
    img = CharacterImage(
        character_id=character_id, user_id=user_id, kind=kind,
        status=S.ACTIVE, visibility=ImageVisibilityEnum.PRIVATE,
        # Step 6.5: selected for the Character Home gallery, so the anonymous
        # assertions below turn on media safety alone.
        public_gallery_enabled=True,
        provider=provider, prompt_summary="fixture", metadata_json=metadata,
        file_path=f"static/generated/surface-{name}.png",
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img.id


@pytest.fixture()
def surface(client, db_session):
    from app.models.user import User

    token = get_auth_token(client, email="surf@test.com", username="surfowner")
    owner_id = db_session.query(User).filter(User.email == "surf@test.com").first().id
    cid = _create_character(client, token)
    # Published Home: since Step 4 that is what makes the gallery anonymously
    # reachable. These tests are about which media is safe, not about the gate.
    from app.models.character import Character
    db_session.query(Character).filter(Character.id == cid).first(
        ).public_home_enabled = True
    db_session.commit()

    return {
        "token": token,
        "character_id": cid,
        "owner_id": owner_id,
        "ok": _insert(db_session, cid, owner_id, provider="fal",
                      metadata={"library": True}, name="ok"),
        "adult": _insert(db_session, cid, owner_id, provider="replicate_nsfw",
                         metadata={"adult_studio": True}, name="adult"),
        "editor": _insert(db_session, cid, owner_id, provider="gpt-image",
                          kind=ImageKindEnum.SCENE_ONLY,
                          metadata={"editor_generated": True}, name="editor"),
    }


@pytest.mark.parametrize("key", ["adult", "editor"])
def test_setting_unsafe_image_as_avatar_is_refused(client, surface, key):
    resp = client.post(
        f"/characters/{surface['character_id']}/avatar",
        json={"image_type": "character", "image_id": surface[key]},
        headers=auth_headers(surface["token"]),
    )
    assert resp.status_code == 400, resp.text
    assert "public surface" in resp.json()["detail"]


@pytest.mark.parametrize("key", ["adult", "editor"])
def test_setting_unsafe_image_as_cover_is_refused(client, surface, key):
    resp = client.post(
        f"/characters/{surface['character_id']}/cover",
        json={"image_type": "character", "image_id": surface[key]},
        headers=auth_headers(surface["token"]),
    )
    assert resp.status_code == 400, resp.text
    assert "public surface" in resp.json()["detail"]


@pytest.mark.parametrize("key", ["adult", "editor"])
def test_second_avatar_path_also_refuses_unsafe_images(client, surface, key):
    """POST /characters/{id}/images/{image_id}/set-avatar — the other writer."""
    resp = client.post(
        f"/characters/{surface['character_id']}/images/{surface[key]}/set-avatar",
        headers=auth_headers(surface["token"]),
    )
    assert resp.status_code == 422, resp.text
    assert "public surface" in resp.json()["detail"]


def test_refused_avatar_write_leaves_the_pointer_untouched(client, surface, db_session):
    """A refusal must not clear or change an existing avatar."""
    from app.models.character import Character

    # Set a legitimate avatar first, via the path that needs no file on disk.
    ok = client.post(
        f"/characters/{surface['character_id']}/images/{surface['ok']}/set-avatar",
        headers=auth_headers(surface["token"]),
    )
    assert ok.status_code == 200, ok.text
    db_session.expire_all()
    before = db_session.query(Character).get(surface["character_id"]).avatar_url
    assert before

    refused = client.post(
        f"/characters/{surface['character_id']}/images/{surface['adult']}/set-avatar",
        headers=auth_headers(surface["token"]),
    )
    assert refused.status_code == 422, refused.text
    db_session.expire_all()
    assert db_session.query(Character).get(surface["character_id"]).avatar_url == before


def test_ordinary_image_can_still_become_the_cover(client, surface):
    resp = client.post(
        f"/characters/{surface['character_id']}/cover",
        json={"image_type": "character", "image_id": surface["ok"]},
        headers=auth_headers(surface["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cover_url"]


def test_ordinary_image_can_still_become_the_avatar_via_both_paths(client, surface):
    resp = client.post(
        f"/characters/{surface['character_id']}/images/{surface['ok']}/set-avatar",
        headers=auth_headers(surface["token"]),
    )
    assert resp.status_code == 200, resp.text


# ── D. possession is untouched ───────────────────────────────────────────

def test_owner_still_holds_and_sees_the_unsafe_rows(client, surface, db_session):
    """The rule governs presentation, not ownership. Nothing is deleted."""
    from app.models.character_image import CharacterImage

    for key in ("adult", "editor"):
        assert db_session.query(CharacterImage).get(surface[key]) is not None

    resp = client.get(
        f"/characters/{surface['character_id']}/images",
        headers=auth_headers(surface["token"]),
    )
    assert resp.status_code == 200, resp.text
    returned = {i["id"] for i in resp.json()}
    for key in ("ok", "adult", "editor"):
        assert surface[key] in returned, f"owner lost sight of {key}"


def test_anonymous_still_sees_only_the_safe_image(client, surface):
    """Step 6.6: the anonymous gallery is /public-home/images. Every fixture row
    is selected, so media safety is the only thing filtering here."""
    resp = client.get(f"/characters/{surface['character_id']}/public-home/images")
    assert {i["id"] for i in resp.json()} == {surface["ok"]}
