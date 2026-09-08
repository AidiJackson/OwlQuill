"""ARCHIVED means WITHDRAWN FROM FICSHON — the beta lifecycle rule.

THE PRODUCT REVERSAL THIS FILE PINS. Until this increment, ARCHIVED was read as
a POST-ATTACHMENT rule only. ``is_public_post_image`` required ACTIVE; the
avatar/cover resolver did not, and
``test_character_avatar_safety_on_shared_surfaces`` pinned that divergence on
purpose — an image its owner had deleted stayed eligible as a character's face
on the Character Home, the OG card, the directory and every post the character
had ever written.

That rule has changed, deliberately, for beta. Pressing delete is a withdrawal
from the product:

    an ARCHIVED governed media asset does not appear on a non-owner /
    non-admin Ficshon surface, does not resolve through the public media
    resolvers, cannot be selected or promoted back into live canon without an
    explicit restore, and does not remain as the current governed avatar or
    cover pointer.

There is no restore in beta. The row and its provenance stay in the database;
the product offers no way back.

WHAT THIS IS NOT. It is APPLICATION-LAYER withdrawal. Nothing here deletes
bytes, changes bucket privacy or purges a cache, and an anonymous party already
holding the direct public R2/static URL can still fetch the object after the
archive. Known, accepted beta storage debt — see
``test_an_archived_asset_is_withdrawn_not_deleted`` at the end of this file,
which states it as an assertion rather than leaving it to a comment.

TWO LATER SECTIONS CLOSE FINDINGS THE FIRST STATIC SWEEP TURNED UP rather
than anything the original design missed: ``use-existing-anchor``, the third
member of the "an old row is not a restore" defect class, and
``GET /users/{username}``, the last shared surface that emitted
``User.avatar_url`` raw and so applied neither provenance nor lifecycle.

THE SEPARATION OF CONCERNS SURVIVES THE REVERSAL. ``is_public_surface_safe``
still represents PROVENANCE alone and is still shared, unchanged, with the
gallery and post-attachment rules. ``is_lifecycle_active`` is a separate
predicate. The avatar/cover rule is their COMPOSITION, ``is_public_media``.
Collapsing the two into one widened predicate would pass every assertion below
and is exactly what must not happen, so ``test_provenance_and_lifecycle_stay_
separable`` asserts the halves independently.
"""
from datetime import datetime
from uuid import uuid4

import pytest

from app.core.account_sigils import ACCOUNT_SIGIL_URLS
from app.models.character import Character
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.comment import Comment
from app.models.post import ContentTypeEnum, Post
from app.models.realm import Realm, RealmMembership
from app.models.user import User
from app.models.user_image import UserImage
from app.schemas.character_image import (
    is_lifecycle_active,
    is_public_media,
    is_public_surface_safe,
)
from app.services.character_home_media import (
    candidate_file_paths,
    resolve_account_avatar_url,
    resolve_public_media_url,
    resolve_public_media_urls,
    urls_naming_file_path,
)
from tests.conftest import auth_headers, get_auth_token


AVATAR = "/static/generated/withdrawn-avatar.png"
COVER = "/static/generated/withdrawn-cover.png"


# ── Fixtures and helpers ──────────────────────────────────────────────────────

def _user(db_session, email) -> User:
    return db_session.query(User).filter(User.email == email).first()


