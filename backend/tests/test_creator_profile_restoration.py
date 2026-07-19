"""Creator profile restoration (post-Sprint-33 product correction).

Creator/account profiles and character profiles are BOTH product surfaces:

  * read-only /users/{username}/* surfaces (profile, timeline, mentions,
    characters) are readable by any authenticated user;
  * mutation stays owner-scoped (/users/me/*) — no route mutates another
    account, and unauthenticated mutation is rejected;
  * character-first attribution is unchanged: character-attributed content
    still omits the author's account identity to non-author viewers;
  * legacy characterless content keeps @username attribution so the UI can
    link it to the creator profile; unknown identity stays a Wanderer.
"""
from app.models.post import Post as PostModel
from app.models.user import User as UserModel
from tests.conftest import get_auth_token, auth_headers


_CHAR = {"name": "Nyx", "species": "human", "short_bio": "A character."}


def _create_realm(client, token, name, slug):
    resp = client.post(
        "/realms/",
        json={"name": name, "slug": slug, "is_public": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_character(client, token, name="Nyx"):
    resp = client.post(
        "/characters/", json={**_CHAR, "name": name}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _user_id(db_session, email):
    return db_session.query(UserModel).filter(UserModel.email == email).first().id


def _insert_legacy_post(db_session, author_user_id, realm_id, content):
    """Insert a pre-Sprint-33 characterless (account-authored) post directly —
    the API no longer accepts characterless posts, but legacy rows exist."""
    post = PostModel(
        realm_id=realm_id,
        author_user_id=author_user_id,
        character_id=None,
        content=content,
    )
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)
    return post.id


def test_viewer_reads_another_creators_timeline(client, db_session):
    owner = get_auth_token(client, email="cpt_owner@test.com", username="cptowner")
    viewer = get_auth_token(client, email="cpt_viewer@test.com", username="cptviewer")
    from app.models.user import User

    db_session.query(User).filter(User.email == "cpt_owner@test.com").first().is_seeder = True
    db_session.commit()

    realm = _create_realm(client, owner, "CPTRealm", "cpt-realm")
    join = client.post(f"/realms/{realm}/join", headers=auth_headers(viewer))
    assert join.status_code in (200, 201, 204)

    char_id = _create_character(client, owner, name="Pan")
    resp = client.post(
        f"/posts/realms/{realm}/posts",
        json={"content": "Pan on the timeline", "character_id": char_id},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text

    items = client.get(
        "/users/cptowner/timeline", headers=auth_headers(viewer)
    ).json()
    assert any(
        i["payload"]["content"] == "Pan on the timeline" for i in items
    ), items
    # Character-first attribution holds inside the timeline payloads too.
    for i in items:
        if i["payload"].get("character_id") is not None:
            assert i["payload"].get("author_username") is None


def test_viewer_reads_mentions_and_characters_tabs(client, db_session):
    owner = get_auth_token(client, email="cpm_owner@test.com", username="cpmowner")
    viewer = get_auth_token(client, email="cpm_viewer@test.com", username="cpmviewer")

    m = client.get("/users/cpmowner/mentions", headers=auth_headers(viewer))
    assert m.status_code == 200
    assert isinstance(m.json(), list)

    c = client.get("/users/cpmowner/characters", headers=auth_headers(viewer))
    assert c.status_code == 200
    assert isinstance(c.json(), list)


def test_profile_mutation_remains_owner_scoped(client, db_session):
    owner = get_auth_token(client, email="cpe_owner@test.com", username="cpeowner")
    viewer = get_auth_token(client, email="cpe_viewer@test.com", username="cpeviewer")

    # A viewer's PATCH /users/me can only ever edit the viewer's own account.
    resp = client.patch(
        "/users/me",
        json={"display_name": "Hijacked?"},
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "cpeviewer"

    owner_profile = client.get(
        "/users/cpeowner", headers=auth_headers(owner)
    ).json()
    assert owner_profile.get("display_name") != "Hijacked?"

    # Unauthenticated mutation is rejected.
    anon = client.patch("/users/me", json={"display_name": "anon"})
    assert anon.status_code in (401, 403)


def test_legacy_characterless_post_keeps_creator_attribution(client, db_session):
    owner = get_auth_token(client, email="cpl_owner@test.com", username="cplowner")
    viewer = get_auth_token(client, email="cpl_viewer@test.com", username="cplviewer")

    realm = _create_realm(client, owner, "CPLRealm", "cpl-realm")
    join = client.post(f"/realms/{realm}/join", headers=auth_headers(viewer))
    assert join.status_code in (200, 201, 204)

    _insert_legacy_post(
        db_session, _user_id(db_session, "cpl_owner@test.com"), realm, "legacy words"
    )

    posts = client.get(
        f"/posts/realms/{realm}/posts", headers=auth_headers(viewer)
    ).json()
    legacy = [p for p in posts if p["content"] == "legacy words"]
    assert len(legacy) == 1
    # The creator identity is exposed so the UI can link to /u/cplowner...
    assert legacy[0]["author_username"] == "cplowner"
    # ...and it is genuinely characterless.
    assert legacy[0]["character_id"] is None


def test_character_post_still_hides_account_identity(client, db_session):
    owner = get_auth_token(client, email="cpc_owner@test.com", username="cpcowner")
    viewer = get_auth_token(client, email="cpc_viewer@test.com", username="cpcviewer")

    realm = _create_realm(client, owner, "CPCRealm", "cpc-realm")
    join = client.post(f"/realms/{realm}/join", headers=auth_headers(viewer))
    assert join.status_code in (200, 201, 204)

    char_id = _create_character(client, owner, name="Vella")
    resp = client.post(
        f"/posts/realms/{realm}/posts",
        json={"content": "in character", "character_id": char_id},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201, resp.text

    posts = client.get(
        f"/posts/realms/{realm}/posts", headers=auth_headers(viewer)
    ).json()
    char_posts = [p for p in posts if p["content"] == "in character"]
    assert len(char_posts) == 1
    assert char_posts[0]["character_id"] == char_id
    assert char_posts[0]["author_username"] is None
    assert char_posts[0]["author_user_id"] is None
