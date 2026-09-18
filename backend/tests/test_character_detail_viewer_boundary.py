"""Character detail read is viewer-aware (Polish Phase 5.1).

``GET /characters/{id}`` used to hand every signed-in viewer of a PUBLIC
character the owner's account id and the character's ``identity_anchor_json``
(lock string, prompt hash, anchor image urls — the working references the
media surface deliberately withholds from visitors). The directory and search
never carried either. This pins the boundary the projection now applies on the
server:

  * the OWNER still receives everything owner tooling reads (``owner_id``,
    ``owner_username``, ``identity_anchor_json``, ``identity_health``) and
    ``is_owner`` true;
  * a NON-OWNER reading a PUBLIC character receives ``is_owner`` false and
    ``None`` for all four, and nothing equivalent through another field;
  * a NON-OWNER reading a PRIVATE character still gets the indistinguishable
    404;
  * the owner-scoped routes (create, list, update) say ``is_owner`` true;
  * the directory and search stay as clean as they were.
"""
import json

from app.models.character import Character as CharacterModel
from tests.conftest import auth_headers, get_auth_token


#: What the owner alone may read off the detail response. ``owner_username``
#: was owner-only before this pass; the other three are new to the boundary.
OWNER_ONLY_FIELDS = ("owner_id", "owner_username", "identity_anchor_json", "identity_health")

#: Substrings that must not appear ANYWHERE in a non-owner payload, at any
#: depth — the anchor data's own vocabulary, so a leak through a field this
#: test did not name by name still fails.
_ANCHOR_MARKERS = ("identity_lock_string", "identity_prompt_hash", "anchor_front.png", "ANCHOR-SECRET")

_ANCHOR_JSON = json.dumps({
    "version": 1,
    "pack_version": 1,
    "style": "realistic",
    "identity_prompt_hash": "ANCHOR-SECRET-hash",
    "identity_lock_string": "Long dark hair, hazel eyes, ANCHOR-SECRET lock",
    "anchors": {
        "front": {"id": 1, "url": "/static/generated/anchor_front.png"},
        "three_quarter": {"id": 2, "url": "/static/generated/anchor_3q.png"},
    },
})


def _create_character(client, token, name, visibility="public"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": visibility},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_anchor(db_session, character_id: int) -> None:
    """Write anchor data straight to the row: the boundary is about what the
    READ returns, not about how a pack is accepted."""
    row = db_session.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    row.identity_anchor_json = _ANCHOR_JSON
    row.visual_locked = True
    db_session.commit()


def _walk(value):
    """Every string at any depth of a JSON payload."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def _setup(client, db_session):
    owner = get_auth_token(client, email="vb-owner@test.com", username="vbowner")
    viewer = get_auth_token(client, email="vb-viewer@test.com", username="vbviewer")
    public = _create_character(client, owner, "Pan")
    _seed_anchor(db_session, public["id"])
    return owner, viewer, public["id"]


# ── OWNER ─────────────────────────────────────────────────────────────

def test_owner_detail_keeps_owner_only_identity_data(client, db_session):
    owner, _viewer, cid = _setup(client, db_session)
    me = client.get("/users/me", headers=auth_headers(owner)).json()

    resp = client.get(f"/characters/{cid}", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["is_owner"] is True
    assert body["owner_id"] == me["id"]
    assert body["owner_username"] == "vbowner"
    assert body["identity_anchor_json"] == _ANCHOR_JSON, "generation readiness reads this"
    assert json.loads(body["identity_anchor_json"])["anchors"]["front"]["url"].endswith("anchor_front.png")
    assert body["identity_health"] == {
        "face": "current", "body": "current", "tattoos": "current",
        "slots": {"front": {"stale": False}, "three_quarter": {"stale": False}},
    }
    assert body["visual_locked"] is True


# ── NON-OWNER, PUBLIC ─────────────────────────────────────────────────

def test_non_owner_reads_a_public_character_without_owner_or_identity_data(client, db_session):
    _owner, viewer, cid = _setup(client, db_session)

    resp = client.get(f"/characters/{cid}", headers=auth_headers(viewer))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The character itself is readable, as before.
    assert body["id"] == cid and body["name"] == "Pan" and body["visibility"] == "public"
    assert body["visual_locked"] is True, "a public fact, still public"

    # The boundary.
    assert body["is_owner"] is False
    for field in OWNER_ONLY_FIELDS:
        assert body.get(field) is None, f"{field} must be withheld from a non-owner"

    # Nothing equivalent leaks through any other field, at any depth.
    for s in _walk(body):
        for marker in _ANCHOR_MARKERS:
            assert marker not in s, f"anchor data leaked via {s!r}"


def test_non_owner_payload_has_no_account_identifier_anywhere(client, db_session):
    """The owner's numeric account id must not surface under any key."""
    _owner, viewer, cid = _setup(client, db_session)
    owner_id = client.get("/users/me", headers=auth_headers(_owner)).json()["id"]

    body = client.get(f"/characters/{cid}", headers=auth_headers(viewer)).json()
    for key, value in body.items():
        if key == "id":
            continue
        # Integer-typed only: a framing float such as cover_scale 1.0 is not
        # an account id, and ``1.0 == 1`` would otherwise trip this.
        if type(value) is int:
            assert value != owner_id, f"owner account id exposed under {key!r}"
        assert "vbowner" not in _walk_join(value), f"owner username exposed under {key!r}"


def _walk_join(value) -> str:
    return "\n".join(_walk(value))


def test_admin_viewer_is_not_the_owner(client, db_session, monkeypatch):
    """Existing behaviour kept: an admin reading someone else's character is a
    viewer of it, not its owner. No admin carve-out is introduced here."""
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "vb-viewer@test.com")
    _owner, viewer, cid = _setup(client, db_session)

    body = client.get(f"/characters/{cid}", headers=auth_headers(viewer)).json()
    assert body["is_owner"] is False
    for field in OWNER_ONLY_FIELDS:
        assert body.get(field) is None, field