def _char_image(db_session, *, character_id, user_id, file_path,
                status=ImageStatusEnum.ACTIVE, kind=ImageKindEnum.GENERATED,
                provider="fal", metadata=None):
    img = CharacterImage(
        character_id=character_id, user_id=user_id, kind=kind, status=status,
        visibility=ImageVisibilityEnum.PRIVATE, provider=provider,
        prompt_summary="fixture",
        metadata_json={"library": True} if metadata is None else metadata,
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


def _user_image(db_session, *, user_id, file_path, status="active",
                kind="profile_cover"):
    img = UserImage(
        user_id=user_id, kind=kind, status=status, provider="openai",
        prompt_summary="fixture", metadata_json={"is_temp": False},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


@pytest.fixture()
def home(client, db_session):
    """A published Character Home with an avatar and a cover, and a viewer."""
    owner_token = get_auth_token(client, email="wd-own@test.com", username="wdown")
    resp = client.post(
        "/characters/",
        json={"name": "Vela", "species": "human", "visibility": "public"},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    owner = _user(db_session, "wd-own@test.com")

    character = db_session.query(Character).filter(Character.id == cid).first()
    character.public_home_enabled = True
    character.avatar_url = AVATAR
    character.cover_url = COVER
    db_session.commit()

    viewer_token = get_auth_token(client, email="wd-see@test.com", username="wdsee")
    return {
        "owner_token": owner_token, "owner_id": owner.id, "owner_username": "wdown",
        "viewer_token": viewer_token, "character_id": cid,
    }


def _add_marking(client, ctx) -> str:
    """A body marking to hang an anchor off. Returns its id."""
    resp = client.post(
        f"/characters/{ctx['character_id']}/body-markings",
        json={"type": "tattoo", "placement": "left_upper_arm",
              "style": "black ink wolf", "size": "large",
              "description": "Wolf tattoo on left upper arm"},
        headers=auth_headers(ctx["owner_token"]),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["markings"][-1]["id"]


def _set_account_avatar(db_session, user_id, url) -> None:
    row = db_session.query(User).filter(User.id == user_id).first()
    row.avatar_url = url
    db_session.commit()


def _set_account_cover(db_session, user_id, url) -> None:
    row = db_session.query(User).filter(User.id == user_id).first()
    row.cover_url = url
    db_session.commit()


def _profile(client, ctx) -> dict:
    """``GET /users/{username}`` as a signed-in NON-OWNER sees it."""
    resp = client.get(f"/users/{ctx['owner_username']}",
                      headers=auth_headers(ctx["viewer_token"]))
    assert resp.status_code == 200, resp.text
    return resp.json()


def public_home(client, ctx) -> dict:
    resp = client.get(f"/characters/{ctx['character_id']}/public-home")
    assert resp.status_code == 200, resp.text
    return resp.json()


def detail(client, ctx, token) -> dict:
    resp = client.get(f"/characters/{ctx['character_id']}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def directory_entry(client, ctx, token) -> dict:
    resp = client.get("/characters/directory", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    for entry in resp.json():
        if entry["id"] == ctx["character_id"]:
            return entry
    raise AssertionError(f"character {ctx['character_id']} absent from the directory")


# ══════════════════════════════════════════════════════════════════════════════
# The predicate itself — pinned hardest, because every surface below inherits it
# ══════════════════════════════════════════════════════════════════════════════

def test_the_resolver_withholds_an_archived_row(client, db_session, home):
    """(A, core) The central enforcement point, asserted directly.

    Every surface in this file is protected BY this one function. Pinning it
    here means the integration tests below are evidence that the surfaces route
    through it, not the only thing standing between an archived image and an
    anonymous visitor.
    """
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png",
                status=ImageStatusEnum.ARCHIVED)

    assert resolve_public_media_url(db_session, AVATAR) is None
    assert resolve_public_media_urls(db_session, [AVATAR]) == {AVATAR: None}


def test_the_resolver_still_publishes_an_active_row(client, db_session, home):
    """(D) The reversal must stop at the images that deserve to be shown."""
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png")

    assert resolve_public_media_url(db_session, AVATAR) == AVATAR
    assert resolve_public_media_urls(db_session, [AVATAR]) == {AVATAR: AVATAR}


def test_the_batched_and_single_forms_agree_about_lifecycle(client, db_session, home):
    """Two implementations of one rule is how a rule quietly becomes two.

    The batch is a rewrite of the per-item predicate, so it gets the same
    lifecycle question asked of it over a mixed page.
    """
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png")
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-cover.png",
                status=ImageStatusEnum.ARCHIVED)

    urls = [AVATAR, COVER, "/static/generated/no-row.png"]
    batched = resolve_public_media_urls(db_session, urls)
    assert batched == {u: resolve_public_media_url(db_session, u) for u in urls}
    assert batched == {AVATAR: AVATAR, COVER: None, "/static/generated/no-row.png": None}


def test_one_archived_row_fails_the_url_closed(client, db_session, home):
    """Ambiguity resolves against publication, as it always has.

    One url, two rows, one archived. The rule was already fail-closed on
    provenance; lifecycle joins it on the same terms rather than inventing a
    "some row is fine" majority vote.
    """
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png")
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png",
                status=ImageStatusEnum.ARCHIVED)

    assert resolve_public_media_url(db_session, AVATAR) is None


def test_provenance_and_lifecycle_stay_separable():
    """The refactor that would pass every other test in this file and be wrong.

    ``is_public_surface_safe`` is shared with the gallery and post-attachment
    rules, which compose lifecycle differently. If lifecycle were folded INTO
    it — the shortest way to make the reversal work — those rules would each
    acquire a second, invisible status check and the distinction that lets them
    differ would be gone. So the halves are asserted independently, on a row
    that is archived and has clean provenance.
    """
    class Row:
        status = ImageStatusEnum.ARCHIVED
        provider = "fal"
        metadata_json = {"library": True}

    row = Row()
    assert is_public_surface_safe(row) is True    # provenance: clean
    assert is_lifecycle_active(row) is False      # lifecycle: withdrawn
    assert is_public_media(row) is False          # the composition decides


def test_lifecycle_fails_closed_on_a_row_with_no_status():
    """A duck-typed stand-in without the column is withdrawn, not published."""
    class Row:
        provider = "fal"
        metadata_json = {}

    assert is_lifecycle_active(Row()) is False
    assert is_public_media(Row()) is False


# ══════════════════════════════════════════════════════════════════════════════
# A/B/D. Representative shared surfaces, through the central resolver
# ══════════════════════════════════════════════════════════════════════════════

def test_archived_avatar_and_cover_are_withdrawn_from_shared_surfaces(
    client, db_session, home
):
    """(A + B) The Home, the character detail and the directory, at once.

    REPRESENTATIVE, not exhaustive, and deliberately so. Every consumer listed
    in ``character_projection`` and ``character_home`` reaches the same
    ``resolve_public_media_url``, which the tests above pin directly; building
    a fixture per consumer would restate one fact ten times. What these three
    prove is that the pointer columns actually travel through the resolver on
    an anonymous surface, an authenticated non-owner surface and a browse
    surface.
    """
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png",
                status=ImageStatusEnum.ARCHIVED)
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-cover.png",
                status=ImageStatusEnum.ARCHIVED, kind=ImageKindEnum.COVER)

    body = public_home(client, home)
    assert body["avatar_url"] is None
    assert body["cover_url"] is None
    # The character is still there. Withdrawal removes the picture, not the
    # writing or the identity.
    assert body["name"] == "Vela"

    seen = detail(client, home, home["viewer_token"])
    assert seen["avatar_url"] is None and seen["cover_url"] is None

    listed = directory_entry(client, home, home["viewer_token"])
    assert listed["avatar_url"] is None and listed["cover_url"] is None


def test_active_avatar_and_cover_still_render_on_shared_surfaces(
    client, db_session, home
):
    """(D) The same three surfaces, with nothing archived."""
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png")
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-cover.png",
                kind=ImageKindEnum.COVER)

    body = public_home(client, home)
    assert body["avatar_url"] == AVATAR
    assert body["cover_url"] == COVER
    assert directory_entry(client, home, home["viewer_token"])["avatar_url"] == AVATAR


def test_archived_avatar_is_withdrawn_from_the_search_surface(
    client, db_session, home
):
    """Search feeds the message-recipient picker off the same projection."""
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png",
                status=ImageStatusEnum.ARCHIVED)

    resp = client.get("/characters/search", params={"q": "Vela"},
                      headers=auth_headers(home["viewer_token"]))
    assert resp.status_code == 200, resp.text
    hits = [e for e in resp.json() if e["id"] == home["character_id"]]
    assert hits, resp.text
    assert hits[0]["avatar_url"] is None


