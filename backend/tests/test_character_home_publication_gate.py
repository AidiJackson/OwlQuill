"""Character Home Step 2 — the controlled publication gate.

``visibility == PUBLIC`` does not by itself publish a Character Home. Publication
requires PUBLIC visibility AND the founder-granted ``public_home_enabled`` flag,
and these tests pin all four corners of that conjunction plus the two ways the
flag can be set (founder only) and cannot be set (ordinary character update).

They also pin what must NOT change: the authenticated ``GET /characters/{id}``
contract and ordinary owner workflows are not gated by the new flag.
"""
import pytest

from app.models.character import Character, VisibilityEnum
from app.models.user import User
from app.services.character_publication import character_home_is_publishable
from tests.conftest import auth_headers, get_auth_token


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_character(client, token, name, visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_admin(db_session, email):
    user = db_session.query(User).filter(User.email == email).first()
    assert user is not None, f"no such fixture user: {email}"
    user.is_admin = True
    db_session.commit()
    return user


def _row(db_session, character_id) -> Character:
    db_session.expire_all()
    return db_session.query(Character).filter(Character.id == character_id).first()


# ── A. Default is false ───────────────────────────────────────────────────────

def test_new_character_defaults_to_not_publishable(client, db_session):
    """A character created through the ordinary API is never born published."""
    token = get_auth_token(client, email="phe-new@test.com", username="phenew")
    character_id = _create_character(client, token, "Summer")

    row = _row(db_session, character_id)
    assert row.public_home_enabled is False
    assert row.visibility == VisibilityEnum.PUBLIC
    assert character_home_is_publishable(row) is False


def test_model_default_is_false_without_explicit_value(db_session):
    """The Python-side default applies to a row constructed without the field.

    This is the path a migrated pre-Step-2 row takes: the column exists, nothing
    set it, and it must read false rather than NULL.
    """
    user = User(
        email="phe-default@test.com",
        username="phedefault",
        hashed_password="x",
    )
    db_session.add(user)
    db_session.commit()

    character = Character(owner_id=user.id, name="Unset", visibility=VisibilityEnum.PUBLIC)
    db_session.add(character)
    db_session.commit()
    db_session.refresh(character)

    assert character.public_home_enabled is False
    assert character_home_is_publishable(character) is False


# ── B. The predicate: all four corners ────────────────────────────────────────

@pytest.mark.parametrize(
    "visibility,enabled,expected",
    [
        (VisibilityEnum.PUBLIC, True, True),
        (VisibilityEnum.PUBLIC, False, False),
        (VisibilityEnum.PRIVATE, True, False),
        (VisibilityEnum.PRIVATE, False, False),
    ],
)
def test_publishable_requires_both_public_and_enabled(
    client, db_session, visibility, enabled, expected
):
    token = get_auth_token(client, email="phe-pred@test.com", username="phepred")
    character_id = _create_character(client, token, "Corner")

    row = _row(db_session, character_id)
    row.visibility = visibility
    row.public_home_enabled = enabled
    db_session.commit()

    assert character_home_is_publishable(_row(db_session, character_id)) is expected


def test_friends_visibility_is_not_publishable_even_when_enabled(client, db_session):
    """FRIENDS is not PUBLIC; the flag does not promote it."""
    token = get_auth_token(client, email="phe-friends@test.com", username="phefriends")
    character_id = _create_character(client, token, "Friendly")

    row = _row(db_session, character_id)
    row.visibility = VisibilityEnum.FRIENDS
    row.public_home_enabled = True
    db_session.commit()

    assert character_home_is_publishable(_row(db_session, character_id)) is False


def test_publishable_is_false_for_missing_character(db_session):
    assert character_home_is_publishable(None) is False


# ── C. Founder control ────────────────────────────────────────────────────────

def test_admin_can_enable_public_home(client, db_session):
    owner = get_auth_token(client, email="phe-owner@test.com", username="pheowner")
    character_id = _create_character(client, owner, "Summer")

    admin = get_auth_token(client, email="phe-admin@test.com", username="pheadmin")
    _make_admin(db_session, "phe-admin@test.com")

    resp = client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["character_id"] == character_id
    assert body["public_home_enabled"] is True
    assert body["publishable"] is True

    assert _row(db_session, character_id).public_home_enabled is True


def test_admin_can_disable_public_home(client, db_session):
    owner = get_auth_token(client, email="phe-owner2@test.com", username="pheowner2")
    character_id = _create_character(client, owner, "Summer")

    admin = get_auth_token(client, email="phe-admin2@test.com", username="pheadmin2")
    _make_admin(db_session, "phe-admin2@test.com")

    client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
        headers=auth_headers(admin),
    )
    resp = client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": False},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_home_enabled"] is False
    assert resp.json()["publishable"] is False

    assert _row(db_session, character_id).public_home_enabled is False


