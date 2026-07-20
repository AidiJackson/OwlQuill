"""Character-first public identity — directory & mentions surfaces.

Covers the two endpoints added for the public character profile:
  * GET /characters/directory: PUBLIC characters only, no owner fields in the
    payload (the directory cannot cluster characters by account);
  * GET /characters/{id}/mentions: posts mentioning the character, restricted
    to realms the viewer can see, account identity stripped for non-authors.
"""
from tests.conftest import get_auth_token, auth_headers


def _create_character(client, token, name, visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_realm(client, token, name, slug):
    resp = client.post(
        "/realms/",
        json={"name": name, "slug": slug, "is_public": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_post(client, token, realm_id, content, character_id):
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "character_id": character_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_seeder(db_session, email):
    from app.models.user import User

    user = db_session.query(User).filter(User.email == email).first()
    user.is_seeder = True
    db_session.commit()


# ── GET /characters/directory ────────────────────────────────────────────


def test_directory_lists_public_characters_without_owner_fields(client, db_session):
    owner = get_auth_token(client, email="dir-owner@test.com", username="dirowner")
    _make_seeder(db_session, "dir-owner@test.com")
    viewer = get_auth_token(client, email="dir-viewer@test.com", username="dirviewer")

    _create_character(client, owner, "Summer")
    _create_character(client, owner, "Pan")
    _create_character(client, owner, "Shadow", visibility="private")

    resp = client.get("/characters/directory", headers=auth_headers(viewer))
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    names = {e["name"] for e in entries}
    assert {"Summer", "Pan"} <= names
    # Private characters never appear in the public directory.
    assert "Shadow" not in names
    # No owner/account fields anywhere in the payload — the directory must not
    # allow clustering characters by their owning account.
    for entry in entries:
        assert "owner_id" not in entry
        assert "owner_username" not in entry


def test_directory_requires_authentication(client, db_session):
    resp = client.get("/characters/directory")
    assert resp.status_code in (401, 403)


# ── GET /characters/{id}/mentions ────────────────────────────────────────


def test_character_mentions_surface(client, db_session):
    owner = get_auth_token(client, email="men-owner@test.com", username="menowner")
    _make_seeder(db_session, "men-owner@test.com")
    viewer = get_auth_token(client, email="men-viewer@test.com", username="menviewer")

    realm = _create_realm(client, owner, "MentionRealm", "mention-realm")
    join = client.post(f"/realms/{realm}/join", headers=auth_headers(viewer))
    assert join.status_code in (200, 201, 204), join.text

    summer = _create_character(client, owner, "Summer")
    pan = _create_character(client, owner, "Pan")
    _create_post(client, owner, realm, "Pan waves at @Summer across the square.", pan)
    _create_post(client, owner, realm, "Pan talks to no one.", pan)

    resp = client.get(
        f"/characters/{summer}/mentions", headers=auth_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    payload = items[0]["payload"]
    assert "@Summer" in payload["content"]
    # Attribution is the authoring CHARACTER; account identity is stripped for
    # the non-author viewer.
    assert payload["character_name"] == "Pan"
    assert payload["author_username"] is None
    assert payload["author_user_id"] is None


def test_private_character_mentions_hidden_from_non_owner(client, db_session):
    owner = get_auth_token(client, email="pm-owner@test.com", username="pmowner")
    viewer = get_auth_token(client, email="pm-viewer@test.com", username="pmviewer")

    hidden = _create_character(client, owner, "Hidden", visibility="private")

    resp = client.get(
        f"/characters/{hidden}/mentions", headers=auth_headers(viewer)
    )
    assert resp.status_code == 404
