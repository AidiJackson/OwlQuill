"""A post attachment answers to one rule on every surface but its author's own.

The anonymous Character Home has re-checked ``Post.image_url`` since Step 5. No
authenticated surface did. ``serialize_post_for_viewer`` returned the
denormalised string straight off the row, so an image the public timeline
withheld — Adult Studio output, an archived row, a kind that had since left the
post-attachable allowlist, a path resolving to nothing at all — was served in
full to the Commons feed, the realm listing, the single-post fetch, the creator
timeline and both mention lists. Being logged in was not supposed to be a reason
to see it, and yet it was the only thing separating the two answers.

This file pins the corrected shape:

* **G-3** — every shared surface suppresses exactly what the anonymous Home
  suppresses. The comparison is made against the Home in the same test rather
  than against a hardcoded ``None``, so the two cannot drift apart silently.
* **The author is not a shared surface.** Their own post hands their own
  attachment back, on all of those endpoints. Suppression is about showing
  someone else's image to someone else, never about taking a creator's material
  away from them.
* **The batch resolver** (:func:`resolve_public_post_image_urls`) is the same
  decision at page scale. Its one genuinely new failure mode is cross-talk —
  one url borrowing another's verdict because the fetch was unioned — so that
  is asserted directly, in both directions, rather than left to inference from
  the single-url tests.

Text is never touched. A post whose image is withheld still publishes its words,
here as on the anonymous timeline.
"""
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models.character import Character
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.post import ContentTypeEnum, Post
from app.models.post_mention import PostMention
from app.models.realm import Realm, RealmMembership
from app.models.user import User
from app.models.user_image import UserImage
from app.services.character_home_media import (
    resolve_public_post_image_url,
    resolve_public_post_image_urls,
)
from tests.conftest import auth_headers, engine, get_auth_token


# ── Fixtures and helpers ──────────────────────────────────────────────────────

def _create_character(client, token, name="Summer"):
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human", "visibility": "public"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _user_id(db_session, email) -> int:
    return db_session.query(User).filter(User.email == email).first().id


def _realm(db_session, owner_id, name, *, is_public=True):
    """A realm with a collision-proof slug — registration seeds The Commons."""
    realm = Realm(
        owner_id=owner_id,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        is_public=is_public,
    )
    db_session.add(realm)
    db_session.commit()
    db_session.refresh(realm)
    return realm