def test_admin_enable_on_private_character_does_not_make_it_publishable(client, db_session):
    """The founder may grant permission; permission still does not beat privacy."""
    owner = get_auth_token(client, email="phe-priv@test.com", username="phepriv")
    character_id = _create_character(client, owner, "Shadow", visibility="private")

    admin = get_auth_token(client, email="phe-admin3@test.com", username="pheadmin3")
    _make_admin(db_session, "phe-admin3@test.com")

    resp = client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_home_enabled"] is True
    assert resp.json()["publishable"] is False


def test_non_admin_cannot_enable_public_home(client, db_session):
    """Including the character's own owner — self-publication is not available."""
    owner = get_auth_token(client, email="phe-selfpub@test.com", username="pheselfpub")
    character_id = _create_character(client, owner, "Summer")

    resp = client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 403, resp.text
    assert _row(db_session, character_id).public_home_enabled is False


def test_anonymous_cannot_enable_public_home(client, db_session):
    owner = get_auth_token(client, email="phe-anon@test.com", username="pheanon")
    character_id = _create_character(client, owner, "Summer")

    resp = client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
    )
    assert resp.status_code in (401, 403), resp.text
    assert _row(db_session, character_id).public_home_enabled is False


def test_admin_public_home_unknown_character_404(client, db_session):
    admin = get_auth_token(client, email="phe-admin4@test.com", username="pheadmin4")
    _make_admin(db_session, "phe-admin4@test.com")

    resp = client.post(
        "/admin/characters/999999/public-home",
        json={"enabled": True},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 404, resp.text


# ── D. The ordinary update path cannot reach the flag ─────────────────────────

def test_character_patch_cannot_set_public_home_enabled(client, db_session):
    """An owner PATCHing the field is ignored, not honoured — and not an error
    that would tell them a flag exists."""
    owner = get_auth_token(client, email="phe-patch@test.com", username="phepatch")
    character_id = _create_character(client, owner, "Summer")

    resp = client.patch(
        f"/characters/{character_id}",
        json={"short_bio": "updated", "public_home_enabled": True},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["short_bio"] == "updated"
    assert _row(db_session, character_id).public_home_enabled is False


def test_character_create_cannot_set_public_home_enabled(client, db_session):
    owner = get_auth_token(client, email="phe-create@test.com", username="phecreate")
    resp = client.post(
        "/characters/",
        json={"name": "Sneaky", "species": "human", "public_home_enabled": True},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text
    assert _row(db_session, resp.json()["id"]).public_home_enabled is False


def test_admin_grant_survives_a_subsequent_owner_patch(client, db_session):
    """A creator editing their character does not silently revoke the grant
    either — the flag is not part of that payload in either direction."""
    owner = get_auth_token(client, email="phe-keep@test.com", username="phekeep")
    character_id = _create_character(client, owner, "Summer")

    admin = get_auth_token(client, email="phe-admin5@test.com", username="pheadmin5")
    _make_admin(db_session, "phe-admin5@test.com")
    client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
        headers=auth_headers(admin),
    )

    resp = client.patch(
        f"/characters/{character_id}",
        json={"short_bio": "edited"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    assert _row(db_session, character_id).public_home_enabled is True


# ── E. Exposure ───────────────────────────────────────────────────────────────

def test_flag_is_not_serialized_to_character_readers(client, db_session):
    """Neither the owner nor another viewer receives the raw flag.

    Founder control reads it back from the admin endpoint; nobody else needs it,
    so it stays off the character payload entirely.
    """
    owner = get_auth_token(client, email="phe-exp@test.com", username="pheexp")
    character_id = _create_character(client, owner, "Summer")

    admin = get_auth_token(client, email="phe-admin6@test.com", username="pheadmin6")
    _make_admin(db_session, "phe-admin6@test.com")
    client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
        headers=auth_headers(admin),
    )

    viewer = get_auth_token(client, email="phe-viewer@test.com", username="pheviewer")
    for token in (owner, viewer):
        resp = client.get(f"/characters/{character_id}", headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        assert "public_home_enabled" not in resp.json()

    listing = client.get("/characters/", headers=auth_headers(owner))
    assert listing.status_code == 200, listing.text
    assert all("public_home_enabled" not in c for c in listing.json())

    directory = client.get("/characters/directory", headers=auth_headers(viewer))
    assert directory.status_code == 200, directory.text
    assert all("public_home_enabled" not in c for c in directory.json())


# ── F. Existing behaviour is not newly gated ──────────────────────────────────

def test_authenticated_get_character_unchanged_when_flag_is_false(client, db_session):
    """A PUBLIC character with the flag false is still fully readable by a
    signed-in stranger. The gate governs the anonymous Home, nothing else."""
    owner = get_auth_token(client, email="phe-compat@test.com", username="phecompat")
    character_id = _create_character(client, owner, "Summer")
    viewer = get_auth_token(client, email="phe-compat2@test.com", username="phecompat2")

    assert _row(db_session, character_id).public_home_enabled is False

    resp = client.get(f"/characters/{character_id}", headers=auth_headers(viewer))
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Summer"
    # Non-owner still gets no account link — the S24D policy, untouched.
    assert resp.json()["owner_username"] is None


def test_private_character_still_404s_for_strangers_regardless_of_flag(client, db_session):
    owner = get_auth_token(client, email="phe-p1@test.com", username="phep1")
    character_id = _create_character(client, owner, "Shadow", visibility="private")
    viewer = get_auth_token(client, email="phe-p2@test.com", username="phep2")

    admin = get_auth_token(client, email="phe-admin7@test.com", username="pheadmin7")
    _make_admin(db_session, "phe-admin7@test.com")
    client.post(
        f"/admin/characters/{character_id}/public-home",
        json={"enabled": True},
        headers=auth_headers(admin),
    )

    assert client.get(
        f"/characters/{character_id}", headers=auth_headers(viewer)
    ).status_code == 404
    # The owner still sees their own private character.
    assert client.get(
        f"/characters/{character_id}", headers=auth_headers(owner)
    ).status_code == 200


def test_owner_workflows_are_not_gated_by_the_flag(client, db_session):
    """Read, list and update all work on a character with the flag false."""
    owner = get_auth_token(client, email="phe-own@test.com", username="pheown")
    character_id = _create_character(client, owner, "Summer")
    assert _row(db_session, character_id).public_home_enabled is False

    assert client.get(
        f"/characters/{character_id}", headers=auth_headers(owner)
    ).status_code == 200
    assert client.get("/characters/", headers=auth_headers(owner)).status_code == 200
    assert client.get(
        f"/characters/{character_id}/posts", headers=auth_headers(owner)
    ).status_code == 200
    assert client.patch(
        f"/characters/{character_id}",
        json={"short_bio": "still editable"},
        headers=auth_headers(owner),
    ).status_code == 200


def test_anonymous_images_endpoint_behaviour_is_unchanged(client, db_session):
    """Pre-existing endpoint, deliberately not moved onto the new predicate:
    a PUBLIC character with the flag false still serves it anonymously."""
    owner = get_auth_token(client, email="phe-img@test.com", username="pheimg")
    character_id = _create_character(client, owner, "Summer")
    assert _row(db_session, character_id).public_home_enabled is False

    resp = client.get(f"/characters/{character_id}/images")
    assert resp.status_code == 200, resp.text
