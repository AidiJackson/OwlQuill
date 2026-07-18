"""Sprint 33 — identity-first foundation.

Covers:
  * /auth/me identity context: is_seeder, character_count, active_character
    (explicit selection, single-character fallback, null cases);
  * PATCH /users/me/active-character: owner validation, clearing, 404 on
    non-owned/nonexistent characters;
  * Wanderer comments: zero-character accounts may leave short identity-less
    comments; accounts with characters must comment as an owned character;
  * GET /characters/{id}/posts: character-only timeline, account identity
    stripped for non-authors;
  * GET /characters/{id}/images: owner sees ACTIVE non-temp, others only
    PUBLIC-visibility images; private characters 404;
  * mentions resolve to public characters only — usernames stay unresolved.
"""
from tests.conftest import get_auth_token, auth_headers


_CHAR = {"name": "Pan", "species": "human", "short_bio": "A founding character."}


def _create_character(client, token, name="Pan"):
    resp = client.post(
        "/characters/", json={**_CHAR, "name": name}, headers=auth_headers(token)
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


def _me(client, token):
    resp = client.get("/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── /auth/me identity context ────────────────────────────────────────────


def test_me_reports_zero_characters(client, db_session):
    token = get_auth_token(client, email="wanderer@test.com", username="wanderer1")
    me = _me(client, token)
    assert me["character_count"] == 0
    assert me["active_character"] is None
    assert me["is_seeder"] is False


def test_me_single_character_fallback(client, db_session):
    token = get_auth_token(client, email="solo@test.com", username="solo1")
    char_id = _create_character(client, token)
    me = _me(client, token)
    assert me["character_count"] == 1
    assert me["active_character"] is not None
    assert me["active_character"]["id"] == char_id
    assert me["active_character"]["name"] == "Pan"


def test_me_is_seeder_flag(client, db_session):
    token = get_auth_token(client, email="seedy@test.com", username="seedy1")
    from app.models.user import User

    user = db_session.query(User).filter(User.email == "seedy@test.com").first()
    user.is_seeder = True
    db_session.commit()
    me = _me(client, token)
    assert me["is_seeder"] is True


def test_me_is_seeder_via_email_config(client, db_session, monkeypatch):
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "SEEDER_EMAILS", "listed@test.com")
    token = get_auth_token(client, email="listed@test.com", username="listed1")
    me = _me(client, token)
    assert me["is_seeder"] is True


# ── Active character selection ───────────────────────────────────────────


def test_set_active_character_and_multi_char_resolution(client, db_session):
    token = get_auth_token(client, email="founder@test.com", username="founder1")
    from app.models.user import User

    user = db_session.query(User).filter(User.email == "founder@test.com").first()
    user.is_seeder = True
    db_session.commit()

    first = _create_character(client, token, name="Pan")
    second = _create_character(client, token, name="Summer")

    # Multi-character account with no selection: no implicit active character.
    me = _me(client, token)
    assert me["character_count"] == 2
    assert me["active_character"] is None

    # Select the second character.
    resp = client.patch(
        "/users/me/active-character",
        json={"character_id": second},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["active_character"]["id"] == second
    assert resp.json()["active_character"]["name"] == "Summer"

    # Switch to the first.
    resp = client.patch(
        "/users/me/active-character",
        json={"character_id": first},
        headers=auth_headers(token),
    )
    assert resp.json()["active_character"]["id"] == first

    # Clear the selection.
    resp = client.patch(
        "/users/me/active-character",
        json={"character_id": None},
        headers=auth_headers(token),
    )
    assert resp.json()["active_character"] is None


def test_set_active_character_rejects_non_owned(client, db_session):
    owner = get_auth_token(client, email="aco@test.com", username="aco1")
    other = get_auth_token(client, email="acx@test.com", username="acx1")
    victim_char = _create_character(client, owner)

    resp = client.patch(
        "/users/me/active-character",
        json={"character_id": victim_char},
        headers=auth_headers(other),
    )
    assert resp.status_code == 404

    resp = client.patch(
        "/users/me/active-character",
        json={"character_id": 999999},
        headers=auth_headers(other),
    )
    assert resp.status_code == 404


def test_delete_active_character_clears_selection(client, db_session):
    token = get_auth_token(client, email="delac@test.com", username="delac1")
    char_id = _create_character(client, token)
    client.patch(
        "/users/me/active-character",
        json={"character_id": char_id},
        headers=auth_headers(token),
    )
    resp = client.delete(f"/characters/{char_id}", headers=auth_headers(token))
    assert resp.status_code == 204
    me = _me(client, token)
    assert me["active_character"] is None
    assert me["character_count"] == 0


# ── Wanderer comments ────────────────────────────────────────────────────


def test_wanderer_short_comment_allowed_and_identityless(client, db_session):
    author = get_auth_token(client, email="cauth@test.com", username="cauth1")
    wanderer = get_auth_token(client, email="wand@test.com", username="wand1")

    realm = _create_realm(client, author, "CommentRealm", "comment-realm")
    char_id = _create_character(client, author)
    post_id = _create_post(client, author, realm, "hello world", char_id)

    resp = client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "lovely post!"},
        headers=auth_headers(wanderer),
    )
    assert resp.status_code == 201, resp.text

    # The comment is identity-less to other viewers (including the post author).
    listed = client.get(
        f"/comments/posts/{post_id}/comments", headers=auth_headers(author)
    ).json()
    assert len(listed) == 1
    assert listed[0]["author_username"] is None
    assert listed[0]["author_user_id"] is None
    assert listed[0]["character_name"] is None


