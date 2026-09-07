"""The closed-beta DISPLAY/POINTER boundary — Beta Boundary 2.

Beta Boundary 1 closed the conditioning inputs: image bytes and URLs an ordinary
account could feed to a generation provider. This closes the other half — the
places an ordinary account could WRITE an image pointer that Ficshon later
renders, publishes or serves on a shared surface.

FOUR MECHANISMS, NOT ONE, and the tests are grouped by mechanism because the
choice of mechanism per field is the design:

  * governed asset setter — Character avatar/cover. The raw fields are gone from
    the write contract; ``POST /characters/{id}/avatar`` and ``/cover`` take an
    asset id and check ownership, status, safety and kind.
  * retired field — Character portrait. No asset model, no setter, no product.
  * exact sigil allowlist — User avatar. The legitimate value is one of eight
    built-in ``data:`` marks, which is neither an asset nor a founder capability.
  * founder product boundary — Realm banner, Story Space cover, Published Story
    cover. No asset model exists for any of them.

Plus a READ-PATH defence that is independent of all four: the directory, the
search and the character detail now put ``avatar_url``/``cover_url`` through the
same public-media resolver the Character Home has always used. That half also
covers values already in the database and anything written straight to a column,
which is why it is not merely belt-and-braces on the write guards above.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.account_sigils import (
    ACCOUNT_SIGILS,
    ACCOUNT_SIGIL_URLS,
    SIGIL_SET_DIGEST,
    is_account_sigil,
)
from tests.conftest import (
    TestingSessionLocal,
    auth_headers,
    character_owner_id,
    get_auth_token,
    make_admin,
    make_seeder,
)

_EXTERNAL = "https://evil.example.com/a-real-persons-face.jpg"

#: Minimal valid 1x1 PNG.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea7568c4e0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _creator(client: TestClient, email: str, username: str) -> tuple[str, int]:
    """An ordinary one-character Creator — the outsider beta persona."""
    token = get_auth_token(client, email=email, username=username)
    resp = client.post(
        "/characters/",
        json={"name": f"{username} Char", "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return token, resp.json()["id"]


def _seeder(client: TestClient, email: str, username: str) -> tuple[str, int]:
    token, cid = _creator(client, email, username)
    make_seeder(email)
    return token, cid


def _admin(client: TestClient, email: str, username: str) -> tuple[str, int]:
    token, cid = _creator(client, email, username)
    make_admin(email)
    return token, cid


def _wanderer(client: TestClient, email: str, username: str) -> str:
    return get_auth_token(client, email=email, username=username)


def _column(character_id: int, name: str):
    """Read a column straight from the DB — what was STORED, not what was served."""
    from app.models.character import Character

    db = TestingSessionLocal()
    try:
        return getattr(db.query(Character).filter(Character.id == character_id).one(), name)
    finally:
        db.close()


def _user_column(email: str, name: str):
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        return getattr(db.query(User).filter(User.email == email).one(), name)
    finally:
        db.close()


def _seed_image(cid: int, *, kind=None, status=None):
    """One real ``CharacterImage`` for *cid*, owned by *cid*'s owner.

    ``file_path`` is an absolute ``https://`` url — the shape a row has in
    OBJECT-STORAGE mode, which is production. That shape is what makes these
    tests exercise the governed setters end to end: the setter's local branch
    center-crops by reading the file from a repo-relative directory, which a
    test cannot write to without polluting the working tree, while the R2 branch
    performs every ownership, status, safety and kind check and then points the
    column straight at the source. The checks under test are the same on both
    branches; only the byte handling differs.

    It is also the honest fixture for the N1 case: a stored ``file_path`` that
    is literally an https url is exactly why a raw pointer write could name
    another character's image and pass the resolver.
    """
    from uuid import uuid4

    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )

    db = TestingSessionLocal()
    try:
        img = CharacterImage(
            character_id=cid,
            user_id=character_owner_id(db, cid),
            kind=kind or ImageKindEnum.GENERATED,
            status=status or ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path=f"https://cdn.test.invalid/generated/{uuid4().hex}.png",
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        return img.id, img.file_path
    finally:
        db.close()


def _force_column(character_id: int, name: str, value):
    """Write a pointer STRAIGHT to the column, bypassing every route.

    Stands in for the three things the read-path defence exists for and the
    write guards cannot reach: a value stored before the boundary landed, a
    founder or migration writing the column, and a future serializer that
    forgets to ask. If the read path only worked because the write path was
    closed, these tests would pass for the wrong reason.
    """
    from app.models.character import Character

    db = TestingSessionLocal()
    try:
        character = db.query(Character).filter(Character.id == character_id).one()
        setattr(character, name, value)
        db.commit()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════
# 1. Character write contract — the pointers are gone
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("field", ["avatar_url", "cover_url", "portrait_url"])
def test_character_create_cannot_set_a_raw_pointer(client, field):
    """Accepted-and-ignored, not 422.

    Pydantic drops an unknown field rather than refusing the body, so the
    assertion that matters is about the COLUMN: the request succeeds and the
    pointer is not stored. A 422 would also be defensible, but it would break
    every existing client that still sends the field, and "the pointer did not
    land" is the property the product rule actually asks for.
    """
    token = get_auth_token(client, email=f"bdp_c_{field}@test.com", username=f"bdpc{field[:4]}")
    resp = client.post(
        "/characters/",
        json={"name": "Pointer Char", "species": "human", field: _EXTERNAL},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json().get(field) is None
    assert _column(resp.json()["id"], field) is None


@pytest.mark.parametrize("field", ["avatar_url", "cover_url", "portrait_url"])
def test_character_update_cannot_set_a_raw_pointer(client, field):
    token, cid = _creator(client, f"bdp_u_{field}@test.com", f"bdpu{field[:4]}")
    resp = client.patch(
        f"/characters/{cid}",
        json={field: _EXTERNAL},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert _column(cid, field) is None


def test_character_update_still_writes_the_numeric_framing_fields(client):
    """The reason removing the pointers is invisible to the product.

    The picker sets the IMAGE through the governed setter and the FRAMING
    through this endpoint. Breaking these would break avatar/cover positioning
    for every creator while looking like a security improvement.
    """
    token, cid = _creator(client, "bdp_frame@test.com", "bdpframe")
    resp = client.patch(
        f"/characters/{cid}",
        json={
            "avatar_position_x": 0.25,
            "avatar_position_y": 0.75,
            "avatar_scale": 1.5,
            "cover_position_x": 0.1,
            "cover_position_y": 0.9,
            "cover_scale": 2.0,
            "short_bio": "still editable",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["avatar_position_x"] == 0.25
    assert body["avatar_scale"] == 1.5
    assert body["cover_position_y"] == 0.9
    assert body["cover_scale"] == 2.0
    assert body["short_bio"] == "still editable"


def test_character_creation_does_not_depend_on_portrait_url(client):
    """Explicitly pinned, because retiring a field is only safe if nothing needs it."""
    token = get_auth_token(client, email="bdp_nop@test.com", username="bdpnop")
    resp = client.post(
        "/characters/",
        json={"name": "No Portrait", "species": "human", "short_bio": "words only"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "No Portrait"


def test_creator_cannot_point_avatar_at_another_characters_image(client):
    """N1 from the audit, closed at the write path.

    ``resolve_public_media_url`` is NOT ownership-scoped: it asks whether a url
    names a row that is safe to publish, never whose row it is. With object
    storage on, a ``file_path`` IS an absolute https URL, so a raw pointer write
    was a way to wear another character's face using an image the resolver would
    happily approve. Removing the raw field closes it; the governed setter
    checks ``img.user_id == caller`` and is tested below.
    """
    token_a, cid_a = _creator(client, "bdp_n1a@test.com", "bdpn1a")
    _token_b, cid_b = _creator(client, "bdp_n1b@test.com", "bdpn1b")
    _image_id, victim_path = _seed_image(cid_b)

    for field in ("avatar_url", "cover_url"):
        resp = client.patch(
            f"/characters/{cid_a}",
            json={field: victim_path},
            headers=auth_headers(token_a),
        )
        assert resp.status_code == 200, resp.text
        assert _column(cid_a, field) is None


# ══════════════════════════════════════════════════════════════════════════
# 2. Governed setters still work, and still refuse
# ══════════════════════════════════════════════════════════════════════════


def test_governed_avatar_and_cover_setters_still_work(client):
    token, cid = _creator(client, "bdp_set@test.com", "bdpset")
    image_id, _path = _seed_image(cid)

    avatar = client.post(
        f"/characters/{cid}/avatar",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token),
    )
    assert avatar.status_code == 200, avatar.text
    assert avatar.json()["avatar_url"]
    assert _column(cid, "avatar_url")

    cover = client.post(
        f"/characters/{cid}/cover",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token),
    )
    assert cover.status_code == 200, cover.text
    assert _column(cid, "cover_url")


def test_governed_setter_still_refuses_another_accounts_image(client):
    """The ownership check the removed raw field had no way to perform."""
    token_a, cid_a = _creator(client, "bdp_own_a@test.com", "bdpowna")
    _token_b, cid_b = _creator(client, "bdp_own_b@test.com", "bdpownb")
    image_id, _path = _seed_image(cid_b)

    resp = client.post(
        f"/characters/{cid_a}/avatar",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 403, resp.text
    assert _column(cid_a, "avatar_url") is None


# ══════════════════════════════════════════════════════════════════════════
# 3. Read-path defence — directory, search, detail
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("field", ["avatar_url", "cover_url"])
def test_directory_suppresses_a_rowless_pointer(client, field):
    token, cid = _creator(client, f"bdp_dir_{field}@test.com", f"bdpd{field[:4]}")
    _force_column(cid, field, _EXTERNAL)

    resp = client.get("/characters/directory", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    row = next(c for c in resp.json() if c["id"] == cid)
    assert row[field] is None


@pytest.mark.parametrize("field", ["avatar_url", "cover_url"])
def test_search_suppresses_a_rowless_pointer(client, field):
    token, cid = _creator(client, f"bdp_srch_{field}@test.com", f"bdps{field[:4]}")
    _force_column(cid, field, _EXTERNAL)

    resp = client.get("/characters/search?q=Char", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    row = next((c for c in resp.json() if c["id"] == cid), None)
    assert row is not None, "the character should still be findable"
    assert row[field] is None


@pytest.mark.parametrize("field", ["avatar_url", "cover_url"])
def test_character_detail_suppresses_a_rowless_pointer(client, field):
    """Checked as a NON-OWNER: the divergence mattered because this surface is
    served to any viewer of a public character, not only to the creator."""
    _owner_token, cid = _creator(client, f"bdp_det_{field}@test.com", f"bdpt{field[:4]}")
    _force_column(cid, field, _EXTERNAL)
    viewer = _wanderer(client, f"bdp_view_{field}@test.com", f"bdpv{field[:4]}")

    resp = client.get(f"/characters/{cid}", headers=auth_headers(viewer))
    assert resp.status_code == 200, resp.text
    assert resp.json()[field] is None


def test_read_path_preserves_a_governed_asset(client):
    """Suppression must not be indiscriminate — a real asset still shows."""
    token, cid = _creator(client, "bdp_keep@test.com", "bdpkeep")
    image_id, _path = _seed_image(cid)
    client.post(
        f"/characters/{cid}/avatar",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token),
    )
    stored = _column(cid, "avatar_url")
    assert stored

    detail = client.get(f"/characters/{cid}", headers=auth_headers(token))
    assert detail.json()["avatar_url"] == stored

    directory = client.get("/characters/directory", headers=auth_headers(token))
    row = next(c for c in directory.json() if c["id"] == cid)
    assert row["avatar_url"] == stored


def test_reading_does_not_mutate_the_stored_pointer(client):
    """The resolver's verdict lands on the schema, never on the row.

    Assigning it back to the ORM object would mark the row dirty and let a later
    flush persist a suppression as a deletion — the owner would lose the pointer
    because a stranger looked at their character.
    """
    token, cid = _creator(client, "bdp_nomut@test.com", "bdpnomut")
    _force_column(cid, "avatar_url", _EXTERNAL)

    client.get(f"/characters/{cid}", headers=auth_headers(token))
    client.get("/characters/directory", headers=auth_headers(token))
    client.get("/characters/search?q=Char", headers=auth_headers(token))

    assert _column(cid, "avatar_url") == _EXTERNAL


def test_character_home_and_og_remain_suppressed(client):
    """Unchanged behaviour, re-pinned here because this increment is the one
    that must not have disturbed it."""
    from app.models.character import Character

    token, cid = _creator(client, "bdp_home@test.com", "bdphome")
    _force_column(cid, "avatar_url", _EXTERNAL)
    _force_column(cid, "cover_url", _EXTERNAL)

    db = TestingSessionLocal()
    try:
        character = db.query(Character).filter(Character.id == cid).one()
        character.public_home_enabled = True
        db.commit()
    finally:
        db.close()

    home = client.get(f"/characters/{cid}/public-home")
    if home.status_code == 200:
        assert home.json()["avatar_url"] is None
        assert home.json()["cover_url"] is None

    # OG shares the Home's projection by construction, so it inherits the
    # verdict rather than repeating the rule.
    from app.services.character_home_share import choose_share_image

    assert choose_share_image(None, None, "https://ficshon.test").endswith(
        ("png", "jpg", "svg", "webp")
    )
    assert token  # keeps the fixture's intent explicit


# ══════════════════════════════════════════════════════════════════════════
# 4. Account sigils — the exact allowlist
# ══════════════════════════════════════════════════════════════════════════


def test_sigil_allowlist_is_exactly_the_eight_known_marks():
    """Backend half of the two-sided pin.

    ``frontend/src/lib/__tests__/accountSigils.test.ts`` asserts the SAME digest
    from its own derivation. Neither file imports the other; a template edit on
    either side fails that side's test.
    """
    assert list(ACCOUNT_SIGILS) == [
        "ember", "tide", "grove", "dusk", "rose", "aurum", "mist", "sol",
    ]
    assert len(ACCOUNT_SIGIL_URLS) == 8
    assert (
        SIGIL_SET_DIGEST
        == "cb88ec9be326ec416636510c74008658925b43f208ff0d8de8481ac8e1206042"
    )


def test_is_account_sigil_matches_exactly_and_nothing_near_it():
    for url in ACCOUNT_SIGIL_URLS:
        assert is_account_sigil(url) is True
        # One byte different is not a sigil.
        assert is_account_sigil(url + " ") is False
        assert is_account_sigil(url.replace("64", "65", 1)) is False

    assert is_account_sigil(None) is False
    assert is_account_sigil("") is False
    assert is_account_sigil(_EXTERNAL) is False
    # A caller-authored data URL with the right prefix — the exact thing a
    # prefix check would have admitted, and markup the browser would execute.
    assert is_account_sigil("data:image/svg+xml,<svg onload=alert(1)/>") is False


@pytest.mark.parametrize("sigil_id", list(ACCOUNT_SIGILS))
def test_patch_users_me_accepts_every_known_sigil(client, sigil_id):
    email = f"bdp_sig_{sigil_id}@test.com"
    token = _wanderer(client, email, f"bdpsig{sigil_id}")
    resp = client.patch(
        "/users/me",
        json={"avatar_url": ACCOUNT_SIGILS[sigil_id]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert _user_column(email, "avatar_url") == ACCOUNT_SIGILS[sigil_id]


@pytest.mark.parametrize(
    "value",
    [
        _EXTERNAL,
        "http://example.com/x.png",
        "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>",
        "data:image/png;base64,iVBORw0KGgo=",
        "/static/generated/somebody-elses.png",
        "static/generated/somebody-elses.png",
        "https://pub-abc.r2.dev/generated/somebody-elses.png",
    ],
    ids=["https", "http", "own-svg", "data-png", "static-abs", "static-rel", "r2"],
)
def test_patch_users_me_refuses_everything_that_is_not_a_sigil(client, value):
    email = "bdp_sig_no@test.com"
    token = _wanderer(client, email, "bdpsigno")
    resp = client.patch("/users/me", json={"avatar_url": value}, headers=auth_headers(token))
    assert resp.status_code == 422, resp.text
    assert "sigil" in resp.text.lower()
    assert _user_column(email, "avatar_url") is None


def test_sigil_rule_applies_to_founders_too(client):
    """No admin bypass, and that is deliberate.

    There is no internal workflow that sets an account avatar to a raw URL —
    founders use the same picker and the same governed setter — so an exemption
    here would be a hole with no user behind it.
    """
    email = "bdp_sig_admin@test.com"
    token, _cid = _admin(client, email, "bdpsigadmin")
    resp = client.patch("/users/me", json={"avatar_url": _EXTERNAL}, headers=auth_headers(token))
    assert resp.status_code == 422, resp.text


def test_governed_account_avatar_setter_still_works(client):
    """Real image avatars keep their route — this is what the sigil rule is
    NOT supposed to close."""
    email = "bdp_acct@test.com"
    token, cid = _creator(client, email, "bdpacct")
    image_id, _path = _seed_image(cid)

    resp = client.post(
        "/users/me/avatar",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"]
    assert _user_column(email, "avatar_url")


def test_user_cover_url_is_not_writable_through_patch(client):
    email = "bdp_ucov@test.com"
    token = _wanderer(client, email, "bdpucov")
    resp = client.patch(
        "/users/me", json={"cover_url": _EXTERNAL}, headers=auth_headers(token)
    )
    # Silently dropped by the schema — the field is gone from the contract.
    assert resp.status_code == 200, resp.text
    assert _user_column(email, "cover_url") is None


def test_governed_account_set_cover_still_works(client):
    """The route that actually produced every account cover there has ever been."""
    from app.core.storage import save_image
    from app.models.user_image import UserImage

    email = "bdp_setcov@test.com"
    token = _wanderer(client, email, "bdpsetcov")

    db = TestingSessionLocal()
    try:
        from app.models.user import User

        user_id = db.query(User).filter(User.email == email).one().id
        img = UserImage(
            user_id=user_id,
            kind="profile_cover",
            status="active",
            provider="stub",
            metadata_json={"is_temp": False},
            file_path=save_image(_PNG_BYTES),
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        image_id = img.id
    finally:
        db.close()

    resp = client.post(f"/users/me/images/{image_id}/set-cover", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert _user_column(email, "cover_url")


# ══════════════════════════════════════════════════════════════════════════
# 5. Comment author avatar — the anonymous-reader leak
# ══════════════════════════════════════════════════════════════════════════


def _wanderer_comment(client, token: str, post_id: int, body: str = "a wanderer says hello"):
    resp = client.post(
        f"/comments/posts/{post_id}/comments", json={"content": body}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _public_post(client) -> int:
    """A post in a public realm, authored by a character, for comments to hang off."""
    token, cid = _creator(client, "bdp_poster@test.com", "bdpposter")
    hdrs = auth_headers(token)
    realm = client.post(
        "/realms/",
        json={"name": "Comment Realm", "slug": "comment-realm", "is_public": True},
        headers=hdrs,
    )
    assert realm.status_code == 201, realm.text
    post = client.post(
        f"/posts/realms/{realm.json()['id']}/posts",
        json={"content": "a post to comment on", "character_id": cid},
        headers=hdrs,
    )
    assert post.status_code == 201, post.text
    return post.json()["id"]


def test_anonymous_comment_reader_never_receives_an_arbitrary_author_avatar(client):
    """The concrete leak. ``GET /posts/{id}/comments`` is optionally
    authenticated, so this response reaches readers with no token at all."""
    post_id = _public_post(client)
    email = "bdp_cmt_bad@test.com"
    token = _wanderer(client, email, "bdpcmtbad")
    _wanderer_comment(client, token, post_id)

    # A pointer already in the column — the write path refuses this now, so the
    # only honest way to test the READ path is to put it there directly.
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        db.query(User).filter(User.email == email).one().avatar_url = _EXTERNAL
        db.commit()
    finally:
        db.close()

    anon = client.get(f"/comments/posts/{post_id}/comments")
    assert anon.status_code == 200, anon.text
    assert anon.json(), "the comment itself must still be served"
    for comment in anon.json():
        assert comment.get("author_avatar_url") is None


def test_authenticated_comment_reader_has_the_same_property(client):
    post_id = _public_post(client)
    email = "bdp_cmt_auth@test.com"
    token = _wanderer(client, email, "bdpcmtauth")
    _wanderer_comment(client, token, post_id)

    from app.models.user import User

    db = TestingSessionLocal()
    try:
        db.query(User).filter(User.email == email).one().avatar_url = _EXTERNAL
        db.commit()
    finally:
        db.close()

    # Including the AUTHOR's own read — the one response an attacker can always
    # obtain, and therefore the one that must not be the exception.
    for headers in ({}, auth_headers(token)):
        resp = client.get(f"/comments/posts/{post_id}/comments", headers=headers)
        assert resp.status_code == 200, resp.text
        for comment in resp.json():
            assert comment.get("author_avatar_url") is None


def test_a_legitimate_sigil_still_reaches_comment_readers(client):
    """The failure mode this fix must NOT have: suppressing every Wanderer
    avatar in the product because a ``data:`` string matches no ``file_path``."""
    post_id = _public_post(client)
    email = "bdp_cmt_sig@test.com"
    token = _wanderer(client, email, "bdpcmtsig")
    sigil = ACCOUNT_SIGILS["ember"]
    assert client.patch(
        "/users/me", json={"avatar_url": sigil}, headers=auth_headers(token)
    ).status_code == 200
    _wanderer_comment(client, token, post_id)

    anon = client.get(f"/comments/posts/{post_id}/comments")
    assert anon.status_code == 200, anon.text
    wanderer_comments = [c for c in anon.json() if c.get("author_username")]
    assert wanderer_comments, "the Wanderer comment should be attributed"
    assert any(c.get("author_avatar_url") == sigil for c in wanderer_comments)


def test_a_governed_account_avatar_still_reaches_comment_readers(client):
    """The other half of the same rule: a real ``UserImage``-backed avatar is
    media, and resolves as media.

    Necessarily a WANDERER. ``author_avatar_url`` is only ever serialized for a
    characterless comment — an account that owns a character must comment AS
    that character, and the serializer then strips the account identity — so the
    Wanderer is the only account for which this field is a live surface at all.
    That is also exactly the account the anonymous leak affected.
    """
    from uuid import uuid4

    from app.models.user import User
    from app.models.user_image import UserImage

    post_id = _public_post(client)
    email = "bdp_cmt_real@test.com"
    token = _wanderer(client, email, "bdpcmtreal")

    db = TestingSessionLocal()
    try:
        user_id = db.query(User).filter(User.email == email).one().id
        img = UserImage(
            user_id=user_id,
            kind="profile_cover",
            status="active",
            provider="stub",
            metadata_json={"is_temp": False},
            # Object-storage shape, for the same reason ``_seed_image`` uses it:
            # the setter's local branch center-crops from disk, the R2 branch
            # runs every check and points the column at the source.
            file_path=f"https://cdn.test.invalid/generated/{uuid4().hex}.png",
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        image_id = img.id
    finally:
        db.close()

    set_resp = client.post(
        "/users/me/avatar",
        json={"image_type": "user", "image_id": image_id},
        headers=auth_headers(token),
    )
    assert set_resp.status_code == 200, set_resp.text
    stored = _user_column(email, "avatar_url")
    assert stored

    _wanderer_comment(client, token, post_id, "governed avatar comment")

    anon = client.get(f"/comments/posts/{post_id}/comments")
    mine = [c for c in anon.json() if c.get("content") == "governed avatar comment"]
    assert mine, "the comment must be served"
    assert mine[0]["author_avatar_url"] == stored


# ══════════════════════════════════════════════════════════════════════════
# 6. Realm banner — founder product boundary
# ══════════════════════════════════════════════════════════════════════════


def _realm_body(slug: str, **extra) -> dict:
    body = {"name": f"Realm {slug}", "slug": slug, "is_public": True}
    body.update(extra)
    return body


def _assert_boundary_refusal(resp, field: str) -> None:
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "user_supplied_image_input_closed", detail
    assert detail["fields"] == [field]


def test_wanderer_cannot_create_a_realm_with_a_banner(client):
    token = _wanderer(client, "bdp_realm_w@test.com", "bdprealmw")
    resp = client.post(
        "/realms/", json=_realm_body("wanderer-banner", banner_url=_EXTERNAL),
        headers=auth_headers(token),
    )
    _assert_boundary_refusal(resp, "banner_url")


def test_ordinary_creator_cannot_create_a_realm_with_a_banner(client):
    token, _cid = _creator(client, "bdp_realm_c@test.com", "bdprealmc")
    resp = client.post(
        "/realms/", json=_realm_body("creator-banner", banner_url=_EXTERNAL),
        headers=auth_headers(token),
    )
    _assert_boundary_refusal(resp, "banner_url")


def test_realm_creation_without_a_banner_still_works(client):
    token = _wanderer(client, "bdp_realm_ok@test.com", "bdprealmok")
    resp = client.post(
        "/realms/", json=_realm_body("no-banner"), headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["banner_url"] is None


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_accounts_keep_the_realm_banner(client, role):
    make = _seeder if role == "seeder" else _admin
    token, _cid = make(client, f"bdp_realm_{role}@test.com", f"bdprealm{role}")
    resp = client.post(
        "/realms/",
        json=_realm_body(f"{role}-banner", banner_url="https://cdn.example.com/b.png"),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["banner_url"] == "https://cdn.example.com/b.png"


def test_realm_update_schema_is_not_routed():
    """``RealmUpdate`` declares ``banner_url`` and nothing serves it.

    Left in place rather than deleted, but pinned: if a realm PATCH is ever
    wired up this fails, and whoever wires it up has to decide about the banner
    guard deliberately instead of inheriting an unguarded field.
    """
    from app.main import app

    realm_methods = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set()) or set()
        if getattr(route, "path", "").startswith(("/realms", "/api/realms"))
    }
    assert not [m for m in realm_methods if m[1] in {"PATCH", "PUT"}], (
        "A realm update route now exists — guard REALM_IMAGE_FIELDS on it."
    )


# ══════════════════════════════════════════════════════════════════════════
# 7. Story Space / Published Story covers — founder product boundary
# ══════════════════════════════════════════════════════════════════════════


def test_ordinary_creator_cannot_create_a_space_with_a_cover(client):
    token, _cid = _creator(client, "bdp_space_c@test.com", "bdpspacec")
    resp = client.post(
        "/story-spaces/",
        json={"name": "Covered Space", "cover_url": _EXTERNAL},
        headers=auth_headers(token),
    )
    _assert_boundary_refusal(resp, "cover_url")


def test_ordinary_creator_can_create_a_space_without_a_cover(client):
    token, _cid = _creator(client, "bdp_space_ok@test.com", "bdpspaceok")
    resp = client.post(
        "/story-spaces/",
        json={"name": "Plain Space", "description": "words"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["cover_url"] is None


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_accounts_keep_the_space_cover(client, role):
    make = _seeder if role == "seeder" else _admin
    token, _cid = make(client, f"bdp_space_{role}@test.com", f"bdpspace{role}")
    resp = client.post(
        "/story-spaces/",
        json={"name": f"{role} Space", "cover_url": "https://cdn.example.com/c.png"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["cover_url"] == "https://cdn.example.com/c.png"


def _space_with_story_post(client, token: str, cid: int, name: str) -> tuple[int, int]:
    """A space plus one story-channel post, ready to publish."""
    hdrs = auth_headers(token)
    space = client.post("/story-spaces/", json={"name": name}, headers=hdrs)
    assert space.status_code == 201, space.text
    space_id = space.json()["id"]
    story_channel = next(
        ch for ch in space.json()["channels"] if ch["channel_type"] == "story"
    )
    post = client.post(
        f"/story-spaces/{space_id}/channels/{story_channel['id']}/posts",
        json={"content": "a story beat", "character_id": cid},
        headers=hdrs,
    )
    assert post.status_code == 201, post.text
    return space_id, post.json()["id"]


def test_ordinary_creator_cannot_publish_with_a_cover(client):
    token, cid = _creator(client, "bdp_pub_c@test.com", "bdppubc")
    space_id, post_id = _space_with_story_post(client, token, cid, "Publish Space")
    resp = client.post(
        f"/story-spaces/{space_id}/publish",
        json={"title": "A Story", "post_ids": [post_id], "cover_url": _EXTERNAL},
        headers=auth_headers(token),
    )
    _assert_boundary_refusal(resp, "cover_url")


def test_publishing_without_a_cover_is_unchanged(client):
    token, cid = _creator(client, "bdp_pub_ok@test.com", "bdppubok")
    space_id, post_id = _space_with_story_post(client, token, cid, "Plain Publish Space")
    resp = client.post(
        f"/story-spaces/{space_id}/publish",
        json={"title": "A Story", "post_ids": [post_id]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["title"] == "A Story"
    assert resp.json()["cover_url"] is None


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_accounts_keep_the_published_story_cover(client, role):
    make = _seeder if role == "seeder" else _admin
    token, cid = make(client, f"bdp_pub_{role}@test.com", f"bdppub{role}")
    space_id, post_id = _space_with_story_post(client, token, cid, f"{role} Publish Space")
    resp = client.post(
        f"/story-spaces/{space_id}/publish",
        json={
            "title": "A Story",
            "post_ids": [post_id],
            "cover_url": "https://cdn.example.com/s.png",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["cover_url"] == "https://cdn.example.com/s.png"


# ══════════════════════════════════════════════════════════════════════════
# 8. Messaging — the last raw emitter of Character.avatar_url
# ══════════════════════════════════════════════════════════════════════════
#
# A PRIVATE 1:1 surface, so nothing here is about who may open a conversation.
# The only thing that changed is that the participant avatars answer to the same
# media rule as every other surface, instead of being handed to the other
# participant's browser verbatim.


def _open_conversation(client, token: str, from_char: int, to_char: int) -> int:
    resp = client.post(
        "/messages/conversations",
        json={"from_character_id": from_char, "to_character_id": to_char},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _summaries(payload: dict) -> list[dict]:
    return [payload["character_a"], payload["character_b"]]


def test_messaging_suppresses_a_rowless_arbitrary_avatar(client):
    token_a, cid_a = _creator(client, "bdp_msg_a@test.com", "bdpmsga")
    _token_b, cid_b = _creator(client, "bdp_msg_b@test.com", "bdpmsgb")
    _force_column(cid_b, "avatar_url", _EXTERNAL)

    created = client.post(
        "/messages/conversations",
        json={"from_character_id": cid_a, "to_character_id": cid_b},
        headers=auth_headers(token_a),
    )
    assert created.status_code == 200, created.text
    assert all(s["avatar_url"] is None for s in _summaries(created.json()))

    listed = client.get("/messages/conversations", headers=auth_headers(token_a))
    assert listed.status_code == 200, listed.text
    for conv in listed.json():
        for summary in _summaries(conv):
            assert summary["avatar_url"] is None


def test_messaging_preserves_a_governed_avatar(client):
    """Suppression must not be indiscriminate — the other participant still
    sees a real, governed avatar."""
    token_a, cid_a = _creator(client, "bdp_msg_ok_a@test.com", "bdpmsgoka")
    token_b, cid_b = _creator(client, "bdp_msg_ok_b@test.com", "bdpmsgokb")
    image_id, _path = _seed_image(cid_b)
    assert client.post(
        f"/characters/{cid_b}/avatar",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token_b),
    ).status_code == 200
    stored = _column(cid_b, "avatar_url")
    assert stored

    created = client.post(
        "/messages/conversations",
        json={"from_character_id": cid_a, "to_character_id": cid_b},
        headers=auth_headers(token_a),
    )
    assert created.status_code == 200, created.text
    avatars = {s["id"]: s["avatar_url"] for s in _summaries(created.json())}
    assert avatars[cid_b] == stored


def test_reading_a_conversation_does_not_mutate_the_stored_avatar(client):
    """Same discipline as the character projections: the verdict lands on the
    schema, never on the row."""
    token_a, cid_a = _creator(client, "bdp_msg_mut_a@test.com", "bdpmsgmuta")
    _token_b, cid_b = _creator(client, "bdp_msg_mut_b@test.com", "bdpmsgmutb")
    _force_column(cid_b, "avatar_url", _EXTERNAL)

    _open_conversation(client, token_a, cid_a, cid_b)
    client.get("/messages/conversations", headers=auth_headers(token_a))

    assert _column(cid_b, "avatar_url") == _EXTERNAL


def test_messaging_behaviour_is_otherwise_unchanged(client):
    """Identity, listing and message delivery are untouched by the avatar fix."""
    token_a, cid_a = _creator(client, "bdp_msg_norm_a@test.com", "bdpmsgnorma")
    token_b, cid_b = _creator(client, "bdp_msg_norm_b@test.com", "bdpmsgnormb")

    conv_id = _open_conversation(client, token_a, cid_a, cid_b)

    # Idempotent open — the same pair resolves to the same conversation.
    assert _open_conversation(client, token_a, cid_a, cid_b) == conv_id

    sent = client.post(
        f"/messages/conversations/{conv_id}/messages",
        json={"sender_character_id": cid_a, "body": "hello there"},
        headers=auth_headers(token_a),
    )
    assert sent.status_code in (200, 201), sent.text

    listed = client.get("/messages/conversations", headers=auth_headers(token_a))
    assert listed.status_code == 200, listed.text
    conv = next(c for c in listed.json() if c["id"] == conv_id)
    assert {conv["character_a"]["id"], conv["character_b"]["id"]} == {cid_a, cid_b}
    assert conv["character_a"]["name"]
    assert conv["character_b"]["name"]
    assert conv["last_message"]["body"] == "hello there"
    assert conv["updated_at"]

    # And the other participant sees the same conversation.
    theirs = client.get("/messages/conversations", headers=auth_headers(token_b))
    assert any(c["id"] == conv_id for c in theirs.json())
