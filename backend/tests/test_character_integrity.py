"""Closed-beta Character Integrity hardening.

Pins, in one place:

  A. Deletion privacy — what a character's posts and comments reveal about the
     owning ACCOUNT, before and after the character is deleted, per viewer.
     Two cases are ``xfail(strict=True)``: they state the required invariant,
     which the current schema cannot satisfy (a deleted character's orphaned
     rows are indistinguishable from legacy account-authored posts and from
     Wanderer comments — both supported, both ``character_id IS NULL``). When
     the schema fix lands they XPASS, strict turns that into a failure, and
     whoever lands it removes the marker.
  B. The name/alias policy (``app.services.character_names``) — unit-level and
     through both write routes, including the temporary duplicate rule and the
     PATCH null refusals.
  C. Mention determinism, and the documented limit of the legacy @ parser.
  Rename consequences — /c/{id} is stable, publication is untouched, live
     attribution follows the new name, a historical mention stays linked by id.
"""
import pytest

from app.models.character import Character, VisibilityEnum
from app.models.user import User
from app.services.character_home_share import render_character_home_shell
from app.services.character_names import (
    ALIAS_MAX_LENGTH,
    NAME_MAX_LENGTH,
    CharacterNameError,
    normalize_character_alias,
    normalize_character_name,
)
from app.services.mentions import parse_mention_texts, resolve_mentions
from tests.conftest import auth_headers, get_auth_token

BASE = "https://ficshon.example"
SHELL = "<!doctype html><html><head><title>Ficshon</title></head><body><div id=\"root\"></div></body></html>"


# ── helpers ──────────────────────────────────────────────────────────────────

def _login(client, email):
    return get_auth_token(client, email=email, username=email.split("@")[0])


def _create(client, token, name, **extra):
    body = {"name": name, "species": "human", "visibility": "public", **extra}
    return client.post("/characters/", json=body, headers=auth_headers(token))


def _create_id(client, token, name, **extra):
    resp = _create(client, token, name, **extra)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _patch(client, token, cid, payload):
    return client.patch(f"/characters/{cid}", json=payload, headers=auth_headers(token))