def test_wanderer_long_comment_rejected(client, db_session):
    author = get_auth_token(client, email="cauth2@test.com", username="cauth2")
    wanderer = get_auth_token(client, email="wand2@test.com", username="wand2")

    realm = _create_realm(client, author, "CommentRealm2", "comment-realm-2")
    char_id = _create_character(client, author)
    post_id = _create_post(client, author, realm, "hello again", char_id)

    resp = client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "x" * 1001},
        headers=auth_headers(wanderer),
    )
    assert resp.status_code == 403


def test_character_owner_must_comment_as_character(client, db_session):
    author = get_auth_token(client, email="cauth3@test.com", username="cauth3")
    commenter = get_auth_token(client, email="ccom3@test.com", username="ccom3")

    realm = _create_realm(client, author, "CommentRealm3", "comment-realm-3")
    author_char = _create_character(client, author)
    post_id = _create_post(client, author, realm, "third post", author_char)
    commenter_char = _create_character(client, commenter, name="Shadow")

    # Characterless comment rejected for an account that owns a character.
    resp = client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "no identity"},
        headers=auth_headers(commenter),
    )
    assert resp.status_code == 403

    # Commenting as someone else's character rejected.
    resp = client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "impersonation", "character_id": author_char},
        headers=auth_headers(commenter),
    )
    assert resp.status_code == 403

    # Commenting as their own character succeeds and is character-attributed.
    resp = client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "as Shadow", "character_id": commenter_char},
        headers=auth_headers(commenter),
    )
    assert resp.status_code == 201, resp.text
    listed = client.get(
        f"/comments/posts/{post_id}/comments", headers=auth_headers(author)
    ).json()
    assert listed[-1]["character_name"] == "Shadow"
    assert listed[-1]["author_username"] is None


# ── Character profile endpoints ──────────────────────────────────────────


def test_character_posts_timeline(client, db_session):
    owner = get_auth_token(client, email="tl@test.com", username="tlowner")
    viewer = get_auth_token(client, email="tlv@test.com", username="tlviewer")
    from app.models.user import User

    user = db_session.query(User).filter(User.email == "tl@test.com").first()
    user.is_seeder = True
    db_session.commit()

    realm = _create_realm(client, owner, "TLRealm", "tl-realm")
    # Viewer joins the realm so its posts are visible to them.
    join = client.post(f"/realms/{realm}/join", headers=auth_headers(viewer))
    assert join.status_code in (200, 201, 204), join.text

    pan = _create_character(client, owner, name="Pan")
    summer = _create_character(client, owner, name="Summer")
    _create_post(client, owner, realm, "Pan speaks", pan)
    _create_post(client, owner, realm, "Summer speaks", summer)

    items = client.get(
        f"/characters/{pan}/posts", headers=auth_headers(viewer)
    ).json()
    assert len(items) == 1
    payload = items[0]["payload"]
    assert payload["content"] == "Pan speaks"
    assert payload["character_name"] == "Pan"
    # Account identity stripped for the non-author viewer.
    assert payload["author_username"] is None
    assert payload["author_user_id"] is None
    # No cross-character bleed: Summer's post is absent from Pan's timeline.
    assert all(i["payload"]["character_id"] == pan for i in items)


def test_character_media_library_visible_on_public_character(client, db_session):
    """The media surface (existing /characters/{id}/images route) serves a
    PUBLIC character's active non-temp images to any viewer — Wanderers may
    browse image libraries."""
    owner = get_auth_token(client, email="img@test.com", username="imgowner")
    viewer = get_auth_token(client, email="imgv@test.com", username="imgviewer")
    char_id = _create_character(client, owner)

    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
    )

    db_session.add_all([
        CharacterImage(
            character_id=char_id,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            file_path="/static/generated/one.png",
        ),
        CharacterImage(
            character_id=char_id,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            file_path="/static/generated/temp.png",
            metadata_json={"is_temp": True},
        ),
    ])
    db_session.commit()

    mine = client.get(f"/characters/{char_id}/images", headers=auth_headers(owner)).json()
    assert len(mine) == 1  # temp image excluded

    theirs = client.get(f"/characters/{char_id}/images", headers=auth_headers(viewer)).json()
    assert len(theirs) == 1


def test_private_character_endpoints_hidden(client, db_session):
    owner = get_auth_token(client, email="priv@test.com", username="privowner")
    viewer = get_auth_token(client, email="privv@test.com", username="privviewer")
    resp = client.post(
        "/characters/",
        json={**_CHAR, "visibility": "private"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201
    char_id = resp.json()["id"]

    # New timeline endpoint: 404 (indistinguishable from nonexistent).
    assert client.get(
        f"/characters/{char_id}/posts", headers=auth_headers(viewer)
    ).status_code == 404
    # Existing media endpoint keeps its established 403 contract.
    assert client.get(
        f"/characters/{char_id}/images", headers=auth_headers(viewer)
    ).status_code == 403


# ── Mentions are character-only ──────────────────────────────────────────


def test_mentions_resolve_characters_not_usernames(client, db_session):
    author = get_auth_token(client, email="ment@test.com", username="mentauthor")
    get_auth_token(client, email="target@test.com", username="targetuser")

    realm = _create_realm(client, author, "MentRealm", "ment-realm")
    char_id = _create_character(client, author, name="Bella")

    post_id = _create_post(
        client, author, realm, "hi @Bella and hi @targetuser", char_id
    )
    post = client.get(f"/posts/{post_id}", headers=auth_headers(author)).json()
    mentions = {m["mention_text"].lower(): m for m in post["mentions"]}

    # Character mention resolves and links to the character page.
    assert mentions["@bella"]["url"] == f"/characters/{char_id}"
    # Username mention stays unresolved — no link, no existence confirmation.
    assert mentions["@targetuser"]["url"] == ""
    assert mentions["@targetuser"]["target_id"] is None
