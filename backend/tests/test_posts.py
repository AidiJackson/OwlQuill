"""S24E FIX A — GET /posts/{id} visibility enforcement (IDOR regression).

Mirrors the S24D FIX 4 characters test: a single-resource GET must require auth
and enforce post visibility via realm access (a post inherits its realm's
is_public rule), so posts in private realms cannot be scraped by ID.
"""
from tests.conftest import get_auth_token, auth_headers


def _create_realm(client, token, name, slug, is_public):
    resp = client.post(
        "/realms/",
        json={"name": name, "slug": slug, "is_public": is_public},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_post(client, token, realm_id, content):
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_get_post_visibility_enforced(client, db_session):
    owner = get_auth_token(client, email="postowner@test.com", username="postowner")
    priv_realm = _create_realm(client, owner, "Priv", "priv-posts", False)
    pub_realm = _create_realm(client, owner, "Pub", "pub-posts", True)
    priv_post = _create_post(client, owner, priv_realm, "secret content")
    pub_post = _create_post(client, owner, pub_realm, "open content")

    # Unauthenticated → denied outright.
    assert client.get(f"/posts/{priv_post}").status_code in (401, 403)

    # Authenticated non-member → 404 for private-realm post, 200 for public-realm post.
    other = get_auth_token(client, email="postpeeper@test.com", username="postpeeper")
    assert client.get(f"/posts/{priv_post}", headers=auth_headers(other)).status_code == 404
    assert client.get(f"/posts/{pub_post}", headers=auth_headers(other)).status_code == 200

    # Owner → 200 on their own private-realm post.
    assert client.get(f"/posts/{priv_post}", headers=auth_headers(owner)).status_code == 200

    # Explicit member of the private realm → 200.
    from app.models.realm import RealmMembership
    from app.models.user import User

    member_tok = get_auth_token(client, email="postmember@test.com", username="postmember")
    member_user = db_session.query(User).filter(User.email == "postmember@test.com").first()
    db_session.add(RealmMembership(realm_id=priv_realm, user_id=member_user.id, role="member"))
    db_session.commit()
    assert client.get(f"/posts/{priv_post}", headers=auth_headers(member_tok)).status_code == 200


def test_list_realm_posts_visibility_enforced(client, db_session):
    """S24F: a private realm's post list is not enumerable by a non-member."""
    owner = get_auth_token(client, email="lrp_owner@test.com", username="lrpowner")
    priv_realm = _create_realm(client, owner, "PrivLRP", "priv-lrp", False)
    pub_realm = _create_realm(client, owner, "PubLRP", "pub-lrp", True)
    _create_post(client, owner, priv_realm, "hidden post")
    _create_post(client, owner, pub_realm, "shown post")

    # Unauthenticated → denied.
    assert client.get(f"/posts/realms/{priv_realm}/posts").status_code in (401, 403)

    other = get_auth_token(client, email="lrp_peeper@test.com", username="lrppeeper")
    # Non-member → 404 on private realm, 200 on public realm.
    assert client.get(f"/posts/realms/{priv_realm}/posts", headers=auth_headers(other)).status_code == 404
    assert client.get(f"/posts/realms/{pub_realm}/posts", headers=auth_headers(other)).status_code == 200
    # Owner → 200 on their private realm.
    assert client.get(f"/posts/realms/{priv_realm}/posts", headers=auth_headers(owner)).status_code == 200


def test_post_comments_and_reactions_private_realm_gated(client, db_session):
    """S24F: comments/reactions inherit post visibility.

    Public-realm sub-resources remain readable (incl. unauthenticated); private-realm
    posts return 404 for non-members.
    """
    owner = get_auth_token(client, email="cr_owner@test.com", username="crowner")
    priv_realm = _create_realm(client, owner, "PrivCR", "priv-cr", False)
    pub_realm = _create_realm(client, owner, "PubCR", "pub-cr", True)
    priv_post = _create_post(client, owner, priv_realm, "hidden")
    pub_post = _create_post(client, owner, pub_realm, "shown")

    # Owner seeds a comment + reaction on each post.
    for pid in (priv_post, pub_post):
        assert client.post(
            f"/comments/posts/{pid}/comments", json={"content": "hi"},
            headers=auth_headers(owner),
        ).status_code == 201
        assert client.post(
            f"/reactions/posts/{pid}/reactions", json={"type": "like"},
            headers=auth_headers(owner),
        ).status_code == 201

    other = get_auth_token(client, email="cr_peeper@test.com", username="crpeeper")

    # Private-realm post: non-member and unauthenticated → 404 for comments + reactions.
    assert client.get(f"/comments/posts/{priv_post}/comments", headers=auth_headers(other)).status_code == 404
    assert client.get(f"/comments/posts/{priv_post}/comments").status_code == 404
    assert client.get(f"/reactions/posts/{priv_post}/reactions", headers=auth_headers(other)).status_code == 404
    assert client.get(f"/reactions/posts/{priv_post}/reactions").status_code == 404

    # Public-realm post: readable by non-member AND unauthenticated (existing convention).
    assert client.get(f"/comments/posts/{pub_post}/comments", headers=auth_headers(other)).status_code == 200
    assert client.get(f"/comments/posts/{pub_post}/comments").status_code == 200
    assert client.get(f"/reactions/posts/{pub_post}/reactions").status_code == 200

    # Owner can read their private-realm post's comments + reactions.
    assert client.get(f"/comments/posts/{priv_post}/comments", headers=auth_headers(owner)).status_code == 200
    assert client.get(f"/reactions/posts/{priv_post}/reactions", headers=auth_headers(owner)).status_code == 200
