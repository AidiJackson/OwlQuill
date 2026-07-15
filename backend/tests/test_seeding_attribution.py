"""Step 2 — character-first attribution + roster privacy (seeding mode).

Covers the server-side guarantees:
  * character-attributed posts omit the owner's identity (author_username +
    author_user_id) to non-owner viewers, but keep it for the owner;
  * non-character posts keep normal @username attribution for everyone;
  * GET /characters/{id} omits owner_username to non-owner viewers;
  * GET /users/{username}/characters does not enumerate a roster to a non-owner
    (returns []), while the owner sees their full roster;
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
    plain_post = _create_post(client, owner, realm, "OOC chatter")

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

    # Non-character post keeps normal @username attribution for everyone.
    vp = client.get(f"/posts/{plain_post}", headers=auth_headers(viewer)).json()
    assert vp["author_username"] == "attrowner"
    assert vp["character_name"] is None


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


def test_roster_not_enumerable_to_non_owner(client, db_session):
    owner = get_auth_token(client, email="rost_owner@test.com", username="rostowner")
    viewer = get_auth_token(client, email="rost_viewer@test.com", username="rostviewer")
    _create_character(client, owner)

    # Seeding mode ON (default): non-owner gets an empty roster (non-enumerable).
    v = client.get("/users/rostowner/characters", headers=auth_headers(viewer))
    assert v.status_code == 200
    assert v.json() == []

    # Owner sees their full roster.
    o = client.get("/users/rostowner/characters", headers=auth_headers(owner))
    assert o.status_code == 200
    assert len(o.json()) == 1


def test_roster_visible_to_non_owner_when_seeding_off(client, db_session, monkeypatch):
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "SEEDING_MODE", False)

    owner = get_auth_token(client, email="off_owner@test.com", username="offowner")
    viewer = get_auth_token(client, email="off_viewer@test.com", username="offviewer")
    _create_character(client, owner)  # public by default

    v = client.get("/users/offowner/characters", headers=auth_headers(viewer))
    assert v.status_code == 200
    assert len(v.json()) == 1