def _realm(client, token, slug):
    resp = client.post(
        "/realms/",
        json={"name": slug.title(), "slug": slug, "is_public": True},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _join(client, token, realm_id):
    resp = client.post(f"/realms/{realm_id}/join", headers=auth_headers(token))
    assert resp.status_code in (200, 201, 204), resp.text


def _post(client, token, realm_id, character_id, content):
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "character_id": character_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _comment(client, token, post_id, character_id, content):
    resp = client.post(
        f"/comments/posts/{post_id}/comments",
        json={"content": content, "character_id": character_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _comments(client, post_id, token=None):
    headers = auth_headers(token) if token else {}
    resp = client.get(f"/comments/posts/{post_id}/comments", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_admin(db_session, email):
    user = db_session.query(User).filter(User.email == email).first()
    user.is_admin = True
    db_session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# A. Deletion privacy
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def authored(client):
    """An owner whose character wrote one post and one comment in a public
    realm, and a signed-in non-author who can read both."""
    owner = _login(client, "ci_owner@example.com")
    viewer = _login(client, "ci_viewer@example.com")
    realm = _realm(client, owner, "ci-realm")
    _join(client, viewer, realm)
    cid = _create_id(client, owner, "Ashmark")
    post_id = _post(client, owner, realm, cid, "in character")
    comment_id = _comment(client, owner, post_id, cid, "also in character")
    return {"owner": owner, "viewer": viewer, "cid": cid,
            "post_id": post_id, "comment_id": comment_id}


def _the_comment(comments, comment_id):
    [c] = [c for c in comments if c["id"] == comment_id]
    return c


def test_character_post_before_deletion_shows_only_the_character(client, authored):
    p = client.get(f"/posts/{authored['post_id']}", headers=auth_headers(authored["viewer"])).json()
    assert p["character_name"] == "Ashmark"
    assert p["author_username"] is None
    assert p["author_user_id"] is None


def test_character_post_owner_keeps_own_attribution(client, authored):
    p = client.get(f"/posts/{authored['post_id']}", headers=auth_headers(authored["owner"])).json()
    assert p["author_username"] == "ci_owner"


def test_character_comment_before_deletion_shows_only_the_character(client, authored):
    signed_in = _the_comment(_comments(client, authored["post_id"], authored["viewer"]), authored["comment_id"])
    assert signed_in["character_name"] == "Ashmark"
    assert signed_in["author_username"] is None
    assert signed_in["author_avatar_url"] is None
    anon = _the_comment(_comments(client, authored["post_id"]), authored["comment_id"])
    assert anon["character_name"] == "Ashmark"
    assert anon["author_username"] is None


def _delete_character(client, authored):
    resp = client.delete(f"/characters/{authored['cid']}", headers=auth_headers(authored["owner"]))
    assert resp.status_code == 204, resp.text


def test_after_deletion_anonymous_reader_gets_no_account_identity(client, authored):
    _delete_character(client, authored)
    anon = _the_comment(_comments(client, authored["post_id"]), authored["comment_id"])
    assert anon["author_username"] is None
    assert anon["author_user_id"] is None
    assert anon["author_avatar_url"] is None
    # A single post is not served to anonymous readers at all.
    resp = client.get(f"/posts/{authored['post_id']}")
    assert resp.status_code in (401, 403)
    assert "ci_owner" not in resp.text


def test_after_deletion_the_owner_still_sees_their_own_rows(client, authored):
    _delete_character(client, authored)
    p = client.get(f"/posts/{authored['post_id']}", headers=auth_headers(authored["owner"])).json()
    assert p["character_id"] is None
    assert p["author_username"] == "ci_owner"


_ORPHAN_XFAIL = pytest.mark.xfail(
    strict=True,
    reason=(
        "BLOCKER (Character Integrity A), unresolved by design: posts/comments "
        "carry no authorship provenance. Character deletion sets character_id to "
        "NULL (ON DELETE SET NULL), after which a modern character-authored row is "
        "indistinguishable from a genuine legacy account-authored post or a "
        "Wanderer comment, which legitimately carry the account username. Fixing "
        "it without guessing needs a write-time authorship-kind column on posts "
        "and comments. Do not weaken this test; remove the marker when it XPASSes."
    ),
)


@_ORPHAN_XFAIL
def test_after_deletion_signed_in_non_author_sees_no_username_on_the_post(client, authored):
    _delete_character(client, authored)
    p = client.get(f"/posts/{authored['post_id']}", headers=auth_headers(authored["viewer"])).json()
    assert p["author_username"] is None
    assert p["author_user_id"] is None


@_ORPHAN_XFAIL
def test_after_deletion_signed_in_non_author_sees_no_username_on_the_comment(client, authored):
    _delete_character(client, authored)
    c = _the_comment(_comments(client, authored["post_id"], authored["viewer"]), authored["comment_id"])
    assert c["author_username"] is None
    assert c["author_avatar_url"] is None


# ══════════════════════════════════════════════════════════════════════════════
# B. Name / alias policy — unit
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw, stored", [
    ("  Pan  ", "Pan"),
    ("Leo   Vance", "Leo Vance"),
    ("Leo\tVance\nthe Second", "Leo Vance the Second"),
    ("Zoë", "Zoë"),                    # NFD → NFC
    ("Zoë", "Zoë"),
    ("林黛玉", "林黛玉"),
    ("Ash 🦊", "Ash 🦊"),
    ("👩‍🚀 Nova", "👩‍🚀 Nova"),      # ZWJ emoji sequence allowed
    ("Admiral Staffe", "Admiral Staffe"),        # reserved words only as WHOLE names
    ("The System Breaker", "The System Breaker"),
    ("O'Brien-Smythe, Jr.", "O'Brien-Smythe, Jr."),
    ("Lord Vexis the Flayer", "Lord Vexis the Flayer"),  # no content filter
])
def test_valid_names_normalise(raw, stored):
    assert normalize_character_name(raw) == stored


@pytest.mark.parametrize("raw", [
    "", "   ", "\t\n",                      # empty / whitespace-only
    "Pan\x00",                              # NUL
    "Pan\x07", "Pan\x7f",                   # other Cc
    "Pan‮", "Pan‪", "Pan⁦", "Pan⁩",  # bidi controls
    "Pan​", "P‌an", "Pan⁠", "﻿Pan",  # prohibited zero-width
    "<b>Pan</b>", "Pan>", "<Pan",           # angle brackets
    "https://pan.example", "HTTP://x", "www.pan.com", "WWW.Pan",  # URL-ish
    "Ficshon", "admin", "MODERATOR", "Staff", "support", "System", "Official",
    " admin ",                              # reserved after normalisation
    "!!!", "🦊", "--",                     # no letter or digit
    None,
])
def test_invalid_names_are_refused(raw):
    with pytest.raises(CharacterNameError):
        normalize_character_name(raw)


def test_name_length_is_measured_after_normalisation():
    assert normalize_character_name("  " + "x" * NAME_MAX_LENGTH + "  ") == "x" * NAME_MAX_LENGTH
    with pytest.raises(CharacterNameError):
        normalize_character_name("x" * (NAME_MAX_LENGTH + 1))


def test_alias_is_optional_and_policed():
    assert normalize_character_alias(None) is None
    assert normalize_character_alias("   ") is None          # clears, never stores blanks
    assert normalize_character_alias("  the   Quiet  One ") == "the Quiet One"
    assert normalize_character_alias("x" * ALIAS_MAX_LENGTH) == "x" * ALIAS_MAX_LENGTH
    for bad in ("x" * (ALIAS_MAX_LENGTH + 1), "Admin", "www.x.com", "a‮b", "<i>", "a\x00"):
        with pytest.raises(CharacterNameError):
            normalize_character_alias(bad)


# ══════════════════════════════════════════════════════════════════════════════
# B. Name / alias policy — through the routes
# ══════════════════════════════════════════════════════════════════════════════

def test_create_stores_the_normalised_name_and_alias(client):
    t = _login(client, "ci_norm@example.com")
    resp = _create(client, t, "  Leo   Vance ", alias="  the   Lion ")
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Leo Vance"
    assert resp.json()["alias"] == "the Lion"


@pytest.mark.parametrize("bad", ["   ", "Pan‮", "Pan\x00", "<script>", "www.pan.com", "Admin", "x" * 101])
def test_create_refuses_with_a_readable_422(client, bad):
    t = _login(client, "ci_bad@example.com")
    resp = _create(client, t, bad)
    assert resp.status_code == 422, resp.text
    # One sentence, not Pydantic's list — Edit Details shows ``detail`` verbatim.
    assert isinstance(resp.json()["detail"], str)


@pytest.mark.parametrize("bad", ["   ", "Pan​", "https://x.y", "Support"])
def test_patch_refuses_with_a_readable_422_and_writes_nothing(client, db_session, bad):
    t = _login(client, "ci_pbad@example.com")
    cid = _create_id(client, t, "Keeper")
    resp = _patch(client, t, cid, {"name": bad})
    assert resp.status_code == 422, resp.text
    assert isinstance(resp.json()["detail"], str)
    db_session.expire_all()
    assert db_session.get(Character, cid).name == "Keeper"


def test_patch_alias_cap(client):
    t = _login(client, "ci_alias@example.com")
    cid = _create_id(client, t, "Aliased")
    assert _patch(client, t, cid, {"alias": "a" * 101}).status_code == 422
    ok = _patch(client, t, cid, {"alias": "a" * 100})
    assert ok.status_code == 200 and ok.json()["alias"] == "a" * 100
    cleared = _patch(client, t, cid, {"alias": None})
    assert cleared.status_code == 200 and cleared.json()["alias"] is None


def test_patch_explicit_null_name_is_422_not_500(client):
    t = _login(client, "ci_nulln@example.com")
    cid = _create_id(client, t, "Nullable")
    resp = _patch(client, t, cid, {"name": None})
    assert resp.status_code == 422, resp.text
    assert isinstance(resp.json()["detail"], str)


def test_patch_explicit_null_visibility_is_422_not_500(client):
    t = _login(client, "ci_nullv@example.com")
    cid = _create_id(client, t, "Visible")
    resp = _patch(client, t, cid, {"visibility": None})
    assert resp.status_code == 422, resp.text
    assert isinstance(resp.json()["detail"], str)


def test_omitted_fields_are_still_left_alone(client):
    t = _login(client, "ci_omit@example.com")
    cid = _create_id(client, t, "Steady", alias="Still")
    resp = _patch(client, t, cid, {"role": "watcher"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Steady"
    assert resp.json()["alias"] == "Still"
    assert resp.json()["visibility"] == "public"


def test_duplicate_name_is_refused_case_insensitively_on_create(client):
    a = _login(client, "ci_dupa@example.com")
    b = _login(client, "ci_dupb@example.com")
    _create_id(client, a, "Leo")
    for attempt in ("Leo", "leo", "  LEO  "):
        resp = _create(client, b, attempt)
        assert resp.status_code == 409, resp.text
        assert "unique" in resp.json()["detail"]


def test_duplicate_includes_private_characters(client):
    a = _login(client, "ci_dpa@example.com")
    b = _login(client, "ci_dpb@example.com")
    _create_id(client, a, "Hidden One", visibility="private")
    assert _create(client, b, "hidden one").status_code == 409


def test_rename_into_another_characters_name_is_refused(client):
    a = _login(client, "ci_rna@example.com")
    b = _login(client, "ci_rnb@example.com")
    _create_id(client, a, "Leo")
    cid = _create_id(client, b, "Pan")
    resp = _patch(client, b, cid, {"name": "LEO"})
    assert resp.status_code == 409, resp.text


def test_self_case_only_rename_is_allowed(client):
    t = _login(client, "ci_self@example.com")
    cid = _create_id(client, t, "leo")
    resp = _patch(client, t, cid, {"name": "Leo"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Leo"


def test_alias_is_not_required_to_be_unique(client):
    a = _login(client, "ci_ala@example.com")
    b = _login(client, "ci_alb@example.com")
    _create_id(client, a, "First", alias="The Fox")
    assert _create(client, b, "Second", alias="The Fox").status_code == 201


# ══════════════════════════════════════════════════════════════════════════════
# Rename consequences
# ══════════════════════════════════════════════════════════════════════════════

def test_rename_keeps_the_home_url_and_publication_state(client, db_session):
    owner = _login(client, "ci_home@example.com")
    admin = _login(client, "ci_admin@example.com")
    _make_admin(db_session, "ci_admin@example.com")
    cid = _create_id(client, owner, "Pan")
    resp = client.post(f"/admin/characters/{cid}/public-home", json={"enabled": True},
                       headers=auth_headers(admin))
    assert resp.status_code == 200 and resp.json()["publishable"] is True

    before = render_character_home_shell(db_session, cid, SHELL, BASE)
    assert f"{BASE}/c/{cid}" in before and "Pan | Ficshon" in before

    assert _patch(client, owner, cid, {"name": "Leo"}).status_code == 200
    db_session.expire_all()

    row = db_session.get(Character, cid)
    assert row.public_home_enabled is True
    assert row.visibility == VisibilityEnum.PUBLIC
    home = client.get(f"/characters/{cid}/public-home")
    assert home.status_code == 200 and home.json()["name"] == "Leo"
    after = render_character_home_shell(db_session, cid, SHELL, BASE)
    assert f"{BASE}/c/{cid}" in after          # same URL, no redirect needed
    assert "Leo | Ficshon" in after and "Pan | Ficshon" not in after


def test_rename_flows_into_live_post_and_comment_attribution(client, authored):
    assert _patch(client, authored["owner"], authored["cid"], {"name": "Emberly"}).status_code == 200
    p = client.get(f"/posts/{authored['post_id']}", headers=auth_headers(authored["viewer"])).json()
    assert p["character_name"] == "Emberly"
    c = _the_comment(_comments(client, authored["post_id"], authored["viewer"]), authored["comment_id"])
    assert c["character_name"] == "Emberly"


def test_historical_mention_stays_linked_by_id_after_rename(client):
    owner = _login(client, "ci_m_owner@example.com")
    other = _login(client, "ci_m_other@example.com")
    realm = _realm(client, owner, "ci-mention")
    _join(client, other, realm)
    pan = _create_id(client, owner, "Pan")
    bard = _create_id(client, other, "Bard")
    post_id = _post(client, other, realm, bard, "Hello @Pan, welcome.")

    assert _patch(client, owner, pan, {"name": "Leo"}).status_code == 200
    p = client.get(f"/posts/{post_id}", headers=auth_headers(other)).json()
    assert p["content"] == "Hello @Pan, welcome."     # prose is history; not rewritten
    [m] = p["mentions"]
    assert m["mention_text"] == "@Pan"
    assert m["url"] == f"/characters/{pan}"          # still the same character
    assert m["display_name"] == "Leo"                # live name


# ══════════════════════════════════════════════════════════════════════════════
# C. Mentions
# ══════════════════════════════════════════════════════════════════════════════

def test_mention_resolution_is_deterministic_for_legacy_duplicates(db_session):
    """Rows predating the duplicate rule can still share a name; the OLDEST
    public one wins, every time."""
    u = User(email="ci_dup_legacy@example.com", username="ci_dup_legacy", hashed_password="x")
    db_session.add(u)
    db_session.flush()
    first = Character(owner_id=u.id, name="Twin", visibility=VisibilityEnum.PUBLIC)
    db_session.add(first)
    db_session.flush()
    second = Character(owner_id=u.id, name="twin", visibility=VisibilityEnum.PUBLIC)
    db_session.add(second)
    db_session.commit()
    for _ in range(5):
        [r] = resolve_mentions(["@TWIN"], db_session)
        assert r["mentioned_character_id"] == first.id


def test_legacy_mention_parser_limitation_is_documented():
    """KNOWN LIMITATION, pinned so it is not mistaken for a bug fix target here:
    the legacy @ parser takes ASCII [A-Za-z0-9_] only. Multi-word and
    non-ASCII names are not fully addressable. W-10 (character tagging)
    replaces this path; do not widen the regex as a side quest."""
    assert parse_mention_texts("hi @Leo Vance") == ["@Leo"]
    assert parse_mention_texts("hi @Zoë") == ["@Zo"]
    assert parse_mention_texts("hi @林黛玉") == []
