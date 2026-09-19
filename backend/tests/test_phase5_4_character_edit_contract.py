"""Phase 5.4 — the PATCH /characters/{id} contract the Edit Details UI relies on.

The owner-facing Edit Details form (name, alias, role, era, short_bio,
long_bio, tags) and the Public/Private control both save through the existing
PATCH. These tests pin the parts of that route the form depends on, without
restating what other files already prove (``test_character_detail_viewer_boundary``
covers is_owner on update; ``test_beta_display_pointer_boundary`` covers the
framing fields and the pointer refusal).

  1. each approved profile field is writable by the owner
  2. PATCH is genuinely partial — unspecified fields are untouched
  3. an explicit null clears an optional field (how the form "empties" one)
  4. a non-owner is refused 403 and writes nothing
  5. public → private and private → public, with the read-side consequences
     the UI copy describes (hidden from the detail read, search and mentions
     for others; still open to the owner; existing posts untouched)
  6. the enum still admits "friends" (nothing removes it) and it behaves as
     private on the read side — the UI simply does not offer it
  7. the owner PATCH response is the same projection as the owner GET
  8. editing profile fields leaves identity DNA / canon / anchor untouched
  9. the validation the client mirrors: empty name 422, >100 chars 422,
     whitespace is NOT trimmed by the server (so the client must), and tags
     are an opaque comma-separated string
"""
import json

import pytest

from app.models.character import Character as CharacterModel
from app.models.character_identity_canon import CharacterIdentityCanon
from tests.canon_test_utils import setup_canon
from tests.conftest import auth_headers, get_auth_token

PROFILE_FIELDS = {
    "name": "Renamed",
    "alias": "The Quiet One",
    "role": "cartographer",
    "era": "late bronze age",
    "short_bio": "Maps what others fear.",
    "long_bio": "A much longer account of a life spent at the edges of known maps.",
    "tags": "maps, quiet, bronze age",
}


def _login(client, email):
    return get_auth_token(client, email=email, username=email.split("@")[0])