# ══════════════════════════════════════════════════════════════════════════════
# C. The ACCOUNT avatar, and the built-in sigil that is not media
# ══════════════════════════════════════════════════════════════════════════════

def test_archived_user_image_account_avatar_is_withdrawn(client, db_session, home):
    """(C) ``resolve_account_avatar_url`` inherits the lifecycle rule.

    An account avatar backed by a real ``UserImage`` falls through to the media
    resolver, so archiving the row withdraws it from the shared surfaces that
    carry an author's avatar — the comment list most of all, which takes no
    token at all.
    """
    url = "/static/generated/account-face.png"
    _user_image(db_session, user_id=home["owner_id"],
                file_path="static/generated/account-face.png", status="active")
    assert resolve_account_avatar_url(db_session, url) == url

    row = db_session.query(UserImage).filter(
        UserImage.file_path == "static/generated/account-face.png"
    ).first()
    row.status = "archived"
    db_session.commit()

    assert resolve_account_avatar_url(db_session, url) is None


def test_a_builtin_sigil_is_never_touched_by_the_lifecycle_rule(
    client, db_session, home
):
    """(C, K) A sigil has no bytes, no row and no lifecycle.

    It is checked by exact membership BEFORE the media resolver, so a rule
    about archived rows cannot reach it. If it fell through, every Wanderer
    avatar in the product would disappear.
    """
    sigil = sorted(ACCOUNT_SIGIL_URLS)[0]
    assert resolve_account_avatar_url(db_session, sigil) == sigil


def test_an_archived_account_avatar_is_withdrawn_from_anonymous_comments(
    client, db_session, home
):
    """(C) The end-to-end surface: a comment list served with no token."""
    owner_id = home["owner_id"]
    realm = Realm(owner_id=owner_id, name="Withdrawal Square",
                  slug=f"wd-square-{uuid4().hex[:8]}", is_public=True)
    db_session.add(realm)
    db_session.commit()
    db_session.refresh(realm)
    db_session.add(RealmMembership(realm_id=realm.id, user_id=owner_id, role="owner"))

    post = Post(realm_id=realm.id, author_user_id=owner_id, content="A scene.",
                content_type=ContentTypeEnum.OOC, post_kind="general",
                created_at=datetime(2026, 1, 1, 12, 0, 0))
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)
    db_session.add(Comment(post_id=post.id, author_user_id=owner_id,
                           content="And a reply."))

    account_url = "/static/generated/wanderer-face.png"
    image = _user_image(db_session, user_id=owner_id,
                        file_path="static/generated/wanderer-face.png")
    owner = db_session.query(User).filter(User.id == owner_id).first()
    owner.avatar_url = account_url
    db_session.commit()

    anon = client.get(f"/comments/posts/{post.id}/comments")
    assert anon.status_code == 200, anon.text
    assert anon.json()[0]["author_avatar_url"] == account_url

    image.status = "archived"
    db_session.commit()

    anon = client.get(f"/comments/posts/{post.id}/comments")
    assert anon.status_code == 200, anon.text
    assert anon.json()[0]["author_avatar_url"] is None


# ══════════════════════════════════════════════════════════════════════════════
# E/F. The two surfaces that already honoured ARCHIVED — unchanged
# ══════════════════════════════════════════════════════════════════════════════

def test_the_public_gallery_still_excludes_an_archived_image(
    client, db_session, home
):
    """(E) Regression guard, not new behaviour.

    ``is_public_gallery_image`` has always required ACTIVE. The reversal must
    not have moved that check, loosened it, or made the gallery answer to the
    avatar composition instead of its own.
    """
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/gallery-piece.png")
    img.public_gallery_enabled = True
    db_session.commit()

    resp = client.get(f"/characters/{home['character_id']}/public-home/images")
    assert resp.status_code == 200, resp.text
    assert [e["id"] for e in resp.json()] == [img.id]

    img.status = ImageStatusEnum.ARCHIVED
    db_session.commit()

    resp = client.get(f"/characters/{home['character_id']}/public-home/images")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_a_post_attachment_still_excludes_an_archived_image(
    client, db_session, home
):
    """(F) The rule the avatar surface has now been brought into line with."""
    from app.services.character_home_media import resolve_public_post_image_url

    url = "/static/generated/attachment.png"
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/attachment.png")
    assert resolve_public_post_image_url(db_session, url) == url

    img.status = ImageStatusEnum.ARCHIVED
    db_session.commit()
    assert resolve_public_post_image_url(db_session, url) is None


# ══════════════════════════════════════════════════════════════════════════════
# G/H. Re-promotion: an old row is not a restore
# ══════════════════════════════════════════════════════════════════════════════

