"""Phase 4D3-2 — the three policy boundaries, drawn before canon has rows.

4D3-3 gives the identity-canon writers owned ``CharacterImage`` rows. Every test
here exists because that step silently GRANTS something unless a rule is stated
first:

* an image becomes selectable as an avatar and as a cover, on routes that only
  ever asked about ownership, status and provenance — so rowlessness has been
  doing the work of a policy;
* an image becomes reachable by the two generic archive routes, neither of which
  knows what canon is;
* and ``kind``, now that three policies read it, becomes worth rewriting —
  which ``promote-to-canon`` would have allowed.

The rules are unit-tested against the predicates AND exercised through the real
routes, because a predicate nobody calls is not a boundary.
"""
import pytest

from app.models.character_image import (
    CANON_PROMOTABLE_SOURCE_KINDS,
    PROTECTED_IMAGE_KINDS,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.character_image import (
    AVATAR_ELIGIBLE_KINDS,
    COVER_ELIGIBLE_KINDS,
    is_avatar_eligible,
    is_cover_eligible,
)
from app.services.canon_references import canon_referenced_file_paths, is_canon_referenced
from tests.conftest import auth_headers, get_auth_token

#: The ten kinds Phase 4D3-1 added. None may reach a public surface by kind.
CANON_KINDS_4D3 = (
    ImageKindEnum.IDENTITY_FACE_PROFILE,
    ImageKindEnum.IDENTITY_FACE_EXPRESSION,
    ImageKindEnum.IDENTITY_BODY_LEFT,
    ImageKindEnum.IDENTITY_BODY_RIGHT,
    ImageKindEnum.IDENTITY_TORSO_FRONT,
    ImageKindEnum.IDENTITY_TORSO_SIDE,
    ImageKindEnum.IDENTITY_POSE_STANDING,
    ImageKindEnum.IDENTITY_POSE_SEATED,
    ImageKindEnum.IDENTITY_MARK_REFERENCE,
    ImageKindEnum.IDENTITY_MARK_DETAIL,
)

REFUSED_AVATAR_KINDS = tuple(k for k in ImageKindEnum if k not in AVATAR_ELIGIBLE_KINDS)
REFUSED_COVER_KINDS = tuple(k for k in ImageKindEnum if k not in COVER_ELIGIBLE_KINDS)


# ── helpers ──────────────────────────────────────────────────────────────────


#: Position of each kind in the enum — a short, unique, ALPHANUMERIC tag per
#: parametrised case. Truncating ``kind.value`` instead produces ``"identity_"``
#: for ten different kinds, which collides the accounts AND ends a username in
#: an underscore that registration rejects, so every such case fails to log in
#: for a reason that has nothing to do with the policy under test.
_KIND_INDEX = {kind: index for index, kind in enumerate(ImageKindEnum)}


def _tag(prefix: str, kind: ImageKindEnum) -> str:
    return f"{prefix}{_KIND_INDEX[kind]}"


def _owner(client, tag):
    # ``@test.com``: the ``.test`` TLD is reserved and the email validator
    # refuses it, as every other suite here already discovered.
    assert tag.isalnum(), f"tag must be alphanumeric for username validity: {tag!r}"
    token = get_auth_token(client, email=f"{tag}@4d3p.test.com", username=f"u{tag}")
    return token, auth_headers(token)


def _character(client, hdrs, name="Policy Character"):
    resp = client.post("/characters/", json={"name": name, "description": "d"}, headers=hdrs)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _image(db, character_id, owner_id, kind, *, provider="google", path=None, metadata=None):
    """An owned, ACTIVE image row.

    ``file_path`` defaults to an ABSOLUTE (R2-style) url, which is what 1409 of
    the 1429 rows on DEV actually hold. It also keeps these tests off the
    filesystem: the avatar route crops LOCAL paths, so a relative fixture path
    would need real bytes on disk and would fail with "source image file not
    found" — a disk-shaped failure in a test about kind policy. Tests that are
    specifically about local path spellings pass ``path`` explicitly.
    """
    img = CharacterImage(
        user_id=owner_id,
        character_id=character_id,
        kind=kind,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider,
        metadata_json=metadata,
        file_path=path or f"https://r2.example/generated/{kind.value}-{character_id}.png",
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


def _owner_id(db, character_id):
    from app.models.character import Character
    return db.query(Character).filter(Character.id == character_id).one().owner_id


# ── A. avatar eligibility ────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted(AVATAR_ELIGIBLE_KINDS, key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_an_approved_kind_may_become_the_avatar_on_both_routes(client, db_session, kind):
    _, hdrs = _owner(client, _tag("av", kind))
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)

    img = _image(db_session, char_id, owner_id, kind)
    resp = client.post(f"/characters/{char_id}/avatar",
                       json={"image_type": "character", "image_id": img.id}, headers=hdrs)
    assert resp.status_code == 200, resp.text

    img2 = _image(db_session, char_id, owner_id, kind,
                  path=f"https://r2.example/generated/{kind.value}-b.png")
    resp2 = client.post(f"/characters/{char_id}/images/{img2.id}/set-avatar", headers=hdrs)
    assert resp2.status_code == 200, resp2.text


@pytest.mark.parametrize("kind", sorted(REFUSED_AVATAR_KINDS, key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_an_ineligible_kind_is_refused_on_both_routes(client, db_session, kind):
    _, hdrs = _owner(client, _tag("rv", kind))
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    img = _image(db_session, char_id, owner_id, kind)

    resp = client.post(f"/characters/{char_id}/avatar",
                       json={"image_type": "character", "image_id": img.id}, headers=hdrs)
    assert resp.status_code == 400, resp.text

    resp2 = client.post(f"/characters/{char_id}/images/{img.id}/set-avatar", headers=hdrs)
    assert resp2.status_code == 422, resp2.text


def test_every_new_canon_kind_is_avatar_ineligible_except_the_two_portrait_ones():
    eligible = {k for k in CANON_KINDS_4D3 if k in AVATAR_ELIGIBLE_KINDS}
    assert eligible == {ImageKindEnum.IDENTITY_FACE_EXPRESSION}


def test_the_refusal_does_not_change_an_existing_avatar(client, db_session):
    """Existing avatars are never retroactively revalidated; a refused NEW
    selection must also leave the current one exactly as it was."""
    _, hdrs = _owner(client, "keepav")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)

    good = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED)
    client.post(f"/characters/{char_id}/avatar",
                json={"image_type": "character", "image_id": good.id}, headers=hdrs)
    before = client.get(f"/characters/{char_id}", headers=hdrs).json()["avatar_url"]
    assert before

    bad = _image(db_session, char_id, owner_id, ImageKindEnum.IDENTITY_BODY_MAP)
    assert client.post(f"/characters/{char_id}/avatar",
                       json={"image_type": "character", "image_id": bad.id},
                       headers=hdrs).status_code == 400
    after = client.get(f"/characters/{char_id}", headers=hdrs).json()["avatar_url"]
    assert after == before


def test_a_user_image_is_not_forced_through_the_character_kind_allowlist(client, db_session):
    """``UserImage.kind`` is a free-form string, not ImageKindEnum. Putting it
    through this allowlist would refuse every account image — a workflow that
    predates the policy."""
    from app.models.user import User as UserModel
    from app.models.user_image import UserImage

    _, hdrs = _owner(client, "uimg")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    user = db_session.query(UserModel).filter(UserModel.id == owner_id).one()

    ui = UserImage(user_id=user.id, kind="profile_cover", status="active",
                   provider="openai",
                   file_path="https://r2.example/generated/user-avatar.png")
    db_session.add(ui)
    db_session.commit()
    db_session.refresh(ui)

    assert is_avatar_eligible(ui) is True
    resp = client.post(f"/characters/{char_id}/avatar",
                       json={"image_type": "user", "image_id": ui.id}, headers=hdrs)
    assert resp.status_code == 200, resp.text


def test_unsafe_provenance_is_still_refused_even_for_an_eligible_kind(client, db_session):
    _, hdrs = _owner(client, "unsafe")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    img = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED,
                 provider="replicate_nsfw")

    assert is_avatar_eligible(img) is False
    assert client.post(f"/characters/{char_id}/avatar",
                       json={"image_type": "character", "image_id": img.id},
                       headers=hdrs).status_code == 400
    assert client.post(f"/characters/{char_id}/images/{img.id}/set-avatar",
                       headers=hdrs).status_code == 422