def _char_image(db_session, character_id, user_id, *, file_path,
                kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
                provider="fal", metadata=None):
    img = CharacterImage(
        character_id=character_id,
        user_id=user_id,
        kind=kind,
        status=status,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider,
        prompt_summary="fixture",
        metadata_json=metadata if metadata is not None else {"library": True},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


def _user_image(db_session, user_id, *, file_path, provider="fal",
                status="active", metadata=None):
    img = UserImage(
        user_id=user_id,
        kind="profile_cover",
        status=status,
        provider=provider,
        metadata_json=metadata if metadata is not None else {},
        file_path=file_path,
    )
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


@pytest.fixture()
def surfaces(client, db_session):
    """A published character, a post in a public realm, and a second reader.

    The viewer is a member of the realm so every authenticated surface admits
    them on its own merits — the question under test is what they are handed
    once admitted, never whether they get in.
    """
    owner_token = get_auth_token(client, email="pis-own@test.com", username="pisown")
    cid = _create_character(client, owner_token, "Summer")
    owner_id = _user_id(db_session, "pis-own@test.com")

    row = db_session.query(Character).filter(Character.id == cid).first()
    row.public_home_enabled = True
    db_session.commit()

    viewer_token = get_auth_token(client, email="pis-see@test.com", username="pissee")
    viewer_id = _user_id(db_session, "pis-see@test.com")

    realm = _realm(db_session, owner_id, "Open Square")
    db_session.add_all([
        RealmMembership(realm_id=realm.id, user_id=owner_id, role="owner"),
        RealmMembership(realm_id=realm.id, user_id=viewer_id),
    ])
    db_session.commit()

    return {
        "owner_token": owner_token,
        "owner_id": owner_id,
        "owner_username": "pisown",
        "viewer_token": viewer_token,
        "viewer_id": viewer_id,
        "character_id": cid,
        "realm": realm,
    }


def _post(db_session, ctx, image_url, content="Look at this.", *, mentions=True):
    """One post by the fixture character, mentioned so both mention lists see it."""
    post = Post(
        realm_id=ctx["realm"].id,
        author_user_id=ctx["owner_id"],
        character_id=ctx["character_id"],
        content=content,
        content_type=ContentTypeEnum.IC,
        post_kind="general",
        image_url=image_url,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)

    if mentions:
        db_session.add_all([
            PostMention(post_id=post.id, mention_text="@Summer",
                        mentioned_character_id=ctx["character_id"]),
            PostMention(post_id=post.id, mention_text="@pisown",
                        mentioned_user_id=ctx["owner_id"]),
        ])
        db_session.commit()
    return post


def _pick(entries, post_id, key="id"):
    """The entry for *post_id* out of a flat ``Post`` list."""
    for entry in entries:
        if entry[key] == post_id:
            return entry
    raise AssertionError(f"post {post_id} absent from {entries}")


def _pick_payload(entries, post_id):
    """The entry for *post_id* out of a wrapped ``{type, payload}`` list."""
    for entry in entries:
        if entry.get("payload", {}).get("id") == post_id:
            return entry["payload"]
    raise AssertionError(f"post {post_id} absent from {entries}")


def shared_surface_images(client, ctx, post_id, token):
    """``image_url`` for one post from every authenticated surface serving it.

    Named per route so a failure says which endpoint regressed rather than only
    that one of them did. Every route here funnels through
    ``serialize_post_for_viewer``; that is precisely why they must agree.
    """
    h = auth_headers(token)
    u = ctx["owner_username"]
    cid = ctx["character_id"]
    rid = ctx["realm"].id

    def ok(resp):
        assert resp.status_code == 200, resp.text
        return resp.json()

    return {
        "feed": _pick(ok(client.get("/posts/feed", headers=h)), post_id)["image_url"],
        "realm_posts": _pick(
            ok(client.get(f"/posts/realms/{rid}/posts", headers=h)), post_id
        )["image_url"],
        "single_post": ok(client.get(f"/posts/{post_id}", headers=h))["image_url"],
        "user_timeline": _pick_payload(
            ok(client.get(f"/users/{u}/timeline", headers=h)), post_id
        )["image_url"],
        "user_mentions": _pick(
            ok(client.get(f"/users/{u}/mentions", headers=h)), post_id
        )["image_url"],
        "character_posts": _pick_payload(
            ok(client.get(f"/characters/{cid}/posts", headers=h)), post_id
        )["image_url"],
        "character_mentions": _pick_payload(
            ok(client.get(f"/characters/{cid}/mentions", headers=h)), post_id
        )["image_url"],
    }


def anonymous_home_image(client, ctx, post_id):
    """``image_url`` for one post as the anonymous Character Home publishes it."""
    resp = client.get(f"/characters/{ctx['character_id']}/public-home/posts")
    assert resp.status_code == 200, resp.text
    return _pick(resp.json(), post_id)["image_url"]


def shared_surface_contents(client, ctx, post_id, token):
    """The same seven surfaces, reporting the post's TEXT instead of its image."""
    h = auth_headers(token)
    u, cid, rid = ctx["owner_username"], ctx["character_id"], ctx["realm"].id
    return {
        "feed": _pick(client.get("/posts/feed", headers=h).json(), post_id)["content"],
        "realm_posts": _pick(
            client.get(f"/posts/realms/{rid}/posts", headers=h).json(), post_id
        )["content"],
        "single_post": client.get(f"/posts/{post_id}", headers=h).json()["content"],
        "user_timeline": _pick_payload(
            client.get(f"/users/{u}/timeline", headers=h).json(), post_id
        )["content"],
        "user_mentions": _pick(
            client.get(f"/users/{u}/mentions", headers=h).json(), post_id
        )["content"],
        "character_posts": _pick_payload(
            client.get(f"/characters/{cid}/posts", headers=h).json(), post_id
        )["content"],
        "character_mentions": _pick_payload(
            client.get(f"/characters/{cid}/mentions", headers=h).json(), post_id
        )["content"],
    }


@contextmanager
def image_lookups():
    """Record every statement that reads an image table, on the test engine.

    Scoped to ``character_images`` / ``user_images`` on purpose. Counting all
    SQL would measure auth, membership and eager-loading too, and the claim
    under test is narrower than that: resolution costs a fixed number of image
    lookups per PAGE, not per post.
    """
    seen = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if "character_images" in statement or "user_images" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


#: The provenance exclusions, one per layer the predicate checks.
UNSAFE_ROWS = [
    ("fal", {"adult_studio": True}),
    ("gpt-image", {"editor_generated": True}),
    ("replicate_nsfw", {}),
    ("self_hosted", {}),
    ("fal", {"provider": "replicate_nsfw"}),
]


# ── A. G-3: a shared surface is a shared surface, logged in or not ────────────

@pytest.mark.parametrize("provider,metadata", UNSAFE_ROWS)
def test_unsafe_image_is_suppressed_on_every_shared_surface(
    client, db_session, surfaces, provider, metadata
):
    """The leak this increment closes, stated as an equality with the Home.

    Asserted against what the anonymous timeline actually returns rather than
    against ``None``, so the two answers are pinned TOGETHER: if the Home ever
    starts publishing this row, this test fails on the Home rather than
    quietly blessing a wider authenticated answer.
    """
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/studio.png",
                provider=provider, metadata=metadata)
    post = _post(db_session, surfaces, "/static/generated/studio.png")

    home = anonymous_home_image(client, surfaces, post.id)
    assert home is None

    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert seen == {k: home for k in seen}, seen


