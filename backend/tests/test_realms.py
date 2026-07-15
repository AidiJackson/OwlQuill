"""S24E FIX B — GET /realms/{id} visibility enforcement (IDOR regression).

Mirrors the S24D FIX 4 characters test: a single-resource GET must require auth
and enforce the same visibility rule as the list endpoint (is_public), so private
realms cannot be scraped by ID.
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


def test_get_realm_visibility_enforced(client, db_session):
    owner = get_auth_token(client, email="realmowner@test.com", username="realmowner")
    priv_id = _create_realm(client, owner, "Secret Realm", "secret-realm", False)
    pub_id = _create_realm(client, owner, "Open Realm", "open-realm", True)

    # Unauthenticated → denied outright (no ID-iteration scrape).
    assert client.get(f"/realms/{priv_id}").status_code in (401, 403)

    # Authenticated non-member → 404 for private, 200 for public.
    other = get_auth_token(client, email="realmpeeper@test.com", username="realmpeeper")
    assert client.get(f"/realms/{priv_id}", headers=auth_headers(other)).status_code == 404
    assert client.get(f"/realms/{pub_id}", headers=auth_headers(other)).status_code == 200

    # Owner → 200 on their own private realm.
    assert client.get(f"/realms/{priv_id}", headers=auth_headers(owner)).status_code == 200

    # Explicit member of the private realm → 200 (added directly; join rejects private).
    from app.models.realm import RealmMembership
    from app.models.user import User

    member_tok = get_auth_token(client, email="realmmember@test.com", username="realmmember")
    member_user = db_session.query(User).filter(User.email == "realmmember@test.com").first()
    db_session.add(RealmMembership(realm_id=priv_id, user_id=member_user.id, role="member"))
    db_session.commit()
    assert client.get(f"/realms/{priv_id}", headers=auth_headers(member_tok)).status_code == 200


def test_list_realm_members_membership_required(client, db_session):
    """S24G: realm rosters (public AND private) require owner/membership."""
    owner = get_auth_token(client, email="mowner@test.com", username="mowner")
    priv_id = _create_realm(client, owner, "Priv Members", "priv-members", False)
    pub_id = _create_realm(client, owner, "Pub Members", "pub-members", True)

    # Unauthenticated → denied.
    assert client.get(f"/realms/{priv_id}/members").status_code in (401, 403)
    assert client.get(f"/realms/{pub_id}/members").status_code in (401, 403)

    other = get_auth_token(client, email="mpeeper@test.com", username="mpeeper")
    # Non-member → 404 on private roster (hides existence), 403 on public roster.
    assert client.get(f"/realms/{priv_id}/members", headers=auth_headers(other)).status_code == 404
    assert client.get(f"/realms/{pub_id}/members", headers=auth_headers(other)).status_code == 403
    # Owner → 200 on their own rosters.
    assert client.get(f"/realms/{priv_id}/members", headers=auth_headers(owner)).status_code == 200
    assert client.get(f"/realms/{pub_id}/members", headers=auth_headers(owner)).status_code == 200
    # Joined member of the public realm → 200.
    assert client.post(f"/realms/{pub_id}/join", headers=auth_headers(other)).status_code == 201
    assert client.get(f"/realms/{pub_id}/members", headers=auth_headers(other)).status_code == 200


def test_list_realms_public_only_false_no_private_leak(client, db_session):
    """S24F: public_only=false must not leak private realms the caller is not in."""
    owner = get_auth_token(client, email="lowner@test.com", username="lowner")
    priv_id = _create_realm(client, owner, "Hidden", "hidden-realm", False)
    _create_realm(client, owner, "Shown", "shown-realm", True)

    other = get_auth_token(client, email="lpeeper@test.com", username="lpeeper")
    # Unauthenticated → denied.
    assert client.get("/realms/?public_only=false").status_code in (401, 403)
    # Non-member with public_only=false must NOT see the private realm.
    resp = client.get("/realms/?public_only=false", headers=auth_headers(other))
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert priv_id not in ids
    # Owner WITH public_only=false DOES see their own private realm.
    resp_owner = client.get("/realms/?public_only=false", headers=auth_headers(owner))
    assert priv_id in {r["id"] for r in resp_owner.json()}