# ── NON-OWNER, PRIVATE ────────────────────────────────────────────────

def test_non_owner_private_character_is_still_404(client, db_session):
    owner = get_auth_token(client, email="vb-owner2@test.com", username="vbowner2")
    viewer = get_auth_token(client, email="vb-viewer2@test.com", username="vbviewer2")
    private = _create_character(client, owner, "Hidden", visibility="private")
    _seed_anchor(db_session, private["id"])

    resp = client.get(f"/characters/{private['id']}", headers=auth_headers(viewer))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Character not found"}
    missing = client.get("/characters/999999", headers=auth_headers(viewer))
    assert missing.status_code == 404 and missing.json() == resp.json(), "indistinguishable"

    # The owner reads their private character in full.
    mine = client.get(f"/characters/{private['id']}", headers=auth_headers(owner)).json()
    assert mine["is_owner"] is True and mine["identity_anchor_json"] == _ANCHOR_JSON


# ── OWNER-SCOPED ROUTES ───────────────────────────────────────────────

def test_create_list_and_update_answer_is_owner_true(client, db_session):
    owner = get_auth_token(client, email="vb-owner3@test.com", username="vbowner3")
    created = _create_character(client, owner, "Mine")
    assert created["is_owner"] is True
    assert created["owner_id"] is not None

    listed = client.get("/characters/", headers=auth_headers(owner)).json()
    assert listed and all(c["is_owner"] is True for c in listed)

    updated = client.patch(
        f"/characters/{created['id']}", json={"alias": "M"}, headers=auth_headers(owner)
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_owner"] is True and updated.json()["alias"] == "M"


def test_is_owner_cannot_be_written_by_the_client(client, db_session):
    """A client sending is_owner on create or update changes nothing: the
    field is not on the write schemas, and the read is the server's answer."""
    owner = get_auth_token(client, email="vb-owner4@test.com", username="vbowner4")
    viewer = get_auth_token(client, email="vb-viewer4@test.com", username="vbviewer4")
    created = client.post(
        "/characters/",
        json={"name": "Spoof", "species": "human", "is_owner": False, "owner_id": 1},
        headers=auth_headers(owner),
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert created.json()["is_owner"] is True

    resp = client.patch(
        f"/characters/{cid}", json={"is_owner": True}, headers=auth_headers(viewer)
    )
    assert resp.status_code == 403
    assert client.get(f"/characters/{cid}", headers=auth_headers(viewer)).json()["is_owner"] is False


# ── DIRECTORY / SEARCH ────────────────────────────────────────────────

def test_directory_and_search_stay_clean(client, db_session):
    from app.models.user import User

    owner = get_auth_token(client, email="vb-seeder@test.com", username="vbseeder")
    user = db_session.query(User).filter(User.email == "vb-seeder@test.com").first()
    user.is_seeder = True
    db_session.commit()
    viewer = get_auth_token(client, email="vb-viewer5@test.com", username="vbviewer5")

    a = _create_character(client, owner, "Summer")
    _seed_anchor(db_session, a["id"])
    _create_character(client, owner, "Shadow", visibility="private")

    for url in ("/characters/directory", "/characters/search?q=Su"):
        resp = client.get(url, headers=auth_headers(viewer))
        assert resp.status_code == 200, resp.text
        entries = resp.json()
        assert any(e["name"] == "Summer" for e in entries), url
        assert not any(e["name"] == "Shadow" for e in entries), url
        for entry in entries:
            for field in OWNER_ONLY_FIELDS + ("is_owner",):
                assert field not in entry, (url, field)
            for s in _walk(entry):
                for marker in _ANCHOR_MARKERS:
                    assert marker not in s, (url, s)