def test_archived_image_is_suppressed_on_every_shared_surface(
    client, db_session, surfaces
):
    """Archiving IS the owner's delete, and ``image_url`` keeps pointing at it.

    Without the read-time check, deleting an image would leave it published on
    every post that ever carried it — to logged-in readers, at least, which was
    the whole population that mattered before the Home existed.
    """
    img = _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                      file_path="static/generated/withdrawn.png")
    post = _post(db_session, surfaces, "/static/generated/withdrawn.png")

    before = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert before == {k: "/static/generated/withdrawn.png" for k in before}, before

    img.status = ImageStatusEnum.ARCHIVED
    db_session.commit()

    home = anonymous_home_image(client, surfaces, post.id)
    after = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert home is None
    assert after == {k: home for k in after}, after


def test_kind_leaving_the_attachable_allowlist_suppresses_everywhere(
    client, db_session, surfaces
):
    """``kind`` is mutable — the identity-pack accept path rewrites it.

    An image that was attachable when the post was written can become private
    production material afterwards, and the attachment-time check cannot know
    that. Re-asserting the allowlist at read time is the only place it can be
    caught, and it has to be caught on all surfaces at once.
    """
    img = _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                      file_path="static/generated/promoted.png")
    post = _post(db_session, surfaces, "/static/generated/promoted.png")

    img.kind = ImageKindEnum.IDENTITY_FACE_REF
    db_session.commit()

    home = anonymous_home_image(client, surfaces, post.id)
    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert home is None
    assert seen == {k: home for k in seen}, seen


def test_unresolvable_image_fails_closed_on_every_shared_surface(
    client, db_session, surfaces
):
    """No row behind the url — so no provenance, so no publication.

    Nothing derives a post attachment: ``POST /realms/{id}/posts`` refuses any
    ``image_url`` it cannot match to an image row. A post carrying one anyway
    is a post whose attachment cannot be accounted for, and a reader who is not
    its author does not get it.
    """
    post = _post(db_session, surfaces, "/static/generated/nothing-behind-it.png")

    home = anonymous_home_image(client, surfaces, post.id)
    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert home is None
    assert seen == {k: home for k in seen}, seen


def test_ambiguous_resolution_fails_closed_on_every_shared_surface(
    client, db_session, surfaces
):
    """One url, two rows, one of them unsafe — the unsafe one decides.

    A file promoted or copied between records really does produce this. The
    batch path has to reach the same verdict as the single-url path, which it
    only does if it collects ALL matches for a url before deciding.
    """
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/shared-file.png")
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/shared-file.png",
                provider="replicate_nsfw")
    post = _post(db_session, surfaces, "/static/generated/shared-file.png")

    home = anonymous_home_image(client, surfaces, post.id)
    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert home is None
    assert seen == {k: home for k in seen}, seen


def test_suppression_never_removes_the_post_or_its_text(client, db_session, surfaces):
    """Only the image is dropped. The writing is the point of the post."""
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/studio.png", metadata={"adult_studio": True})
    post = _post(db_session, surfaces, "/static/generated/studio.png",
                 content="The words survive.")

    texts = shared_surface_contents(client, surfaces, post.id, surfaces["viewer_token"])
    assert texts == {k: "The words survive." for k in texts}, texts