def test_both_avatar_routes_use_the_same_predicate():
    """Pinned by source, because a second implementation is how two entrances
    start meaning different things."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "app" / "api" / "routes"
    for name in ("characters.py", "character_visual.py"):
        assert "is_avatar_eligible(" in (root / name).read_text()


# ── B. cover eligibility ─────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted(COVER_ELIGIBLE_KINDS, key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_an_approved_kind_may_become_the_cover(client, db_session, kind):
    _, hdrs = _owner(client, _tag("cv", kind))
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    img = _image(db_session, char_id, owner_id, kind)

    resp = client.post(f"/characters/{char_id}/cover",
                       json={"image_type": "character", "image_id": img.id},
                       headers=hdrs)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("kind", sorted(REFUSED_COVER_KINDS, key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_an_ineligible_kind_is_refused_as_a_cover(client, db_session, kind):
    _, hdrs = _owner(client, _tag("rc", kind))
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    img = _image(db_session, char_id, owner_id, kind)

    resp = client.post(f"/characters/{char_id}/cover",
                       json={"image_type": "character", "image_id": img.id},
                       headers=hdrs)
    assert resp.status_code == 400, resp.text


def test_the_two_allowlists_are_distinct_and_neither_derives_from_the_other():
    assert AVATAR_ELIGIBLE_KINDS is not COVER_ELIGIBLE_KINDS
    assert AVATAR_ELIGIBLE_KINDS != COVER_ELIGIBLE_KINDS
    # Face anchors: avatar yes, cover no. The divergence that justifies two lists.
    assert ImageKindEnum.ANCHOR_FRONT in AVATAR_ELIGIBLE_KINDS
    assert ImageKindEnum.ANCHOR_FRONT not in COVER_ELIGIBLE_KINDS
    # COVER: cover yes, avatar no.
    assert ImageKindEnum.COVER in COVER_ELIGIBLE_KINDS
    assert ImageKindEnum.COVER not in AVATAR_ELIGIBLE_KINDS


def test_the_approved_allowlists_are_pinned():
    assert AVATAR_ELIGIBLE_KINDS == frozenset({
        ImageKindEnum.GENERATED, ImageKindEnum.SCENE_ONLY, ImageKindEnum.UPLOADED,
        ImageKindEnum.IDENTITY_FACE_REF, ImageKindEnum.ANCHOR_FRONT,
        ImageKindEnum.ANCHOR_THREE_QUARTER, ImageKindEnum.IDENTITY_FACE_EXPRESSION,
        ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD,
    })
    assert COVER_ELIGIBLE_KINDS == frozenset({
        ImageKindEnum.GENERATED, ImageKindEnum.COVER, ImageKindEnum.SCENE_ONLY,
        ImageKindEnum.UPLOADED, ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD,
    })


def test_a_user_image_is_not_forced_through_the_cover_allowlist(db_session):
    from app.models.user_image import UserImage
    ui = UserImage(user_id=1, kind="profile_cover", status="active",
                   provider="openai", file_path="static/generated/uc.png")
    assert is_cover_eligible(ui) is True


# ── C. active canon-reference protection ─────────────────────────────────────


CANON_LOCATIONS = (
    ("canon.face_canon_json", "canon", "face_canon_json",
     lambda url: {"face_front_image_url": url}),
    ("canon.body_canon_json", "canon", "body_canon_json",
     lambda url: {"permanent_body_marks": [{"id": "m1", "detail_crop_url": url}]}),
    ("canon.accessories_json", "canon", "accessories_json",
     lambda url: [{"id": "a1", "fit_anchor_image_url": url}]),
    ("character.identity_anchor_json", "character", "identity_anchor_json",
     lambda url: {"anchors": {"front": {"url": url}}}),
    ("character.body_canon_json", "character", "body_canon_json",
     lambda url: {"markings": [{"id": "bm1", "anchor_image_url": url}]}),
)


def _reference_from(db, character, canon, where, column, build, url):
    import json
    target = canon if where == "canon" else character
    setattr(target, column, json.dumps(build(url)))
    db.add(target)
    db.commit()


#: Deterministic per-location tag, for the same reason as :data:`_KIND_INDEX`.
CANON_LOCATION_INDEX = {entry[0]: index for index, entry in enumerate(CANON_LOCATIONS)}


@pytest.mark.parametrize("label,where,column,build", CANON_LOCATIONS,
                         ids=[c[0] for c in CANON_LOCATIONS])
def test_a_referenced_asset_is_refused_by_both_archive_routes(
    client, db_session, label, where, column, build
):
    from app.models.character import Character

    _, hdrs = _owner(client, f"cr{CANON_LOCATION_INDEX[label]}")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    character = db_session.query(Character).filter(Character.id == char_id).one()

    canon = CharacterIdentityCanon(character_id=char_id)
    db_session.add(canon)
    db_session.commit()

    img = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED)
    _reference_from(db_session, character, canon, where, column, build, img.file_path)

    assert is_canon_referenced(db_session, img) is True
    assert client.delete(f"/characters/{char_id}/images/{img.id}",
                         headers=hdrs).status_code == 422
    assert client.delete(f"/users/me/character-images/{img.id}",
                         headers=hdrs).status_code == 422

    db_session.expire_all()
    still = db_session.query(CharacterImage).filter(CharacterImage.id == img.id).one()
    assert still.status == ImageStatusEnum.ACTIVE


def test_an_unreferenced_asset_stays_archivable(client, db_session):
    _, hdrs = _owner(client, "unref")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    canon = CharacterIdentityCanon(character_id=char_id)
    db_session.add(canon)
    db_session.commit()

    img = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED)
    assert is_canon_referenced(db_session, img) is False
    assert client.delete(f"/characters/{char_id}/images/{img.id}",
                         headers=hdrs).status_code == 204


def test_a_superseded_asset_becomes_archivable_once_canon_moves_on(client, db_session):
    """The property a kind-based list cannot express: protection ENDS when the
    reference does."""
    import json
    from app.models.character import Character

    _, hdrs = _owner(client, "supers")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    character = db_session.query(Character).filter(Character.id == char_id).one()
    canon = CharacterIdentityCanon(character_id=char_id)
    db_session.add(canon)
    db_session.commit()

    old = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED,
                 path="static/generated/old-slot.png")
    new = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED,
                 path="static/generated/new-slot.png")

    canon.face_canon_json = json.dumps({"face_front_image_url": old.file_path})
    db_session.commit()
    assert client.delete(f"/characters/{char_id}/images/{old.id}",
                         headers=hdrs).status_code == 422

    canon.face_canon_json = json.dumps({"face_front_image_url": new.file_path})
    db_session.commit()
    db_session.expire_all()
    assert client.delete(f"/characters/{char_id}/images/{old.id}",
                         headers=hdrs).status_code == 204


def test_a_rowless_canon_reference_does_not_block_an_unrelated_row(client, db_session):
    """DEV holds 100 canon URLs no row was ever created for. They must protect
    nothing, and must not be matched against a different image's path."""
    import json

    _, hdrs = _owner(client, "rowless")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    canon = CharacterIdentityCanon(character_id=char_id)
    db_session.add(canon)
    db_session.commit()

    canon.face_canon_json = json.dumps(
        {"face_front_image_url": "https://r2.example/generated/never-had-a-row.png"}
    )
    db_session.commit()

    unrelated = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED)
    assert is_canon_referenced(db_session, unrelated) is False
    assert client.delete(f"/characters/{char_id}/images/{unrelated.id}",
                         headers=hdrs).status_code == 204


