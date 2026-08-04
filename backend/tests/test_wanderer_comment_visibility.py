"""A Wanderer's comment is visible to everyone who can see the parent post.

The reported failure was that a Wanderer's comment on a founder's Commons post
"disappeared" when the founder looked at it. The comment was never actually
lost or filtered — the collapsed comment control simply had no count to show,
because the count was derived from comments that are only fetched once the
section is expanded. These tests pin both halves down:

* the API returns the comment identically to every viewer entitled to the post
  (author, founder, an unrelated Wanderer, and anonymous), and
* the parent post carries a ``comment_count`` so a collapsed control can
  announce the comment before anyone fetches it.

They also re-assert the attribution rules the visibility fix must not weaken:
a Wanderer is named, a Writer's private account username is not, and a private
realm's comments stay private.
"""
from tests.conftest import (
    auth_headers,
    ensure_character,
    get_auth_token,
    grant_writer_unlock,
    make_admin,
)


def _realm(client, token: str, slug: str, is_public: bool = True) -> int:
    resp = client.post(
        "/realms/",
        json={"name": f"Realm {slug}", "slug": slug, "is_public": is_public},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _post(client, token: str, realm_id: int, character_id: int | None = None) -> int:
    body = {"content": "A post to comment on.", "content_type": "ooc"}
    if character_id is not None:
        body["character_id"] = character_id
    resp = client.post(
        f"/posts/realms/{realm_id}/posts", json=body, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _comments(client, post_id: int, token: str | None = None) -> list[dict]:
    headers = auth_headers(token) if token else {}
    resp = client.get(f"/comments/posts/{post_id}/comments", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _founder_with_post(client) -> tuple[str, int, int]:
    """A founder who owns a character and a public-realm post. Returns
    (token, realm_id, post_id)."""
    founder = get_auth_token(client, email="founder@test.com", username="the_founder")
    make_admin("founder@test.com")
    char_id = ensure_character(client, founder, name="Pan")
    realm_id = _realm(client, founder, "commons")
    return founder, realm_id, _post(client, founder, realm_id, character_id=char_id)


# ── The reported bug ─────────────────────────────────────────────────────────

def test_wanderer_can_comment_and_every_entitled_viewer_sees_it(client):
    """1-4: the Wanderer creates it, and the Wanderer, the founder, another
    Wanderer and an anonymous reader all see the same comment."""
    founder, realm_id, post_id = _founder_with_post(client)

    wanderer = get_auth_token(client, email="w1@test.com", username="wanderer_one")
    created = client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "That's a lot hehe"},
        headers=auth_headers(wanderer),
    )
    assert created.status_code == 201, created.text
    comment_id = created.json()["id"]

    other = get_auth_token(client, email="w2@test.com", username="wanderer_two")

    for label, token in (
        ("author", wanderer),
        ("founder", founder),
        ("other wanderer", other),
        ("anonymous", None),
    ):
        visible = _comments(client, post_id, token)
        assert [c["id"] for c in visible] == [comment_id], (
            f"{label} could not see the Wanderer's comment"
        )
        assert visible[0]["content"] == "That's a lot hehe"


def test_parent_post_reports_its_comment_count(client):
    """The count travels with the post, so a collapsed comment control can say
    a comment exists without fetching it first. This is the actual regression:
    without it the founder saw a bare "Comments" and assumed there were none."""
    founder, realm_id, post_id = _founder_with_post(client)

    feed = client.get(f"/posts/realms/{realm_id}/posts", headers=auth_headers(founder))
    assert feed.status_code == 200, feed.text
    assert [p["comment_count"] for p in feed.json() if p["id"] == post_id] == [0]

    wanderer = get_auth_token(client, email="w1@test.com", username="wanderer_one")
    client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "That's a lot hehe"},
        headers=auth_headers(wanderer),
    )

    feed = client.get(f"/posts/realms/{realm_id}/posts", headers=auth_headers(founder))
    assert [p["comment_count"] for p in feed.json() if p["id"] == post_id] == [1], (
        "the founder's feed must report the Wanderer's comment"
    )


# ── Attribution: named Wanderer, unnamed Writer ──────────────────────────────

def test_wanderer_comment_carries_username_and_sigil_for_every_viewer(client):
    """5: the Wanderer username and account sigil ARE the public identity of a
    characterless account, so they are sent to the author and to others alike."""
    founder, _realm_id, post_id = _founder_with_post(client)
    wanderer = get_auth_token(client, email="w1@test.com", username="wanderer_one")
    client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "Hello from a Wanderer"},
        headers=auth_headers(wanderer),
    )

    for label, token in (("author", wanderer), ("founder", founder)):
        comment = _comments(client, post_id, token)[0]
        assert comment["author_username"] == "wanderer_one", label
        assert comment["character_name"] is None, label
        # The sigil key must be present so the client can render the avatar;
        # its value is whatever the account has set (None when unset).
        assert "author_avatar_url" in comment, label


def test_character_comment_never_leaks_the_private_account_username(client):
    """6: a Writer's public output is the character and nothing else. The
    account username and sigil are stripped for everyone but the author."""
    founder, _realm_id, post_id = _founder_with_post(client)

    writer = get_auth_token(client, email="writer@test.com", username="private_writer")
    grant_writer_unlock("writer@test.com")
    writer_char = ensure_character(client, writer, name="Vale")
    client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "In character.", "character_id": writer_char},
        headers=auth_headers(writer),
    )

    def _by_character(viewer_token):
        return next(
            c for c in _comments(client, post_id, viewer_token)
            if c["character_name"] == "Vale"
        )

    for label, token in (("founder", founder), ("anonymous", None)):
        comment = _by_character(token)
        assert comment["author_username"] is None, f"{label} saw the private username"
        assert comment["author_user_id"] is None, f"{label} could cluster on the account"
        assert comment["author_avatar_url"] is None, f"{label} saw the account sigil"

    # The author still sees their own attribution in full.
    own = _by_character(writer)
    assert own["author_username"] == "private_writer"


# ── Permissions are unchanged ────────────────────────────────────────────────

def test_private_realm_comments_are_not_leaked(client):
    """7: making Wanderer comments visible must not widen post visibility. A
    post in a private realm 404s for outsiders, comments and all."""
    owner = get_auth_token(client, email="owner@test.com", username="realm_owner")
    grant_writer_unlock("owner@test.com")
    owner_char = ensure_character(client, owner, name="Keeper")
    realm_id = _realm(client, owner, "hidden", is_public=False)
    post_id = _post(client, owner, realm_id, character_id=owner_char)

    client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": "Members only.", "character_id": owner_char},
        headers=auth_headers(owner),
    )
    assert len(_comments(client, post_id, owner)) == 1

    outsider = get_auth_token(client, email="out@test.com", username="outsider")
    for label, headers in (
        ("outsider", auth_headers(outsider)),
        ("anonymous", {}),
    ):
        resp = client.get(f"/comments/posts/{post_id}/comments", headers=headers)
        assert resp.status_code == 404, f"{label} could read a private realm's comments"
