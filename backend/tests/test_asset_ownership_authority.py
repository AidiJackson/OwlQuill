"""CharacterImage.user_id is the authority on asset ownership (Phase 4B1).

Two things have to hold at once, and they pull in opposite directions:

* "Does this account own this asset?" is answered by ``CharacterImage.user_id``
  — not by joining ``Character`` and reading ``owner_id``.
* "Which character is this associated with?" is still answered by
  ``character_id``, and every surface that is legitimately character-scoped
  stays exactly as narrow as it was. A post authored by Pan may not attach
  Shadow's media, however many characters one account owns.

The tests below pin both, including the cases where the two answers differ —
those are the only ones that can tell which field the code actually consults.
"""
import pytest

from app.models.character import Character
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
)
from app.models.user import User
from tests.conftest import auth_headers, get_auth_token


# ── helpers ───────────────────────────────────────────────────────────────────


def _seeder_token(client, db_session, email, username):
    """A creator account exempt from the one-character-per-account limit."""
    token = get_auth_token(client, email=email, username=username)
    user = db_session.query(User).filter(User.email == email).first()
    user.is_seeder = True
    db_session.commit()
    return token


def _make_character(client, token, name):
    resp = client.post(
        "/characters/", json={"name": name, "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_image(
    db,
    *,
    character_id,
    owner_id,
    file_path,
    kind=ImageKindEnum.GENERATED,
    status=ImageStatusEnum.ACTIVE,
    metadata_json=None,
):
    """Seed one image with association and ownership stated SEPARATELY.

    ``owner_id`` is passed rather than derived from the character precisely so a
    test can make the two disagree — that is the only way to prove which one a
    route reads.
    """
    img = CharacterImage(
        character_id=character_id,
        user_id=owner_id,
        file_path=file_path,
        kind=kind,
        status=status,
        visibility="private",
        metadata_json=metadata_json,
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    return img


def _user_id(db, email):
    return db.query(User).filter(User.email == email).first().id


@pytest.fixture
def library(client, db_session):
    """One account, two characters, a realistic spread of owned assets."""
    token = _seeder_token(client, db_session, "owner@ownership.example.com", "ownershipowner")
    uid = _user_id(db_session, "owner@ownership.example.com")
    pan = _make_character(client, token, "Pan")
    shadow = _make_character(client, token, "Shadow")

    kept = [
        _seed_image(db_session, character_id=pan, owner_id=uid,
                    file_path="static/generated/o-pan-1.png"),
        _seed_image(db_session, character_id=pan, owner_id=uid,
                    file_path="static/generated/o-pan-2.png",
                    kind=ImageKindEnum.IDENTITY_FACE_REF),
        _seed_image(db_session, character_id=shadow, owner_id=uid,
                    file_path="static/generated/o-shadow-1.png"),
    ]
    # Excluded for reasons that have nothing to do with ownership, and must
    # stay excluded: archived lifecycle, and an unaccepted temp pack preview.
    _seed_image(db_session, character_id=pan, owner_id=uid,
                file_path="static/generated/o-archived.png",
                status=ImageStatusEnum.ARCHIVED)
    _seed_image(db_session, character_id=pan, owner_id=uid,
                file_path="static/generated/o-temp.png",
                metadata_json={"is_temp": True})

    return {
        "token": token, "user_id": uid, "pan": pan, "shadow": shadow,
        "kept_ids": sorted(i.id for i in kept),
    }


# ── the library ───────────────────────────────────────────────────────────────


def test_library_row_set_is_identical_to_the_old_character_join(client, db_session, library):
    """The switch changes the authority, not the result, on backfilled data.

    This is the regression the increment turns on: every row's ``user_id``
    equals its character's ``owner_id`` after the backfill, so the endpoint must
    return exactly what the old INNER JOIN returned. If these ever diverge, some
    row has an owner that disagrees with its character — which is the state the
    backfill script refuses to run against.
    """
    legacy_rows = (
        db_session.query(CharacterImage)
        .join(Character, CharacterImage.character_id == Character.id)
        .filter(
            Character.owner_id == library["user_id"],
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )
    legacy_ids = sorted(
        r.id for r in legacy_rows if not (r.metadata_json or {}).get("is_temp", False)
    )

    resp = client.get(
        "/users/me/character-images", headers=auth_headers(library["token"])
    )
    assert resp.status_code == 200, resp.text
    new_ids = sorted(r["id"] for r in resp.json())

    assert new_ids == legacy_ids
    assert new_ids == library["kept_ids"]


def test_library_ownership_resolves_without_a_character_join(db_session, library):
    """Forward-looking: ownership is answerable from the asset row alone.

    Deliberately at query level rather than through the route, and deliberately
    without making ``character_id`` nullable — that is Phase 4C. What is being
    proved here is only that the predicate no longer *needs* the join, so a row
    whose character association changes later cannot silently fall out of its
    owner's library.
    """
    owned = (
        db_session.query(CharacterImage)
        .filter(
            CharacterImage.user_id == library["user_id"],
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )
    ids = sorted(
        r.id for r in owned if not (r.metadata_json or {}).get("is_temp", False)
    )
    assert ids == library["kept_ids"]

    statement = str(
        db_session.query(CharacterImage)
        .filter(CharacterImage.user_id == library["user_id"])
        .statement.compile()
    )
    assert "characters" not in statement, (
        "ownership must not require the characters table"
    )


def test_library_still_honours_the_character_filter(client, library):
    resp = client.get(
        f"/users/me/character-images?character_id={library['shadow']}",
        headers=auth_headers(library["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert [r["character_id"] for r in resp.json()] == [library["shadow"]]


def test_library_still_honours_the_kind_filter(client, library):
    resp = client.get(
        "/users/me/character-images?kind=identity_face_ref",
        headers=auth_headers(library["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert {r["kind"] for r in resp.json()} == {"identity_face_ref"}


def test_library_still_paginates(client, library):
    hdrs = auth_headers(library["token"])
    page1 = client.get("/users/me/character-images?sort=oldest&limit=2", headers=hdrs)
    page2 = client.get(
        "/users/me/character-images?sort=oldest&limit=2&offset=2", headers=hdrs
    )
    assert [r["id"] for r in page1.json()] == library["kept_ids"][:2]
    assert [r["id"] for r in page2.json()] == library["kept_ids"][2:]


def test_library_excludes_another_accounts_assets(client, db_session, library):
    stranger = get_auth_token(client, email="stranger@ownership.example.com", username="ownstranger")
    stranger_char = _make_character(client, stranger, "Outsider")
    _seed_image(
        db_session,
        character_id=stranger_char,
        owner_id=_user_id(db_session, "stranger@ownership.example.com"),
        file_path="static/generated/o-outsider.png",
    )

    resp = client.get(
        "/users/me/character-images", headers=auth_headers(library["token"])
    )
    assert sorted(r["id"] for r in resp.json()) == library["kept_ids"]


def test_library_asks_the_character_only_for_the_character_filter(client, db_session, library):
    """Requesting someone else's character is still an error, not an empty list."""
    stranger = get_auth_token(client, email="probe@ownership.example.com", username="ownprobe")
    stranger_char = _make_character(client, stranger, "Probe Target")

    resp = client.get(
        f"/users/me/character-images?character_id={stranger_char}",
        headers=auth_headers(library["token"]),
    )
    assert resp.status_code == 403, resp.text


# ── source-image ownership on the avatar/cover routes ────────────────────────


@pytest.fixture
def crossed(client, db_session):
    """Two accounts, and one asset whose owner and character owner DISAGREE.

    No application path produces this row today — the backfill script treats a
    disagreement as a hard precondition failure — but it is the only shape that
    can distinguish "asked the asset" from "asked the character", which is the
    entire subject of this increment.
    """
    mine = _seeder_token(client, db_session, "mine@ownership.example.com", "ownmine")
    theirs = get_auth_token(client, email="theirs@ownership.example.com", username="owntheirs")
    my_id = _user_id(db_session, "mine@ownership.example.com")
    their_id = _user_id(db_session, "theirs@ownership.example.com")

    my_char = _make_character(client, mine, "My Character")
    their_char = _make_character(client, theirs, "Their Character")

    return {
        "my_token": mine,
        "my_id": my_id,
        "their_id": their_id,
        "my_char": my_char,
        "their_char": their_char,
        # Theirs, but hanging off MY character.
        "theirs_on_my_character": _seed_image(
            db_session, character_id=my_char, owner_id=their_id,
            file_path="static/generated/x-theirs-on-mine.png",
        ),
        # Mine, but hanging off THEIR character. Stored as an absolute URL so
        # the avatar route takes its object-storage branch — this test is about
        # the ownership verdict, not about cropping bytes off local disk.
        "mine_on_their_character": _seed_image(
            db_session, character_id=their_char, owner_id=my_id,
            file_path="https://media.example.com/x-mine-on-theirs.png",
        ),
    }


def test_account_avatar_refuses_an_asset_owned_by_someone_else(client, crossed):
    """Possession of the character must not launder ownership of the asset.

    Under the old rule this succeeded: the image hung off a character the caller
    owns, and the character was all the route asked about.
    """
    resp = client.post(
        "/users/me/avatar",
        json={"image_type": "character", "image_id": crossed["theirs_on_my_character"].id},
        headers=auth_headers(crossed["my_token"]),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Not your image"


def test_character_avatar_refuses_an_asset_owned_by_someone_else(client, crossed):
    resp = client.post(
        f"/characters/{crossed['my_char']}/avatar",
        json={"image_type": "character", "image_id": crossed["theirs_on_my_character"].id},
        headers=auth_headers(crossed["my_token"]),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Not your image"


def test_character_cover_refuses_an_asset_owned_by_someone_else(client, crossed):
    resp = client.post(
        f"/characters/{crossed['my_char']}/cover",
        json={"image_type": "character", "image_id": crossed["theirs_on_my_character"].id},
        headers=auth_headers(crossed["my_token"]),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Not your image"


def test_an_owned_asset_stays_owned_whatever_it_is_associated_with(client, crossed):
    """The definitional half: ownership is a fact about the asset.

    Accepted because ``user_id`` says the caller owns it, even though the
    character it is currently associated with belongs to someone else. This is
    not a new capability — nothing creates such a row today — it is what
    "authoritative ownership" means, and it is the property Phase 4C relies on
    when an asset has no character at all.
    """
    resp = client.post(
        "/users/me/avatar",
        json={"image_type": "character", "image_id": crossed["mine_on_their_character"].id},
        headers=auth_headers(crossed["my_token"]),
    )
    assert resp.status_code == 200, resp.text


def test_avatar_still_404s_for_an_image_that_does_not_exist(client, crossed):
    resp = client.post(
        "/users/me/avatar",
        json={"image_type": "character", "image_id": 999999},
        headers=auth_headers(crossed["my_token"]),
    )
    assert resp.status_code == 404, resp.text


def test_character_avatar_still_checks_the_target_character_separately(client, crossed):
    """Owning the SOURCE asset does not grant editing someone else's character."""
    mine_on_mine = crossed["mine_on_their_character"]
    resp = client.post(
        f"/characters/{crossed['their_char']}/avatar",
        json={"image_type": "character", "image_id": mine_on_mine.id},
        headers=auth_headers(crossed["my_token"]),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Not authorized"


# ── what must NOT widen ───────────────────────────────────────────────────────


def test_post_attachment_stays_scoped_to_the_acting_character(client, db_session, library):
    """Account-wide ownership must not leak into the post attachment rule.

    Both characters belong to one account and both images are owned by that
    account, so an account-scoped check would allow this. It must still fail:
    a post is authored by ONE character and may only carry that character's
    media.
    """
    hdrs = auth_headers(library["token"])
    realm = client.post(
        "/realms/",
        json={"name": "Ownership Realm", "slug": "ownership-realm", "is_public": True},
        headers=hdrs,
    )
    assert realm.status_code == 201, realm.text

    resp = client.post(
        f"/posts/realms/{realm.json()['id']}/posts",
        json={
            "content": "Pan posting Shadow's picture.",
            "character_id": library["pan"],
            "image_url": "/static/generated/o-shadow-1.png",
        },
        headers=hdrs,
    )
    assert resp.status_code == 403, resp.text


def test_character_gallery_stays_scoped_to_the_character(client, library):
    """``GET /characters/{id}/images`` is association, not ownership."""
    resp = client.get(
        f"/characters/{library['pan']}/images", headers=auth_headers(library["token"])
    )
    assert resp.status_code == 200, resp.text
    assert {r["character_id"] for r in resp.json()} == {library["pan"]}


# ── /images/ ─────────────────────────────────────────────────────────────────


def test_images_library_lists_only_the_callers_own_library_rows(client, db_session, library):
    uid = library["user_id"]
    mine = _seed_image(
        db_session, character_id=library["pan"], owner_id=uid,
        file_path="static/generated/o-lib-mine.png",
        metadata_json={"library": True},
    )
    # Same character, someone else's asset: association is not ownership.
    _seed_image(
        db_session, character_id=library["pan"],
        owner_id=_user_id(db_session, "owner@ownership.example.com") + 10_000,
        file_path="static/generated/o-lib-foreign.png",
        metadata_json={"library": True},
    )
    # Owned, but not a library row.
    _seed_image(
        db_session, character_id=library["pan"], owner_id=uid,
        file_path="static/generated/o-lib-notlibrary.png",
    )

    resp = client.get("/images/", headers=auth_headers(library["token"]))
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in resp.json()] == [mine.id]


def test_images_library_matches_the_old_character_scoped_result(client, db_session, library):
    """Equivalence on data where owner and character owner agree — i.e. today's."""
    uid = library["user_id"]
    _seed_image(
        db_session, character_id=library["pan"], owner_id=uid,
        file_path="static/generated/o-lib-a.png", metadata_json={"library": True},
    )
    _seed_image(
        db_session, character_id=library["shadow"], owner_id=uid,
        file_path="static/generated/o-lib-b.png", metadata_json={"library": True},
    )

    char_ids = [
        c.id for c in db_session.query(Character).filter(Character.owner_id == uid).all()
    ]
    legacy = (
        db_session.query(CharacterImage)
        .filter(
            CharacterImage.character_id.in_(char_ids),
            CharacterImage.metadata_json["library"].as_boolean() == True,  # noqa: E712
        )
        .all()
    )

    resp = client.get("/images/", headers=auth_headers(library["token"]))
    assert sorted(r["id"] for r in resp.json()) == sorted(r.id for r in legacy)