def test_url_spellings_of_the_same_file_are_treated_as_one(client, db_session):
    """Canon may hold ``/static/generated/x.png`` for a row stored as
    ``static/generated/x.png``. Shared candidate-path semantics, so the guard
    and the resolver cannot disagree."""
    import json
    _, hdrs = _owner(client, "spell")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    canon = CharacterIdentityCanon(character_id=char_id)
    db_session.add(canon)
    db_session.commit()

    img = _image(db_session, char_id, owner_id, ImageKindEnum.GENERATED,
                 path="static/generated/spelling.png")
    canon.face_canon_json = json.dumps({"face_front_image_url": "/static/generated/spelling.png"})
    db_session.commit()

    assert is_canon_referenced(db_session, img) is True
    assert client.delete(f"/characters/{char_id}/images/{img.id}",
                         headers=hdrs).status_code == 422


def test_a_characterless_asset_has_no_canon_to_consult(db_session):
    assert canon_referenced_file_paths(db_session, None) == set()


def test_protected_image_kinds_still_holds_exactly_the_four_anchors():
    """The ten new canon kinds are deliberately NOT here: they are protected by
    reference while canon uses them, and freely removable once it does not."""
    assert PROTECTED_IMAGE_KINDS == frozenset({
        ImageKindEnum.ANCHOR_FRONT, ImageKindEnum.ANCHOR_THREE_QUARTER,
        ImageKindEnum.ANCHOR_TORSO, ImageKindEnum.ANCHOR_FULL_BODY,
    })
    for kind in CANON_KINDS_4D3:
        assert kind not in PROTECTED_IMAGE_KINDS


