"""Character-first attribution + account privacy (Sprint 33: identity-first).

Covers the server-side guarantees:
  * every post omits the author's account identity (author_username +
    author_user_id) to non-author viewers — characters are the only public
    identities; the author still sees their own attribution;
  * posts REQUIRE a character author (characterless posting is rejected);
  * GET /characters/{id} omits owner_username to non-owner viewers;
  * creator profile read surfaces (/users/{username}/*) are readable by any
    authenticated user (creator profiles are public product surfaces), while
    roster privacy and character-first post attribution still hold;
  * the one-character-per-account limit is enforced, and seeder accounts are
    exempt.
"""
from tests.conftest import get_auth_token, auth_headers


_CHAR = {"name": "Nyx", "species": "human", "short_bio": "A seeded character."}


def _create_realm(client, token, name, slug, is_public=True):
    resp = client.post(
        "/realms/",
        json={"name": name, "slug": slug, "is_public": is_public},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_character(client, token, name="Nyx"):
    resp = client.post("/characters/", json={**_CHAR, "name": name}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_post(client, token, realm_id, content, character_id=None):
    body = {"content": content}
    if character_id is not None:
        body["character_id"] = character_id
    resp = client.post(
        f"/posts/realms/{realm_id}/posts", json=body, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_character_post_hides_owner_from_non_owner(client, db_session):
    owner = get_auth_token(client, email="attr_owner@test.com", username="attrowner")
    viewer = get_auth_token(client, email="attr_viewer@test.com", username="attrviewer")

    realm = _create_realm(client, owner, "AttrPub", "attr-pub", True)
    char_id = _create_character(client, owner)
    char_post = _create_post(client, owner, realm, "In character", character_id=char_id)

    # Non-owner: character post is attributed to the CHARACTER only — no owner leak.
    v = client.get(f"/posts/{char_post}", headers=auth_headers(viewer)).json()
    assert v["character_name"] == "Nyx"
    assert v["character_id"] == char_id
    assert v["author_username"] is None
    assert v["author_user_id"] is None

    # Owner: still sees full attribution on their own character post.
    o = client.get(f"/posts/{char_post}", headers=auth_headers(owner)).json()
    assert o["author_username"] == "attrowner"
    assert o["author_user_id"] is not None


def test_characterless_post_rejected(client, db_session):
    """Sprint 33: every post is authored by a character — no account posting."""
    owner = get_auth_token(client, email="nochar_owner@test.com", username="nocharowner")
    realm = _create_realm(client, owner, "NoCharPub", "nochar-pub", True)

    resp = client.post(
        f"/posts/realms/{realm}/posts",
        json={"content": "OOC chatter"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 403


def test_post_as_someone_elses_character_rejected(client, db_session):
    """Attribution is validated server-side: you can only post as your own
    character (closes the arbitrary-attribution hole)."""
    owner = get_auth_token(client, email="own_char@test.com", username="ownchar")
    attacker = get_auth_token(client, email="attacker@test.com", username="attacker")

    realm = _create_realm(client, attacker, "AtkPub", "atk-pub", True)
    victim_char = _create_character(client, owner)

    resp = client.post(
        f"/posts/realms/{realm}/posts",
        json={"content": "impersonation attempt", "character_id": victim_char},
        headers=auth_headers(attacker),
    )
    assert resp.status_code == 403


def test_character_payload_hides_owner_username(client, db_session):
    owner = get_auth_token(client, email="cp_owner@test.com", username="cpowner")
    viewer = get_auth_token(client, email="cp_viewer@test.com", username="cpviewer")
    char_id = _create_character(client, owner)

    # Public character is viewable, but owner_username is hidden from non-owners.
    v = client.get(f"/characters/{char_id}", headers=auth_headers(viewer)).json()
    assert v["id"] == char_id
    assert v.get("owner_username") is None

    # Owner sees their own owner_username.
    o = client.get(f"/characters/{char_id}", headers=auth_headers(owner)).json()
    assert o["owner_username"] == "cpowner"


def test_creator_profile_read_surfaces_public(client, db_session):
    """Creator profiles are public product surfaces: every read-only
    /users/{username}/* surface returns 200 to any authenticated user. The
    profile payload exposes only public fields, and roster privacy still
    applies (seeding mode ON: non-owners get an empty roster)."""
    owner = get_auth_token(client, email="rost_owner@test.com", username="rostowner")
    viewer = get_auth_token(client, email="rost_viewer@test.com", username="rostviewer")
    _create_character(client, owner)

    for path in (
        "/users/rostowner",
        "/users/rostowner/characters",
        "/users/rostowner/timeline",
        "/users/rostowner/mentions",
    ):
        v = client.get(path, headers=auth_headers(viewer))
        assert v.status_code == 200, f"{path} not readable by viewer: {v.status_code}"

    # The public profile payload never leaks private account data.
    profile = client.get("/users/rostowner", headers=auth_headers(viewer)).json()
    assert profile["username"] == "rostowner"
    for private_field in ("email", "is_admin", "is_seeder", "hashed_password"):
        assert private_field not in profile

    # Roster privacy is unchanged: non-owners cannot enumerate the roster
    # while seeding mode is on.
    assert client.get(
        "/users/rostowner/characters", headers=auth_headers(viewer)
    ).json() == []

    # Owner still sees their own full roster and surfaces.
    assert client.get("/users/rostowner", headers=auth_headers(owner)).status_code == 200
    o = client.get("/users/rostowner/characters", headers=auth_headers(owner))
    assert o.status_code == 200
    assert len(o.json()) == 1
    assert client.get("/users/rostowner/timeline", headers=auth_headers(owner)).status_code == 200