def _create(client, token, **overrides):
    body = {"name": "Original", "species": "human", "visibility": "public", **overrides}
    resp = client.post("/characters/", json=body, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _patch(client, token, cid, payload):
    return client.patch(f"/characters/{cid}", json=payload, headers=auth_headers(token))


def _get(client, token, cid):
    return client.get(f"/characters/{cid}", headers=auth_headers(token))


# ── 1. every approved field ──────────────────────────────────────────


@pytest.mark.parametrize("field,value", sorted(PROFILE_FIELDS.items()))
def test_owner_can_patch_each_approved_profile_field(client, field, value):
    token = _login(client, f"p54_{field}@example.com")
    cid = _create(client, token)
    resp = _patch(client, token, cid, {field: value})
    assert resp.status_code == 200, resp.text
    assert resp.json()[field] == value
    assert _get(client, token, cid).json()[field] == value


# ── 2 + 3. partial, and null clears ──────────────────────────────────


def test_partial_patch_leaves_unspecified_fields_alone(client):
    token = _login(client, "p54_partial@example.com")
    cid = _create(client, token, alias="Keep Me", role="keeper", tags="a, b", short_bio="stays")

    resp = _patch(client, token, cid, {"era": "only this"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["era"] == "only this"
    assert body["alias"] == "Keep Me"
    assert body["role"] == "keeper"
    assert body["tags"] == "a, b"
    assert body["short_bio"] == "stays"
    assert body["name"] == "Original"
    assert body["visibility"] == "public"


def test_explicit_null_clears_an_optional_field(client):
    """The form sends null for an optional field the owner emptied."""
    token = _login(client, "p54_null@example.com")
    cid = _create(client, token, alias="Gone Soon", tags="x, y")
    resp = _patch(client, token, cid, {"alias": None, "tags": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["alias"] is None
    assert resp.json()["tags"] is None


# ── 4. non-owner ─────────────────────────────────────────────────────


def test_non_owner_cannot_patch_and_nothing_changes(client, db_session):
    owner = _login(client, "p54_owner@example.com")
    intruder = _login(client, "p54_intruder@example.com")
    cid = _create(client, owner)

    resp = _patch(client, intruder, cid, {"name": "Hijacked", "visibility": "private"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not authorized to update this character"
    db_session.expire_all()
    row = db_session.get(CharacterModel, cid)
    assert row.name == "Original"
    assert row.visibility.value == "public"


# ── 5. visibility, and what it does on the read side ─────────────────


def test_public_to_private_hides_from_others_but_not_from_the_owner(client, db_session):
    owner = _login(client, "p54_priv_owner@example.com")
    viewer = _login(client, "p54_priv_viewer@example.com")
    cid = _create(client, owner, name="Cartographer", tags="maps")
    assert _get(client, viewer, cid).status_code == 200
    assert cid in {c["id"] for c in client.get(
        "/characters/search?q=Cartographer", headers=auth_headers(viewer)).json()}

    resp = _patch(client, owner, cid, {"visibility": "private"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["visibility"] == "private"

    # Detail read: 404, indistinguishable from nonexistent.
    assert _get(client, viewer, cid).status_code == 404
    # Directory/search: gone.
    assert cid not in {c["id"] for c in client.get(
        "/characters/search?q=Cartographer", headers=auth_headers(viewer)).json()}
    # Mention resolution: a private character is not a mention target.
    from app.services.mentions import resolve_mentions
    assert resolve_mentions(db_session, ["@Cartographer"]) == []
    # The owner still opens it, still as the owner.
    mine = _get(client, owner, cid)
    assert mine.status_code == 200 and mine.json()["is_owner"] is True


def test_private_to_public_restores_the_shared_surfaces(client):
    owner = _login(client, "p54_pub_owner@example.com")
    viewer = _login(client, "p54_pub_viewer@example.com")
    cid = _create(client, owner, name="Reappearing", visibility="private")
    assert _get(client, viewer, cid).status_code == 404

    resp = _patch(client, owner, cid, {"visibility": "public"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["visibility"] == "public"
    assert _get(client, viewer, cid).status_code == 200
    assert cid in {c["id"] for c in client.get(
        "/characters/search?q=Reappearing", headers=auth_headers(viewer)).json()}


def test_going_private_does_not_touch_existing_posts(client, db_session):
    """PD-2: the UI says already-shared posts stay. Pin that the row does."""
    from app.models.post import Post

    owner = _login(client, "p54_posts_owner@example.com")
    cid = _create(client, owner)
    post = Post(author_user_id=db_session.get(CharacterModel, cid).owner_id,
                character_id=cid, content="already shared")
    db_session.add(post)
    db_session.commit()
    pid = post.id

    assert _patch(client, owner, cid, {"visibility": "private"}).status_code == 200
    db_session.expire_all()
    kept = db_session.get(Post, pid)
    assert kept is not None and kept.character_id == cid


# ── 6. friends stays a backend value, reads as private ───────────────


def test_friends_is_still_accepted_and_reads_like_private(client):
    owner = _login(client, "p54_friends_owner@example.com")
    viewer = _login(client, "p54_friends_viewer@example.com")
    cid = _create(client, owner)
    resp = _patch(client, owner, cid, {"visibility": "friends"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["visibility"] == "friends"
    assert _get(client, viewer, cid).status_code == 404
    assert _get(client, owner, cid).status_code == 200


def test_unknown_visibility_is_rejected(client):
    owner = _login(client, "p54_badvis@example.com")
    cid = _create(client, owner)
    assert _patch(client, owner, cid, {"visibility": "secret"}).status_code == 422


# ── 7. PATCH response == owner GET projection ────────────────────────


def test_patch_response_is_the_owner_detail_projection(client, db_session):
    """The client replaces the page's character with the PATCH body, so it
    must carry everything the owner GET carries: is_owner, owner-only fields,
    has_identity_canon, and the avatar/cover put through the same resolver."""
    owner = _login(client, "p54_proj@example.com")
    cid = _create(client, owner)
    setup_canon(db_session, cid)  # gives the character a generated canon
    # An avatar pointer nothing can vouch for: the resolver withholds it on
    # GET, and must withhold it on PATCH too.
    row = db_session.get(CharacterModel, cid)
    row.avatar_url = "/static/generated/nobody-owns-this.png"
    db_session.commit()

    patched = _patch(client, owner, cid, {"alias": "Projected"}).json()
    read = _get(client, owner, cid).json()

    assert patched["is_owner"] is True
    assert patched["owner_id"] == read["owner_id"] and patched["owner_id"] is not None
    assert patched["owner_username"] == read["owner_username"] == "p54_proj"
    assert patched["has_identity_canon"] is True == read["has_identity_canon"]
    assert patched["avatar_url"] is None == read["avatar_url"]
    assert "identity_health" in patched and patched["identity_health"] == read["identity_health"]
    # And of course the edit landed in both.
    assert patched["alias"] == read["alias"] == "Projected"
    # Field-for-field, the two are the same document.
    assert patched == read


# ── 8. identity is untouched ─────────────────────────────────────────


def test_editing_profile_fields_leaves_identity_data_untouched(client, db_session):
    owner = _login(client, "p54_identity@example.com")
    cid = _create(client, owner)
    setup_canon(db_session, cid)
    row = db_session.get(CharacterModel, cid)
    row.identity_spec_json = json.dumps({"identity": {"hair_color": "black"}})
    row.identity_anchor_json = json.dumps({"identity_lock_string": "locked"})
    row.body_canon_json = json.dumps({"marks": []})
    row.visual_locked = True
    db_session.commit()
    canon_before = db_session.query(CharacterIdentityCanon).filter_by(character_id=cid).one()
    face_before, body_before = canon_before.face_canon_json, canon_before.body_canon_json

    resp = _patch(client, owner, cid, {**PROFILE_FIELDS, "visibility": "private"})
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    row = db_session.get(CharacterModel, cid)
    assert json.loads(row.identity_spec_json) == {"identity": {"hair_color": "black"}}
    assert json.loads(row.identity_anchor_json) == {"identity_lock_string": "locked"}
    assert json.loads(row.body_canon_json) == {"marks": []}
    assert row.visual_locked is True
    canon_after = db_session.query(CharacterIdentityCanon).filter_by(character_id=cid).one()
    assert (canon_after.face_canon_json, canon_after.body_canon_json) == (face_before, body_before)
    # The species/age the form never shows are untouched as well.
    assert row.species == "human"


# ── 9. validation the client mirrors ─────────────────────────────────


def test_name_validation_the_client_mirrors(client):
    owner = _login(client, "p54_namev@example.com")
    cid = _create(client, owner)
    assert _patch(client, owner, cid, {"name": ""}).status_code == 422
    assert _patch(client, owner, cid, {"name": "x" * 101}).status_code == 422
    assert _patch(client, owner, cid, {"name": "x" * 100}).status_code == 200


def test_server_does_not_trim_whitespace_so_the_client_must(client):
    """Documented, not endorsed: the server stores what it is sent. The form
    trims before sending; this pins the fact the form is compensating for."""
    owner = _login(client, "p54_ws@example.com")
    cid = _create(client, owner)
    resp = _patch(client, owner, cid, {"alias": "  padded  ", "tags": " a ,b,, c "})
    assert resp.status_code == 200
    assert resp.json()["alias"] == "  padded  "
    assert resp.json()["tags"] == " a ,b,, c "


def test_tags_are_an_opaque_comma_separated_string(client):
    owner = _login(client, "p54_tags@example.com")
    cid = _create(client, owner)
    assert _patch(client, owner, cid, {"tags": ["a", "b"]}).status_code == 422
    resp = _patch(client, owner, cid, {"tags": "a, b, c"})
    assert resp.status_code == 200 and resp.json()["tags"] == "a, b, c"