# ── D. promote-to-canon taxonomy integrity ───────────────────────────────────


@pytest.mark.parametrize("kind", sorted(CANON_PROMOTABLE_SOURCE_KINDS, key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_an_ordinary_image_may_still_be_promoted(client, db_session, kind):
    _, hdrs = _owner(client, _tag("pr", kind))
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    img = _image(db_session, char_id, owner_id, kind)

    resp = client.post(f"/characters/{char_id}/images/{img.id}/promote-to-canon",
                       json={"target": "face_canon"}, headers=hdrs)
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_kind"] == ImageKindEnum.ANCHOR_FRONT.value


@pytest.mark.parametrize("kind", sorted(CANON_KINDS_4D3, key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_an_established_canon_asset_cannot_be_relabelled(client, db_session, kind):
    """The bypass this closes: relabel a mark crop as a face anchor and it would
    satisfy an avatar policy that is supposed to be about what the image IS."""
    _, hdrs = _owner(client, _tag("np", kind))
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    img = _image(db_session, char_id, owner_id, kind)

    resp = client.post(f"/characters/{char_id}/images/{img.id}/promote-to-canon",
                       json={"target": "face_canon"}, headers=hdrs)
    assert resp.status_code == 422, resp.text

    db_session.expire_all()
    unchanged = db_session.query(CharacterImage).filter(CharacterImage.id == img.id).one()
    assert unchanged.kind is kind


def test_the_relabelling_route_cannot_launder_an_image_onto_the_avatar_surface(
    client, db_session
):
    """End to end: the two policies hold together, not just individually."""
    _, hdrs = _owner(client, "launder")
    char_id = _character(client, hdrs)
    owner_id = _owner_id(db_session, char_id)
    crop = _image(db_session, char_id, owner_id, ImageKindEnum.IDENTITY_MARK_DETAIL)

    assert client.post(f"/characters/{char_id}/avatar",
                       json={"image_type": "character", "image_id": crop.id},
                       headers=hdrs).status_code == 400
    assert client.post(f"/characters/{char_id}/images/{crop.id}/promote-to-canon",
                       json={"target": "face_canon"}, headers=hdrs).status_code == 422
    assert client.post(f"/characters/{char_id}/avatar",
                       json={"image_type": "character", "image_id": crop.id},
                       headers=hdrs).status_code == 400


def test_the_promotable_source_list_holds_no_canon_kind():
    for kind in CANON_KINDS_4D3:
        assert kind not in CANON_PROMOTABLE_SOURCE_KINDS
    assert CANON_PROMOTABLE_SOURCE_KINDS == frozenset({
        ImageKindEnum.SCENE_ONLY, ImageKindEnum.GENERATED, ImageKindEnum.UPLOADED,
    })