# ── B. Safe images still render, and nothing else about the post moves ────────

def test_safe_character_image_renders_on_every_shared_surface(
    client, db_session, surfaces
):
    """The cost of fail-closed has to stop at the images that deserve it."""
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/post-safe.png")
    post = _post(db_session, surfaces, "/static/generated/post-safe.png")

    home = anonymous_home_image(client, surfaces, post.id)
    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert home == "/static/generated/post-safe.png"
    assert seen == {k: home for k in seen}, seen


def test_absolute_r2_url_renders_on_every_shared_surface(client, db_session, surfaces):
    """DEV and production store attachments as absolute R2 urls, matched verbatim.

    The relative-path spellings are the legacy shape; if resolution only worked
    for those, every current attachment would vanish from every surface at once.
    """
    url = "https://pub-abc.r2.dev/generated/deadbeef.png"
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"], file_path=url)
    post = _post(db_session, surfaces, url)

    home = anonymous_home_image(client, surfaces, post.id)
    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert home == url
    assert seen == {k: home for k in seen}, seen


def test_safe_user_image_attachment_renders(client, db_session, surfaces):
    """Account images are checked for provenance too, and pass on their merits.

    The kind allowlist is deliberately not applied to ``UserImage`` — the
    attachment path never imposed one there — so this must survive.
    """
    _user_image(db_session, surfaces["owner_id"], file_path="static/generated/from-device.png")
    post = _post(db_session, surfaces, "/static/generated/from-device.png")

    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert seen == {k: "/static/generated/from-device.png" for k in seen}, seen


def test_unsafe_user_image_attachment_is_suppressed(client, db_session, surfaces):
    _user_image(db_session, surfaces["owner_id"], file_path="static/generated/from-device.png",
                provider="self_hosted")
    post = _post(db_session, surfaces, "/static/generated/from-device.png")

    home = anonymous_home_image(client, surfaces, post.id)
    seen = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert home is None
    assert seen == {k: home for k in seen}, seen


def test_a_post_with_no_image_is_unaffected(client, db_session, surfaces):
    """A falsy url is not a decision. It must not become one, or acquire a query."""
    post = _post(db_session, surfaces, None, content="Words only.")

    with image_lookups() as seen:
        images = shared_surface_images(client, surfaces, post.id, surfaces["viewer_token"])
    assert images == {k: None for k in images}, images
    assert seen == []


def test_character_first_attribution_is_untouched_by_the_media_change(
    client, db_session, surfaces
):
    """The serializer's other policy still holds after gaining a second one.

    ``serialize_post_for_viewer`` grew a media rule inside the function that
    already stripped account identity. A regression in either would look local
    to whichever one was being read at the time.
    """
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/post-safe.png")
    post = _post(db_session, surfaces, "/static/generated/post-safe.png")

    h = auth_headers(surfaces["viewer_token"])
    seen_by_other = client.get(f"/posts/{post.id}", headers=h).json()
    assert seen_by_other["author_username"] is None
    assert seen_by_other["author_user_id"] is None
    assert seen_by_other["character_name"] == "Summer"

    own = client.get(
        f"/posts/{post.id}", headers=auth_headers(surfaces["owner_token"])
    ).json()
    assert own["author_username"] == "pisown"
    assert own["author_user_id"] == surfaces["owner_id"]


# ── C. The author is not a shared surface ─────────────────────────────────────

@pytest.mark.parametrize("provider,metadata", UNSAFE_ROWS)
def test_the_author_still_receives_their_own_attachment(
    client, db_session, surfaces, provider, metadata
):
    """Owner-private reading is unchanged, on every one of the same endpoints.

    This is the creator's own material shown back to them. Publication rules
    govern what OTHER people are handed; withholding a founder's own image
    from their own post would be a data loss dressed up as a safety measure,
    and the rows themselves are never touched either way.
    """
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/studio.png",
                provider=provider, metadata=metadata)
    post = _post(db_session, surfaces, "/static/generated/studio.png")

    assert anonymous_home_image(client, surfaces, post.id) is None

    mine = shared_surface_images(client, surfaces, post.id, surfaces["owner_token"])
    assert mine == {k: "/static/generated/studio.png" for k in mine}, mine


