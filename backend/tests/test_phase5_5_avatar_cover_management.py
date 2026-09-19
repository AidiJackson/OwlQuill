"""Phase 5.5 — avatar / cover management contract (PD-6).

Pins what the owner's Manage tab now relies on, without restating what
``test_phase4d3_policy_boundaries`` (kind allowlists on both avatar routes and
the cover route), ``test_phase4d2_avatar_assets`` (the crop is a real asset)
and ``test_cover_position_persistence`` (preserve-vs-set framing) already prove.

New in this phase and proven here:

  * ``GET /users/me/character-images?eligible_for=avatar|cover`` returns
    exactly the rows the corresponding set route would accept — the server's
    predicate, so the picker no longer carries its own narrower list.
  * ``DELETE /characters/{id}/avatar`` and ``DELETE /characters/{id}/cover``:
    owner-only; clear the pointer; reset that surface's framing to defaults;
    touch no image row; return the owner detail projection; idempotent.
  * The set routes leave framing alone (documented — the client resets it for
    a new image); the remove routes are what guarantee a fresh start.
  * Ownership on every mutation; a foreign or ineligible image on either.
  * No quota deduction and no provider factory is reached by any of these.

Every image fixture uses an absolute (R2-style) ``file_path`` so the avatar
route's local-crop branch is not exercised: that branch reads bytes from disk
and is covered by ``test_phase4d2_avatar_assets``.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.models.character import Character as CharacterModel
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from tests.conftest import auth_headers, get_auth_token


def _login(client, email):
    return get_auth_token(client, email=email, username=email.split("@")[0])


def _character(client, token, name="Managed"):
    resp = client.post("/characters/", json={"name": name, "species": "human"}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _owner_id(db, cid):
    return db.get(CharacterModel, cid).owner_id


def _image(db, cid, owner_id, kind, *, status=ImageStatusEnum.ACTIVE, provider="google", metadata=None, path=None):
    img = CharacterImage(
        user_id=owner_id, character_id=cid, kind=kind, status=status,
        visibility=ImageVisibilityEnum.PRIVATE, provider=provider, metadata_json=metadata,
        file_path=path or f"https://r2.example/{kind.value}-{cid}-{status.value}.png",
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


def _get(client, token, cid):
    resp = client.get(f"/characters/{cid}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _set_avatar(client, token, cid, image_id):
    return client.post(f"/characters/{cid}/avatar",
                       json={"image_type": "character", "image_id": image_id}, headers=auth_headers(token))


def _set_cover(client, token, cid, image_id, **pos):
    return client.post(f"/characters/{cid}/cover",
                       json={"image_type": "character", "image_id": image_id, **pos}, headers=auth_headers(token))


def _remove(client, token, cid, surface):
    return client.delete(f"/characters/{cid}/{surface}", headers=auth_headers(token))


def _library(client, token, cid, **params):
    resp = client.get("/users/me/character-images", params={"character_id": cid, **params}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["id"] for r in resp.json()}


def _quota_used(client, token):
    return client.get("/images/quota", headers=auth_headers(token)).json()["used"]


# ── eligible_for: the server's answer, not the picker's guess ────────


def test_eligible_for_avatar_matches_the_avatar_route_exactly(client, db_session):
    """A fresh character with only canon face cards can pick one; the kinds
    the avatar route refuses are absent; archived, temp, unsafe and foreign
    rows are absent regardless of kind."""
    token = _login(client, "p55_elig_av@example.com")
    cid = _character(client, token)
    oid = _owner_id(db_session, cid)

    face = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FACE_FRONT)
    three_q = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FACE_LEFT_3Q)
    generated = _image(db_session, cid, oid, ImageKindEnum.GENERATED)
    uploaded = _image(db_session, cid, oid, ImageKindEnum.UPLOADED, provider=None)
    body_map = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_BODY_MAP)
    cover_kind = _image(db_session, cid, oid, ImageKindEnum.COVER)
    archived = _image(db_session, cid, oid, ImageKindEnum.GENERATED, status=ImageStatusEnum.ARCHIVED)
    temp = _image(db_session, cid, oid, ImageKindEnum.GENERATED, metadata={"is_temp": True})
    unsafe = _image(db_session, cid, oid, ImageKindEnum.GENERATED, provider="replicate_nsfw")

    other = _login(client, "p55_elig_other@example.com")
    other_cid = _character(client, other, "Theirs")
    foreign = _image(db_session, other_cid, _owner_id(db_session, other_cid), ImageKindEnum.GENERATED)

    offered = _library(client, token, cid, eligible_for="avatar")
    assert offered == {face.id, three_q.id, generated.id, uploaded.id}
    for absent in (body_map, cover_kind, archived, temp, unsafe, foreign):
        assert absent.id not in offered

    # And every offered row is one the route ACCEPTS; every excluded active
    # row of this owner is one it REFUSES — the list and the route agree.
    for img in (face, three_q, generated, uploaded):
        assert _set_avatar(client, token, cid, img.id).status_code == 200
    for img in (body_map, cover_kind, unsafe):
        assert _set_avatar(client, token, cid, img.id).status_code == 400


def test_eligible_for_cover_matches_the_cover_route_exactly(client, db_session):
    token = _login(client, "p55_elig_cv@example.com")
    cid = _character(client, token)
    oid = _owner_id(db_session, cid)

    generated = _image(db_session, cid, oid, ImageKindEnum.GENERATED)
    final_card = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD)
    cover_kind = _image(db_session, cid, oid, ImageKindEnum.COVER)
    face = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FACE_FRONT)

    offered = _library(client, token, cid, eligible_for="cover")
    assert offered == {generated.id, final_card.id, cover_kind.id}
    assert face.id not in offered
    assert _set_cover(client, token, cid, face.id).status_code == 400
    assert _set_cover(client, token, cid, final_card.id).status_code == 200


def test_eligible_for_rejects_unknown_surfaces_and_is_optional(client, db_session):
    token = _login(client, "p55_elig_opt@example.com")
    cid = _character(client, token)
    oid = _owner_id(db_session, cid)
    body_map = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_BODY_MAP)
    # Without the filter the library lists everything it always did.
    assert body_map.id in _library(client, token, cid)
    resp = client.get("/users/me/character-images", params={"eligible_for": "banner"}, headers=auth_headers(token))
    assert resp.status_code == 422


# ── set: ownership and framing ───────────────────────────────────────


def test_non_owner_cannot_set_avatar_or_cover(client, db_session):
    owner = _login(client, "p55_own@example.com")
    intruder = _login(client, "p55_intr@example.com")
    cid = _character(client, owner)
    img = _image(db_session, cid, _owner_id(db_session, cid), ImageKindEnum.GENERATED)
    assert _set_avatar(client, intruder, cid, img.id).status_code == 403
    assert _set_cover(client, intruder, cid, img.id).status_code == 403
    assert _get(client, owner, cid)["avatar_url"] is None
    assert _get(client, owner, cid)["cover_url"] is None


def test_another_users_image_cannot_become_avatar_or_cover(client, db_session):
    owner = _login(client, "p55_own2@example.com")
    cid = _character(client, owner)
    other = _login(client, "p55_other2@example.com")
    other_cid = _character(client, other, "Theirs")
    foreign = _image(db_session, other_cid, _owner_id(db_session, other_cid), ImageKindEnum.GENERATED)
    r1 = _set_avatar(client, owner, cid, foreign.id)
    r2 = _set_cover(client, owner, cid, foreign.id)
    assert r1.status_code == 403 and r1.json()["detail"] == "Not your image"
    assert r2.status_code == 403 and r2.json()["detail"] == "Not your image"


def test_avatar_framing_persists_and_the_set_route_leaves_it_alone(client, db_session):
    """The set route assigns the picture ONLY. Framing is the client's PATCH,
    and a new picture must be given a fresh crop by the client (both canonical
    callers do) or by DELETE; this pins the division so it is not assumed."""
    owner = _login(client, "p55_frame@example.com")
    cid = _character(client, owner)
    oid = _owner_id(db_session, cid)
    first = _image(db_session, cid, oid, ImageKindEnum.GENERATED)
    second = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FACE_FRONT)

    assert _set_avatar(client, owner, cid, first.id).status_code == 200
    resp = client.patch(f"/characters/{cid}", json={"avatar_position_x": 0.2, "avatar_position_y": 0.8, "avatar_scale": 1.6},
                        headers=auth_headers(owner))
    assert resp.status_code == 200
    read = _get(client, owner, cid)
    assert (read["avatar_position_x"], read["avatar_position_y"], read["avatar_scale"]) == (0.2, 0.8, 1.6)

    assert _set_avatar(client, owner, cid, second.id).status_code == 200
    read = _get(client, owner, cid)
    assert read["avatar_url"] == second.file_path
    # Untouched by the set route — the documented contract.
    assert (read["avatar_position_x"], read["avatar_position_y"], read["avatar_scale"]) == (0.2, 0.8, 1.6)


def test_cover_positioning_persists(client, db_session):
    owner = _login(client, "p55_cpos@example.com")
    cid = _character(client, owner)
    img = _image(db_session, cid, _owner_id(db_session, cid), ImageKindEnum.GENERATED)
    resp = _set_cover(client, owner, cid, img.id, cover_position_x=0.1, cover_position_y=0.9)
    assert resp.status_code == 200, resp.text
    read = _get(client, owner, cid)
    assert read["cover_url"] == img.file_path
    assert (read["cover_position_x"], read["cover_position_y"]) == (0.1, 0.9)


# ── remove ───────────────────────────────────────────────────────────


def test_owner_removes_avatar_clearing_pointer_and_framing_keeping_every_image(client, db_session):
    owner = _login(client, "p55_rm_av@example.com")
    cid = _character(client, owner)
    oid = _owner_id(db_session, cid)
    img = _image(db_session, cid, oid, ImageKindEnum.GENERATED)
    assert _set_avatar(client, owner, cid, img.id).status_code == 200
    client.patch(f"/characters/{cid}", json={"avatar_position_x": 0.3, "avatar_position_y": 0.7, "avatar_scale": 2.0},
                 headers=auth_headers(owner))
    rows_before = db_session.query(CharacterImage).filter(CharacterImage.user_id == oid).count()

    resp = _remove(client, owner, cid, "avatar")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["avatar_url"] is None
    assert (body["avatar_position_x"], body["avatar_position_y"], body["avatar_scale"]) == (0.5, 0.5, 1.0)
    # Cover side untouched.
    assert body["cover_url"] is None and body["cover_position_x"] == 0.5

    # The image row: still there, still ACTIVE, still this owner's, same bytes pointer.
    db_session.expire_all()
    kept = db_session.get(CharacterImage, img.id)
    assert kept is not None and kept.status == ImageStatusEnum.ACTIVE
    assert kept.user_id == oid and kept.file_path == img.file_path
    assert db_session.query(CharacterImage).filter(CharacterImage.user_id == oid).count() == rows_before
    assert img.id in _library(client, owner, cid)


def test_owner_removes_cover_clearing_pointer_and_position_keeping_the_image(client, db_session):
    owner = _login(client, "p55_rm_cv@example.com")
    cid = _character(client, owner)
    oid = _owner_id(db_session, cid)
    img = _image(db_session, cid, oid, ImageKindEnum.GENERATED)
    face = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FACE_FRONT)
    assert _set_cover(client, owner, cid, img.id, cover_position_x=0.1, cover_position_y=0.9).status_code == 200
    assert _set_avatar(client, owner, cid, face.id).status_code == 200

    resp = _remove(client, owner, cid, "cover")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cover_url"] is None
    assert (body["cover_position_x"], body["cover_position_y"], body["cover_scale"]) == (0.5, 0.5, 1.0)
    # Avatar side untouched.
    assert body["avatar_url"] == face.file_path

    db_session.expire_all()
    kept = db_session.get(CharacterImage, img.id)
    assert kept is not None and kept.status == ImageStatusEnum.ACTIVE and kept.file_path == img.file_path


@pytest.mark.parametrize("surface", ["avatar", "cover"])
def test_remove_is_owner_only(client, db_session, surface):
    owner = _login(client, f"p55_rmown_{surface}@example.com")
    intruder = _login(client, f"p55_rmintr_{surface}@example.com")
    cid = _character(client, owner)
    img = _image(db_session, cid, _owner_id(db_session, cid), ImageKindEnum.GENERATED)
    setter = _set_avatar if surface == "avatar" else _set_cover
    assert setter(client, owner, cid, img.id).status_code == 200

    assert _remove(client, intruder, cid, surface).status_code == 403
    assert _get(client, owner, cid)[f"{surface}_url"] == img.file_path
    assert _remove(client, owner, 999999, surface).status_code == 404


@pytest.mark.parametrize("surface", ["avatar", "cover"])
def test_remove_is_idempotent(client, surface):
    owner = _login(client, f"p55_rmidem_{surface}@example.com")
    cid = _character(client, owner)
    assert _remove(client, owner, cid, surface).status_code == 200
    assert _remove(client, owner, cid, surface).status_code == 200
    assert _get(client, owner, cid)[f"{surface}_url"] is None


@pytest.mark.parametrize("surface", ["avatar", "cover"])
def test_remove_returns_the_owner_detail_projection(client, db_session, surface):
    owner = _login(client, f"p55_rmproj_{surface}@example.com")
    cid = _character(client, owner)
    img = _image(db_session, cid, _owner_id(db_session, cid), ImageKindEnum.GENERATED)
    setter = _set_avatar if surface == "avatar" else _set_cover
    assert setter(client, owner, cid, img.id).status_code == 200

    body = _remove(client, owner, cid, surface).json()
    read = _get(client, owner, cid)
    assert body["is_owner"] is True
    assert body["owner_id"] is not None
    assert body["owner_username"] == f"p55_rmproj_{surface}"
    assert body == read


# ── none of this costs anything ──────────────────────────────────────


def test_management_operations_consume_no_quota_and_reach_no_provider(client, db_session, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 1)  # one slot: any deduction would show
    owner = _login(client, "p55_free@example.com")
    cid = _character(client, owner)
    oid = _owner_id(db_session, cid)
    face = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FACE_FRONT)
    card = _image(db_session, cid, oid, ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD)
    used_before = _quota_used(client, owner)

    factories = {
        "app.services.image_provider.get_provider_for_option": MagicMock(),
        "app.services.image_provider.get_image_provider": MagicMock(),
        "app.services.image_provider.get_fallback_provider": MagicMock(),
    }
    with patch.multiple("app.services.image_provider",
                        get_provider_for_option=factories["app.services.image_provider.get_provider_for_option"],
                        get_image_provider=factories["app.services.image_provider.get_image_provider"],
                        get_fallback_provider=factories["app.services.image_provider.get_fallback_provider"]):
        assert _set_avatar(client, owner, cid, face.id).status_code == 200
        assert _set_cover(client, owner, cid, card.id).status_code == 200
        assert _library(client, owner, cid, eligible_for="avatar")
        assert _remove(client, owner, cid, "avatar").status_code == 200
        assert _remove(client, owner, cid, "cover").status_code == 200

    for mock in factories.values():
        mock.assert_not_called()
    assert _quota_used(client, owner) == used_before