def test_promote_to_canon_refuses_an_archived_image(client, db_session, home):
    """(G) The gap: a deleted image becoming live canon because its row exists.

    Promotion rewrites ``kind``, which is what makes an image canon AND what
    ``AVATAR_ELIGIBLE_KINDS`` reads. Accepting an archived row would let a
    withdrawn asset drive future generation and become a character's face,
    minutes after being withdrawn from every shared surface — a restore in all
    but name, and beta ships no restore.
    """
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/promote-me.png",
                      kind=ImageKindEnum.SCENE_ONLY,
                      status=ImageStatusEnum.ARCHIVED)

    resp = client.post(
        f"/characters/{home['character_id']}/images/{img.id}/promote-to-canon",
        json={"target": "face_canon"},
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 422, resp.text
    assert "deleted" in resp.json()["detail"].lower()

    db_session.refresh(img)
    assert img.kind == ImageKindEnum.SCENE_ONLY
    assert img.status == ImageStatusEnum.ARCHIVED


def test_promote_to_canon_still_accepts_an_active_image(client, db_session, home):
    """(G) ACTIVE assets keep working exactly as before."""
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/promote-me-too.png",
                      kind=ImageKindEnum.SCENE_ONLY)

    resp = client.post(
        f"/characters/{home['character_id']}/images/{img.id}/promote-to-canon",
        json={"target": "face_canon"},
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["new_kind"] == ImageKindEnum.ANCHOR_FRONT.value


def test_body_slot_use_existing_refuses_an_archived_image(client, db_session, home):
    """(H) The second gap. A body slot url is read back as canon conditioning."""
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/slot-source.png",
                      status=ImageStatusEnum.ARCHIVED)

    resp = client.post(
        f"/characters/{home['character_id']}/identity/body-slots/body_front/use-existing",
        json={"image_id": img.id},
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 422, resp.text
    assert "deleted" in resp.json()["detail"].lower()

    # And the slot is untouched — a refused selection must not half-apply.
    slots = client.get(
        f"/characters/{home['character_id']}/identity/body-slots",
        headers=auth_headers(home["owner_token"]),
    )
    assert slots.status_code == 200, slots.text
    front = next(s for s in slots.json()["slots"] if s["key"] == "body_front")
    assert front["url"] is None


def test_body_slot_use_existing_still_accepts_an_active_image(
    client, db_session, home
):
    """(H) ACTIVE assets keep working exactly as before."""
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/slot-source-ok.png")

    resp = client.post(
        f"/characters/{home['character_id']}/identity/body-slots/body_front/use-existing",
        json={"image_id": img.id},
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 200, resp.text
    front = next(s for s in resp.json()["slots"] if s["key"] == "body_front")
    assert front["status"] == "locked"
    assert front["url"] is not None


def test_use_existing_anchor_refuses_an_archived_image(client, db_session, home):
    """(H, third member) The audit's own follow-up finding, closed.

    ``POST /characters/{id}/body-markings/{id}/use-existing-anchor`` is the
    THIRD path of one defect class — the first static sweep found it after the
    other two were closed, and it was reported rather than fixed silently.

    Same shape, same consequence: the route writes the selected row's
    ``file_path`` into ``anchor_image_url``, which is live canon read back as
    generation conditioning. An old row is not a restore.
    """
    marking_id = _add_marking(client, home)
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/anchor-source.png",
                      status=ImageStatusEnum.ARCHIVED)

    resp = client.post(
        f"/characters/{home['character_id']}/body-markings/{marking_id}"
        f"/use-existing-anchor",
        json={"image_id": img.id},
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 422, resp.text
    assert "deleted" in resp.json()["detail"].lower()

    # A refused selection must not half-apply: the marking keeps no anchor.
    markings = client.get(f"/characters/{home['character_id']}/body-markings",
                          headers=auth_headers(home["owner_token"]))
    assert markings.status_code == 200, markings.text
    marking = next(m for m in markings.json()["markings"] if m["id"] == marking_id)
    assert marking.get("anchor_image_url") is None
    assert marking.get("anchor_status") != "locked"


def test_use_existing_anchor_still_accepts_an_active_image(client, db_session, home):
    """(H, third member) ACTIVE assets keep working exactly as before."""
    marking_id = _add_marking(client, home)
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/anchor-source-ok.png")

    resp = client.post(
        f"/characters/{home['character_id']}/body-markings/{marking_id}"
        f"/use-existing-anchor",
        json={"image_id": img.id},
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 200, resp.text
    marking = resp.json()["marking"]
    assert marking["anchor_status"] == "locked"
    assert marking["anchor_image_url"] == "static/generated/anchor-source-ok.png"


# ══════════════════════════════════════════════════════════════════════════════
# The PUBLIC USER PROFILE — the last shared surface emitting a raw account avatar
# ══════════════════════════════════════════════════════════════════════════════

def test_public_profile_shows_a_builtin_sigil(client, db_session, home):
    """(A) A sigil is not media and must survive the governed rule.

    It is checked by exact membership BEFORE the media resolver. If it fell
    through, every Wanderer avatar on every profile page would vanish — which
    is the failure mode that makes "just run it through the media resolver"
    the wrong fix and ``resolve_account_avatar_url`` the right one.
    """
    sigil = sorted(ACCOUNT_SIGIL_URLS)[0]
    _set_account_avatar(db_session, home["owner_id"], sigil)

    assert _profile(client, home)["avatar_url"] == sigil


def test_public_profile_shows_an_active_governed_avatar(client, db_session, home):
    """(B) The reversal must stop at avatars that deserve to be shown."""
    url = "/static/generated/profile-face.png"
    _user_image(db_session, user_id=home["owner_id"],
                file_path="static/generated/profile-face.png")
    _set_account_avatar(db_session, home["owner_id"], url)

    assert _profile(client, home)["avatar_url"] == url


def test_public_profile_suppresses_an_archived_governed_avatar(
    client, db_session, home
):
    """(C) The gap this closes, stated as a before/after on one response.

    Before the fix this route returned the column raw, so it published an
    avatar that the comment list — reading the SAME column through the SAME
    resolver — already withheld. One account, one avatar, two answers.
    """
    url = "/static/generated/profile-face.png"
    image = _user_image(db_session, user_id=home["owner_id"],
                        file_path="static/generated/profile-face.png")
    _set_account_avatar(db_session, home["owner_id"], url)
    assert _profile(client, home)["avatar_url"] == url

    image.status = "archived"
    db_session.commit()

    assert _profile(client, home)["avatar_url"] is None


def test_public_profile_fails_closed_on_a_rowless_pointer(client, db_session, home):
    """(D) The Beta Boundary 2 rule is inherited, not relaxed.

    An arbitrary url and a storage path with no row behind it are both
    provenance that cannot be established. Neither is newly permitted by this
    route learning the lifecycle rule.
    """
    for pointer in (
        "/static/generated/no-row-at-all.png",
        "https://example.invalid/someone-elses.png",
        "data:image/svg+xml;utf8,<svg/>",
    ):
        _set_account_avatar(db_session, home["owner_id"], pointer)
        assert _profile(client, home)["avatar_url"] is None, pointer


def test_public_profile_suppression_is_the_same_answer_the_comment_list_gives(
    client, db_session, home
):
    """One rule, not two that agree today.

    Pinned against ``resolve_account_avatar_url`` itself rather than against a
    hardcoded ``None``, so if the shared resolver ever starts publishing this
    the failure lands on the resolver and not quietly on this one surface.
    """
    url = "/static/generated/profile-face.png"
    image = _user_image(db_session, user_id=home["owner_id"],
                        file_path="static/generated/profile-face.png")
    _set_account_avatar(db_session, home["owner_id"], url)
    image.status = "archived"
    db_session.commit()

    assert _profile(client, home)["avatar_url"] == \
        resolve_account_avatar_url(db_session, url)


def test_public_profile_applies_the_rule_to_the_owner_too(client, db_session, home):
    """No viewer is exempt, including the account itself.

    Exempting the owner would leave exactly one response still carrying the raw
    pointer — and it is the response an attacker can always obtain, by asking
    for their own profile. Same reasoning the comment list already applies.

    The account's PRIVATE representation is a different schema on a different
    route and is deliberately untouched, which the next test asserts.
    """
    url = "/static/generated/profile-face.png"
    image = _user_image(db_session, user_id=home["owner_id"],
                        file_path="static/generated/profile-face.png")
    _set_account_avatar(db_session, home["owner_id"], url)
    image.status = "archived"
    db_session.commit()

    own = client.get("/users/wdown", headers=auth_headers(home["owner_token"]))
    assert own.status_code == 200, own.text
    assert own.json()["avatar_url"] is None


def test_the_private_account_representation_is_untouched(client, db_session, home):
    """``GET /users/me`` is account MANAGEMENT, not a shared surface.

    It returns a different schema on a different route to the account itself.
    The owner has to be able to see and change the pointer they actually have
    stored, so the public projection must not reach it.
    """
    url = "/static/generated/profile-face.png"
    image = _user_image(db_session, user_id=home["owner_id"],
                        file_path="static/generated/profile-face.png")
    _set_account_avatar(db_session, home["owner_id"], url)
    image.status = "archived"
    db_session.commit()

    me = client.get("/users/me", headers=auth_headers(home["owner_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["avatar_url"] == url


def test_reading_the_public_profile_does_not_mutate_the_stored_avatar(
    client, db_session, home
):
    """(E) Suppression is presentation. The verdict never reaches the ORM row.

    The resolver returns ``None`` for a withheld avatar. Assigning that back to
    ``UserModel.avatar_url`` would mark ``users`` dirty, and a later flush would
    persist a suppression as a deletion of the owner's avatar — data destroyed
    by somebody loading a profile page.
    """
    url = "/static/generated/profile-face.png"
    image = _user_image(db_session, user_id=home["owner_id"],
                        file_path="static/generated/profile-face.png")
    _set_account_avatar(db_session, home["owner_id"], url)
    image.status = "archived"
    db_session.commit()

    for _ in range(3):
        assert _profile(client, home)["avatar_url"] is None

    db_session.expire_all()
    assert db_session.query(User).get(home["owner_id"]).avatar_url == url
    assert db_session.query(UserImage).get(image.id).status == "archived"


# ══════════════════════════════════════════════════════════════════════════════
# The PUBLIC PROFILE COVER — media, never a sigil, so a different resolver
# ══════════════════════════════════════════════════════════════════════════════

def test_public_profile_shows_an_active_governed_cover(client, db_session, home):
    """(A) An ACTIVE ``UserImage``-backed account cover resolves normally."""
    url = "/static/generated/profile-cover.png"
    _user_image(db_session, user_id=home["owner_id"],
                file_path="static/generated/profile-cover.png")
    _set_account_cover(db_session, home["owner_id"], url)

    assert _profile(client, home)["cover_url"] == url


def test_public_profile_suppresses_a_rowless_cover(client, db_session, home):
    """(B) The live half of this gap before the fix.

    No ``UserImage`` archive path exists, so an ARCHIVED cover is unreachable
    today — but a pointer with NO ROW was reachable and was being emitted raw
    to any signed-in account. Provenance that cannot be established is not
    provenance, on this field exactly as on every other.
    """
    for pointer in (
        "/static/generated/cover-with-no-row.png",
        "https://example.invalid/someone-elses-banner.png",
    ):
        _set_account_cover(db_session, home["owner_id"], pointer)
        assert _profile(client, home)["cover_url"] is None, pointer


def test_public_profile_suppresses_a_non_public_provenance_cover(
    client, db_session, home
):
    """(C) Studio provenance is refused on the cover, as everywhere else.

    ``resolve_public_media_url`` is duck-typed, so a ``UserImage`` carrying an
    Adult Studio or Editor Studio marker is judged by the same shared predicate
    that judges a character's cover.
    """
    url = "/static/generated/studio-cover.png"
    image = _user_image(db_session, user_id=home["owner_id"],
                        file_path="static/generated/studio-cover.png")
    _set_account_cover(db_session, home["owner_id"], url)
    assert _profile(client, home)["cover_url"] == url

    image.provider = "replicate_nsfw"
    db_session.commit()
    assert _profile(client, home)["cover_url"] is None

    image.provider = "openai"
    image.metadata_json = {"editor_generated": True}
    db_session.commit()
    assert _profile(client, home)["cover_url"] is None


def test_a_lifecycle_ineligible_cover_is_suppressed_at_the_resolver(
    client, db_session, home
):
    """(D) Lifecycle comes free, and is proven now rather than assumed later.

    No route archives a ``UserImage``, so this state cannot be produced through
    the product and the test writes the column directly. The point is that
    ``resolve_public_media_url`` applies ``is_public_media`` — so the day a
    ``UserImage`` archive path exists, the read path already withholds the
    cover and will not need revisiting.

    Asserted on the ROUTE as well as the resolver, so the route is pinned to
    the lifecycle-aware resolver rather than to a provenance-only one that
    would pass every other test in this section.
    """
    url = "/static/generated/profile-cover.png"
    image = _user_image(db_session, user_id=home["owner_id"],
                        file_path="static/generated/profile-cover.png")
    _set_account_cover(db_session, home["owner_id"], url)

    image.status = "archived"
    db_session.commit()

    assert resolve_public_media_url(db_session, url) is None
    assert _profile(client, home)["cover_url"] is None


def test_the_cover_does_not_go_through_the_sigil_branch(client, db_session, home):
    """The two fields use two resolvers, and the difference is load-bearing.

    The eight built-in sigils are AVATARS. There is no such thing as a built-in
    cover, and ``User.cover_url`` is not writable through ``PATCH /users/me``
    at all. If the cover were routed through ``resolve_account_avatar_url``,
    this field would acquire a way to emit a ``data:`` payload — markup the
    browser executes as a document — that the media rule refuses.
    """
    sigil = sorted(ACCOUNT_SIGIL_URLS)[0]
    _set_account_cover(db_session, home["owner_id"], sigil)

    assert _profile(client, home)["cover_url"] is None
    # ...while the same value on the AVATAR field is still allowed.
    _set_account_avatar(db_session, home["owner_id"], sigil)
    assert _profile(client, home)["avatar_url"] == sigil


def test_reading_the_public_profile_does_not_mutate_the_stored_cover(
    client, db_session, home
):
    """(E) Presentation only, on the cover as on the avatar.

    Assigning a withheld verdict back to ``UserModel.cover_url`` would mark
    ``users`` dirty, and a later flush would persist a suppression as a
    deletion of the owner's banner.
    """
    url = "/static/generated/cover-no-row.png"
    _set_account_cover(db_session, home["owner_id"], url)

    for _ in range(3):
        assert _profile(client, home)["cover_url"] is None

    db_session.expire_all()
    assert db_session.query(User).get(home["owner_id"]).cover_url == url


def test_the_private_representation_keeps_both_stored_pointers(
    client, db_session, home
):
    """(F) ``GET /users/me`` is account MANAGEMENT and stays unchanged.

    The owner has to be able to see and change the pointers they actually have
    stored — on both fields — so the public projection must not reach them.
    """
    avatar = "/static/generated/no-row-avatar.png"
    cover = "/static/generated/no-row-cover.png"
    _set_account_avatar(db_session, home["owner_id"], avatar)
    _set_account_cover(db_session, home["owner_id"], cover)

    public = _profile(client, home)
    assert public["avatar_url"] is None and public["cover_url"] is None

    me = client.get("/users/me", headers=auth_headers(home["owner_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["avatar_url"] == avatar
    assert me.json()["cover_url"] == cover


def test_no_owner_bypass_on_the_public_profile_cover(client, db_session, home):
    """Both fields are resolved for every viewer, the account itself included.

    Exempting the owner would leave one response still carrying the raw
    pointers, and it is the response an attacker can always obtain.
    """
    _set_account_cover(db_session, home["owner_id"],
                       "/static/generated/no-row-cover.png")

    own = client.get("/users/wdown", headers=auth_headers(home["owner_token"]))
    assert own.status_code == 200, own.text
    assert own.json()["cover_url"] is None


# ══════════════════════════════════════════════════════════════════════════════
# The CHARACTER ROSTER — the same schema the directory governs
# ══════════════════════════════════════════════════════════════════════════════

def _roster(client, ctx, token) -> list:
    resp = client.get(f"/users/{ctx['owner_username']}/characters",
                      headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _entry(rows, character_id) -> dict:
    for row in rows:
        if row["id"] == character_id:
            return row
    raise AssertionError(f"character {character_id} absent from {rows}")


def test_roster_resolves_an_active_avatar_and_cover(client, db_session, home):
    """(A) The governed projection reached, on a roster visible to the caller.

    Seeding mode hands a non-owner ``[]``, so the reachable roster today is the
    owner's own — which is exactly where the ungoverned rows were being built.
    The rule applies to every response this route produces, not only the ones a
    configuration currently exposes to strangers.
    """
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png")
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-cover.png",
                kind=ImageKindEnum.COVER)

    row = _entry(_roster(client, home, home["owner_token"]), home["character_id"])
    assert row["avatar_url"] == AVATAR
    assert row["cover_url"] == COVER


def test_roster_suppresses_archived_and_unresolvable_pointers(
    client, db_session, home
):
    """(B) ARCHIVED and rowless both fail closed, exactly as on the directory.

    Pinned against the directory's own answer rather than a hardcoded ``None``,
    so the two surfaces are held together: if the directory ever starts
    publishing one of these, the failure lands there and not quietly here.
    """
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png",
                status=ImageStatusEnum.ARCHIVED)
    # The cover pointer is left with no row at all — the other failure mode.

    row = _entry(_roster(client, home, home["owner_token"]), home["character_id"])
    assert row["avatar_url"] is None
    assert row["cover_url"] is None

    listed = directory_entry(client, home, home["viewer_token"])
    assert row["avatar_url"] == listed["avatar_url"]
    assert row["cover_url"] == listed["cover_url"]


def test_roster_suppresses_a_studio_provenance_avatar(client, db_session, home):
    """(B) Provenance travels with the projection too, not only lifecycle."""
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png",
                metadata={"adult_studio": True})

    row = _entry(_roster(client, home, home["owner_token"]), home["character_id"])
    assert row["avatar_url"] is None


def test_roster_projection_does_not_mutate_stored_pointers(client, db_session, home):
    """(C) Suppression is presentation. The verdict never reaches the ORM row.

    Assigning it back would mark ``characters`` dirty, and a later flush would
    persist a suppression as a deletion of the founder's avatar and cover.
    """
    _char_image(db_session, character_id=home["character_id"],
                user_id=home["owner_id"], file_path="static/generated/withdrawn-avatar.png",
                status=ImageStatusEnum.ARCHIVED)

    for _ in range(3):
        row = _entry(_roster(client, home, home["owner_token"]), home["character_id"])
        assert row["avatar_url"] is None

    db_session.expire_all()
    character = db_session.query(Character).get(home["character_id"])
    assert character.avatar_url == AVATAR
    assert character.cover_url == COVER


def test_roster_visibility_and_ordering_are_unchanged(client, db_session, home):
    """(D) The projection adds a media rule to the rows, not a rule about access.

    Seeding mode is ON by default, so a non-owner still gets ``[]`` — the
    projection must not have turned an empty roster into a populated one, nor a
    populated one into an error, nor changed the schema or the newest-first
    ordering. A second character is seeded directly because the one-per-account
    entitlement refuses the HTTP create route, and the ordering assertion needs
    two rows to mean anything.
    """
    assert _roster(client, home, home["viewer_token"]) == []

    older = Character(
        owner_id=home["owner_id"], name="Wren", species="human",
        visibility="public", created_at=datetime(2020, 1, 1, 0, 0, 0),
    )
    db_session.add(older)
    db_session.commit()
    db_session.refresh(older)

    own = _roster(client, home, home["owner_token"])
    # Newest first, with the seeded 2020 row last — the order the route has
    # always returned, unchanged by projecting the rows.
    assert [r["id"] for r in own] == [home["character_id"], older.id]
    assert {"id", "name", "avatar_url", "cover_url"} <= set(own[0])

    # Still empty for a non-owner: no authorization behaviour changed.
    assert _roster(client, home, home["viewer_token"]) == []


# ══════════════════════════════════════════════════════════════════════════════
# I/J/K/L. Pointer clearing on the owner's archive
# ══════════════════════════════════════════════════════════════════════════════

def test_owner_delete_of_the_current_avatar_clears_the_pointer(
    client, db_session, home
):
    """(I) Archived AND unpointed, in one transaction.

    The resolver would suppress the url either way. The pointer still has to
    go: the owner's own editor reads the raw column, and being shown a portrait
    you deleted as your character's current avatar is the product failing to
    honour the delete, whatever the anonymous surface renders.
    """
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/withdrawn-avatar.png")
    character = db_session.query(Character).filter(
        Character.id == home["character_id"]
    ).first()
    assert character.avatar_url == AVATAR

    resp = client.delete(
        f"/characters/{home['character_id']}/images/{img.id}",
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(CharacterImage).get(img.id).status == ImageStatusEnum.ARCHIVED
    assert db_session.query(Character).get(home["character_id"]).avatar_url is None


def test_owner_delete_of_the_current_cover_clears_the_pointer(
    client, db_session, home
):
    """(J) The cover is the character's largest public surface. Same rule."""
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/withdrawn-cover.png",
                      kind=ImageKindEnum.COVER)

    resp = client.delete(
        f"/characters/{home['character_id']}/images/{img.id}",
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    character = db_session.query(Character).get(home["character_id"])
    assert character.cover_url is None
    # And ONLY the cover: the avatar names a different file.
    assert character.avatar_url == AVATAR


def test_owner_delete_of_the_account_avatar_crop_clears_the_account_pointer(
    client, db_session, home
):
    """(K) The account avatar crop is a CHARACTERLESS ``CharacterImage``.

    ``POST /users/me/avatar`` writes it with ``character_id`` NULL, so
    ``DELETE /users/me/character-images/{id}`` is the only entrance that can archive the
    asset behind ``User.avatar_url`` — and therefore the only place this
    pointer can be cleared.
    """
    url = "/static/generated/account-crop.png"
    img = _char_image(db_session, character_id=None, user_id=home["owner_id"],
                      file_path="static/generated/account-crop.png",
                      kind=ImageKindEnum.UPLOADED,
                      metadata={"avatar_crop": True, "is_temp": False})
    owner = db_session.query(User).filter(User.id == home["owner_id"]).first()
    owner.avatar_url = url
    db_session.commit()

    resp = client.delete(
        f"/users/me/character-images/{img.id}",
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(CharacterImage).get(img.id).status == ImageStatusEnum.ARCHIVED
    assert db_session.query(User).get(home["owner_id"]).avatar_url is None


def test_a_builtin_sigil_account_avatar_survives_an_unrelated_archive(
    client, db_session, home
):
    """(K) The sigil is not media and must be unaffected by any withdrawal."""
    sigil = sorted(ACCOUNT_SIGIL_URLS)[0]
    owner = db_session.query(User).filter(User.id == home["owner_id"]).first()
    owner.avatar_url = sigil
    db_session.commit()

    img = _char_image(db_session, character_id=None, user_id=home["owner_id"],
                      file_path="static/generated/some-crop.png",
                      kind=ImageKindEnum.UPLOADED)
    resp = client.delete(f"/users/me/character-images/{img.id}",
                         headers=auth_headers(home["owner_token"]))
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(User).get(home["owner_id"]).avatar_url == sigil


def test_an_unrelated_pointer_is_not_cleared(client, db_session, home):
    """(L) The failure mode a string-shaped identity invites.

    There is no foreign key to follow, so "which pointers name this row?" is
    answered by the exact inverse of the resolver's own url→file_path
    inversion. A similar name, a shared basename or a different directory is
    NOT a match, and a withdrawal that cleared those would delete a founder's
    working avatar because another file resembled it.
    """
    other_token = get_auth_token(client, email="wd-other@test.com", username="wdother")
    other_cid = client.post(
        "/characters/", json={"name": "Rook", "visibility": "public"},
        headers=auth_headers(other_token),
    ).json()["id"]
    other = db_session.query(Character).filter(Character.id == other_cid).first()
    other.avatar_url = "/static/generated/rook-face.png"
    db_session.commit()

    # Same basename, different directory — the classic near-miss.
    victim = _char_image(db_session, character_id=home["character_id"],
                         user_id=home["owner_id"],
                         file_path="static/other/rook-face.png")

    resp = client.delete(
        f"/characters/{home['character_id']}/images/{victim.id}",
        headers=auth_headers(home["owner_token"]),
    )
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(Character).get(other_cid).avatar_url == \
        "/static/generated/rook-face.png"
    # The archiving owner's own unrelated pointers survive too.
    assert db_session.query(Character).get(home["character_id"]).avatar_url == AVATAR


def test_another_accounts_pointer_is_never_reached(client, db_session, home):
    """Withdrawal is scoped to the archiving account's own material.

    No route lets one account point a character at another account's image, so
    this state should not arise; if it did, archiving must not reach into
    somebody else's profile. The resolver suppresses the url regardless, which
    is the layer that actually protects the surface.
    """
    stranger_token = get_auth_token(client, email="wd-str@test.com", username="wdstr")
    stranger_cid = client.post(
        "/characters/", json={"name": "Ash", "visibility": "public"},
        headers=auth_headers(stranger_token),
    ).json()["id"]
    stranger_char = db_session.query(Character).filter(
        Character.id == stranger_cid
    ).first()
    stranger_char.avatar_url = "/static/generated/shared-file.png"
    db_session.commit()

    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/shared-file.png")
    resp = client.delete(f"/characters/{home['character_id']}/images/{img.id}",
                         headers=auth_headers(home["owner_token"]))
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert db_session.query(Character).get(stranger_cid).avatar_url == \
        "/static/generated/shared-file.png"
    assert resolve_public_media_url(db_session, "/static/generated/shared-file.png") is None


def test_pointer_clearing_matches_the_resolvers_own_inversion():
    """The two halves of the url↔file_path mapping, pinned against each other.

    ``candidate_file_paths`` decides which rows a pointer names;
    ``urls_naming_file_path`` decides which pointers a row names. They must
    agree exactly, in both directions, or a withdrawal either misses a pointer
    the resolver would have matched or clears one it would not.
    """
    file_paths = [
        "generated/a.png", "static/generated/a.png", "/static/generated/a.png",
        "/generated/a.png", "https://pub-abc.r2.dev/generated/a.png",
    ]
    urls = file_paths + ["other/a.png", "/static/other/a.png",
                         "https://pub-abc.r2.dev/generated/b.png"]

    for file_path in file_paths:
        for url in urls:
            assert (file_path in candidate_file_paths(url)) == \
                (url in urls_naming_file_path(file_path)), (file_path, url)


# ══════════════════════════════════════════════════════════════════════════════
# M. Reading is not writing
# ══════════════════════════════════════════════════════════════════════════════

def test_projection_does_not_mutate_lifecycle_or_pointers(client, db_session, home):
    """(M) Suppression is presentation. Nothing on a read path writes.

    The resolver returns ``None`` for an image it withholds. If that verdict
    were ever assigned back to the ORM row or the character's column, a later
    flush would persist a suppression as a deletion — and the owner's data
    would be destroyed by somebody loading a page.
    """
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/withdrawn-avatar.png",
                      status=ImageStatusEnum.ARCHIVED)

    for _ in range(2):
        assert public_home(client, home)["avatar_url"] is None
        detail(client, home, home["viewer_token"])
        directory_entry(client, home, home["viewer_token"])

    db_session.expire_all()
    assert db_session.query(Character).get(home["character_id"]).avatar_url == AVATAR
    row = db_session.query(CharacterImage).get(img.id)
    assert row.status == ImageStatusEnum.ARCHIVED
    assert row.file_path == "static/generated/withdrawn-avatar.png"


def test_an_active_read_does_not_archive_anything(client, db_session, home):
    """The mirror: publishing an image must not touch its lifecycle either."""
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/withdrawn-avatar.png")

    assert public_home(client, home)["avatar_url"] == AVATAR
    db_session.expire_all()
    assert db_session.query(CharacterImage).get(img.id).status == ImageStatusEnum.ACTIVE


# ══════════════════════════════════════════════════════════════════════════════
# The limitation, stated as an assertion rather than left in a comment
# ══════════════════════════════════════════════════════════════════════════════

def test_an_archived_asset_is_withdrawn_not_deleted(client, db_session, home):
    """WITHDRAWAL IS APPLICATION-LAYER. The bytes and the row both survive.

    This is the honest boundary of the increment, and it is asserted so nobody
    reads "withdrawn" as "deleted". The row keeps its file_path, its provenance
    and its owner; no object is removed from storage; no bucket setting
    changes. An anonymous party who already holds the direct public R2/static
    URL can still fetch the file after the owner archives it.

    Revoking that URL needs private-bucket or proxied/presigned serving, which
    this increment deliberately does not touch.
    """
    img = _char_image(db_session, character_id=home["character_id"],
                      user_id=home["owner_id"],
                      file_path="static/generated/withdrawn-avatar.png")
    resp = client.delete(f"/characters/{home['character_id']}/images/{img.id}",
                         headers=auth_headers(home["owner_token"]))
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    row = db_session.query(CharacterImage).get(img.id)
    assert row is not None                                   # the row survives
    assert row.status == ImageStatusEnum.ARCHIVED            # lifecycle only
    assert row.file_path == "static/generated/withdrawn-avatar.png"  # still addressable
    assert row.user_id == home["owner_id"]                   # provenance intact
    assert row.provider == "fal"

    # And there is no way back through the product: no restore endpoint exists,
    # and the selection paths refuse the row.
    assert client.post(
        f"/characters/{home['character_id']}/images/{img.id}/promote-to-canon",
        json={"target": "face_canon"}, headers=auth_headers(home["owner_token"]),
    ).status_code == 422