def test_the_author_keeps_an_unresolvable_attachment_too(client, db_session, surfaces):
    """Fail-closed is a publication rule, not a possession rule."""
    post = _post(db_session, surfaces, "/static/generated/nothing-behind-it.png")

    mine = shared_surface_images(client, surfaces, post.id, surfaces["owner_token"])
    assert mine == {k: "/static/generated/nothing-behind-it.png" for k in mine}, mine


def test_suppression_does_not_touch_the_stored_post_row(client, db_session, surfaces):
    """Presentation only. The denormalised column is exactly as it was written,
    so an image that becomes eligible again reappears with no data recovery.
    """
    img = _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                      file_path="static/generated/withdrawn.png")
    post = _post(db_session, surfaces, "/static/generated/withdrawn.png")
    img.status = ImageStatusEnum.ARCHIVED
    db_session.commit()

    h = auth_headers(surfaces["viewer_token"])
    assert client.get(f"/posts/{post.id}", headers=h).json()["image_url"] is None

    db_session.expire_all()
    assert db_session.query(Post).filter(Post.id == post.id).first().image_url == \
        "/static/generated/withdrawn.png"

    img.status = ImageStatusEnum.ACTIVE
    db_session.commit()
    assert client.get(f"/posts/{post.id}", headers=h).json()["image_url"] == \
        "/static/generated/withdrawn.png"


# ── D. The batch resolver: same verdicts, one page of queries ─────────────────

def test_batch_agrees_with_the_single_url_form(client, db_session, surfaces):
    """Four shapes at once, each checked against the function it replaces.

    The batch form exists for cost, not for policy. Anywhere the two disagree,
    the batch form is wrong by definition.
    """
    cid, uid = surfaces["character_id"], surfaces["owner_id"]
    _char_image(db_session, cid, uid, file_path="static/generated/b-safe.png")
    _char_image(db_session, cid, uid, file_path="static/generated/b-studio.png",
                metadata={"adult_studio": True})
    _char_image(db_session, cid, uid, file_path="static/generated/b-archived.png",
                status=ImageStatusEnum.ARCHIVED)

    urls = [
        "/static/generated/b-safe.png",
        "/static/generated/b-studio.png",
        "/static/generated/b-archived.png",
        "/static/generated/b-missing.png",
    ]
    batched = resolve_public_post_image_urls(db_session, urls)
    assert batched == {u: resolve_public_post_image_url(db_session, u) for u in urls}
    assert batched == {
        "/static/generated/b-safe.png": "/static/generated/b-safe.png",
        "/static/generated/b-studio.png": None,
        "/static/generated/b-archived.png": None,
        "/static/generated/b-missing.png": None,
    }


def test_one_url_cannot_borrow_another_urls_safe_verdict(client, db_session, surfaces):
    """The failure mode a batch rewrite of a per-item predicate invites.

    Candidate spellings are unioned to fetch in one round trip. If the verdict
    were then computed over the whole fetched set — or over "did we find any
    rows at all" — the safe image would launder the unsafe one. Each url is
    matched only against rows in ITS OWN candidate set, and this is the
    assertion that says so.
    """
    cid, uid = surfaces["character_id"], surfaces["owner_id"]
    _char_image(db_session, cid, uid, file_path="static/generated/clean.png")
    _char_image(db_session, cid, uid, file_path="static/generated/studio.png",
                provider="replicate_nsfw")

    clean, studio = "/static/generated/clean.png", "/static/generated/studio.png"
    assert resolve_public_post_image_urls(db_session, [clean, studio]) == \
        {clean: clean, studio: None}
    # Order must not matter either — a fold that carried state between urls
    # would pass one of these two and fail the other.
    assert resolve_public_post_image_urls(db_session, [studio, clean]) == \
        {clean: clean, studio: None}


def test_an_unresolvable_url_cannot_borrow_a_resolvable_ones_rows(
    client, db_session, surfaces
):
    """The mirror image: finding rows for SOMETHING is not finding rows for THIS.

    An implementation that asked "were all fetched rows safe?" would publish
    the url with nothing behind it, because the only rows fetched belong to the
    other one.
    """
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/clean.png")

    clean, missing = "/static/generated/clean.png", "/static/generated/absent.png"
    assert resolve_public_post_image_urls(db_session, [clean, missing]) == \
        {clean: clean, missing: None}


def test_batch_skips_falsy_urls_entirely(db_session):
    """A post with no image has no decision to record, so it gets no key."""
    assert resolve_public_post_image_urls(db_session, []) == {}
    assert resolve_public_post_image_urls(db_session, [None, "", None]) == {}


def test_batch_handles_a_url_repeated_across_posts(client, db_session, surfaces):
    """Two posts carrying the same image resolve once, to one answer."""
    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/reused.png")
    url = "/static/generated/reused.png"
    with image_lookups() as seen:
        assert resolve_public_post_image_urls(db_session, [url, url, url]) == {url: url}
    assert len(seen) == 2


def test_batch_resolution_costs_two_image_lookups_per_page_not_per_post(
    client, db_session, surfaces
):
    """The reason the batch form exists, measured rather than asserted in prose.

    One image query per table, whatever the page size. The single-url form
    issues two PER POST, so twenty posts cost forty round trips — which is what
    a feed page would have paid the moment resolution moved onto it.
    """
    cid, uid = surfaces["character_id"], surfaces["owner_id"]
    for i in range(8):
        _char_image(db_session, cid, uid, file_path=f"static/generated/feed-{i}.png")
        _post(db_session, surfaces, f"/static/generated/feed-{i}.png",
              content=f"Post {i}.", mentions=False)

    h = auth_headers(surfaces["viewer_token"])
    with image_lookups() as seen:
        body = client.get("/posts/feed", headers=h).json()

    assert len([p for p in body if p["image_url"]]) == 8
    assert len(seen) == 2, seen


def test_the_wrapped_routes_also_resolve_once_for_the_whole_page(
    client, db_session, surfaces
):
    """The four routes that serialise inside their own loop pay page cost too.

    They cannot call ``serialize_posts_for_viewer`` — each row is zipped with a
    realm name — so they take the mapping from ``post_image_resolution``
    instead. That is the part a later edit is most likely to drop back to a
    per-post call without anyone noticing, because it would still be correct.
    """
    cid, uid = surfaces["character_id"], surfaces["owner_id"]
    for i in range(8):
        _char_image(db_session, cid, uid, file_path=f"static/generated/wrapped-{i}.png")
        _post(db_session, surfaces, f"/static/generated/wrapped-{i}.png",
              content=f"Post {i}.", mentions=False)

    h = auth_headers(surfaces["viewer_token"])
    for route in (
        f"/characters/{cid}/posts",
        f"/users/{surfaces['owner_username']}/timeline",
    ):
        with image_lookups() as seen:
            body = client.get(route, headers=h).json()
        entries = [e for e in body if e["type"] == "post"]
        assert len([e for e in entries if e["payload"]["image_url"]]) == 8, route
        assert len(seen) == 2, (route, seen)


def test_a_url_missing_from_the_mapping_resolves_to_none(client, db_session, surfaces):
    """The batch path's guard against a caller that maps a different post set.

    ``resolved_images`` is built by the route, from a list the route also
    serialises. Should those two ever diverge, the missing url must fail closed
    rather than fall through to the raw column — the exact failure this whole
    increment exists to remove.
    """
    from app.services.seeding import serialize_post_for_viewer

    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/post-safe.png")
    post = _post(db_session, surfaces, "/static/generated/post-safe.png", mentions=False)
    viewer = db_session.query(User).filter(User.id == surfaces["viewer_id"]).first()

    with_it = serialize_post_for_viewer(
        post, viewer, db_session,
        resolved_images={"/static/generated/post-safe.png": "/static/generated/post-safe.png"},
    )
    assert with_it.image_url == "/static/generated/post-safe.png"

    without_it = serialize_post_for_viewer(
        post, viewer, db_session, resolved_images={},
    )
    assert without_it.image_url is None


def test_an_anonymous_viewer_is_treated_as_a_non_author(client, db_session, surfaces):
    """``viewer=None`` must not read as "the author" through a falsy comparison.

    No route passes ``None`` today, but the identity branch already accepts it
    and the media branch shares that same ``is_author``, so the answer for a
    missing viewer is worth pinning before something starts relying on it.
    """
    from app.services.seeding import serialize_post_for_viewer

    _char_image(db_session, surfaces["character_id"], surfaces["owner_id"],
                file_path="static/generated/studio.png", metadata={"adult_studio": True})
    post = _post(db_session, surfaces, "/static/generated/studio.png", mentions=False)

    assert serialize_post_for_viewer(post, None, db_session).image_url is None
