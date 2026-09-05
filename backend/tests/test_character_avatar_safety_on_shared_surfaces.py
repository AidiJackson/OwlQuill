"""A character's avatar answers to the Home's rule wherever it travels.

``Character.avatar_url`` is denormalised onto everything the character writes.
``Post.character_avatar_url`` and ``Comment.character_avatar_url`` are model
properties that read that column straight through, and Story Space posts copy
it by hand. Phase 3A closed the attachment (``Post.image_url``) on every shared
surface and left these open, so an avatar the anonymous Character Home refused
to publish still rendered beside every post and comment that character had
written — and, on the comment list, to readers with no account at all, since
``GET /posts/{id}/comments`` authenticates optionally.

The rule applied here is not a new one. It is :func:`resolve_public_media_url`,
the same predicate the Home applies to the same column, batched. Every
assertion below compares against what the Home itself returns rather than
against a hardcoded ``None``, so the two are pinned together and cannot drift.

Three surfaces families, one answer:

* the seven authenticated post surfaces Phase 3A already enumerated;
* the comment list, authenticated AND anonymous;
* Story Space channel posts, where a co-member is not the character's owner.

The author keeps their own avatar everywhere, as they keep their own
attachment. Nothing here writes to ``Character.avatar_url``: suppression is
presentation, and re-pointing or re-vetting restores the image untouched.
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
from app.models.comment import Comment
from app.models.post import ContentTypeEnum, Post
from app.models.post_mention import PostMention
from app.models.realm import Realm, RealmMembership
from app.models.story_space import (
    StorySpace,
    StorySpaceChannel,
    StorySpaceMember,
    StorySpacePost,
)
from app.models.user import User
from tests.conftest import auth_headers, engine, get_auth_token


AVATAR = "/static/generated/summer-avatar.png"


# ── Fixtures and helpers ──────────────────────────────────────────────────────

def _user_id(db_session, email) -> int:
    return db_session.query(User).filter(User.email == email).first().id


def _char_image(db_session, character_id, user_id, *, file_path,
                provider="fal", metadata=None, status=ImageStatusEnum.ACTIVE,
                kind=ImageKindEnum.GENERATED):
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


def _set_avatar(db_session, character_id, url):
    row = db_session.query(Character).filter(Character.id == character_id).first()
    row.avatar_url = url
    db_session.commit()


@pytest.fixture()
def avatars(client, db_session):
    """One character with an avatar, writing on every surface that shares it.

    The avatar column is set here; each test decides what (if anything) backs
    it, which is the whole variable under test.
    """
    owner_token = get_auth_token(client, email="av-own@test.com", username="avown")
    resp = client.post(
        "/characters/",
        json={"name": "Summer", "species": "human", "visibility": "public"},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    owner_id = _user_id(db_session, "av-own@test.com")

    character = db_session.query(Character).filter(Character.id == cid).first()
    character.public_home_enabled = True
    character.avatar_url = AVATAR
    db_session.commit()

    viewer_token = get_auth_token(client, email="av-see@test.com", username="avsee")
    viewer_id = _user_id(db_session, "av-see@test.com")

    realm = Realm(owner_id=owner_id, name="Open Square",
                  slug=f"open-square-{uuid4().hex[:8]}", is_public=True)
    db_session.add(realm)
    db_session.commit()
    db_session.refresh(realm)
    db_session.add_all([
        RealmMembership(realm_id=realm.id, user_id=owner_id, role="owner"),
        RealmMembership(realm_id=realm.id, user_id=viewer_id),
    ])
    db_session.commit()

    post = Post(
        realm_id=realm.id, author_user_id=owner_id, character_id=cid,
        content="A scene.", content_type=ContentTypeEnum.IC, post_kind="general",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    db_session.add(post)
    db_session.commit()
    db_session.refresh(post)
    db_session.add_all([
        PostMention(post_id=post.id, mention_text="@Summer", mentioned_character_id=cid),
        PostMention(post_id=post.id, mention_text="@avown", mentioned_user_id=owner_id),
    ])

    comment = Comment(post_id=post.id, author_user_id=owner_id, character_id=cid,
                      content="And a reply.")
    db_session.add(comment)

    space = StorySpace(owner_id=owner_id, name="The Workshop")
    db_session.add(space)
    db_session.commit()
    db_session.refresh(space)
    channel = StorySpaceChannel(space_id=space.id, channel_type="story",
                                name="Story", position=0)
    db_session.add(channel)
    db_session.add_all([
        StorySpaceMember(space_id=space.id, user_id=owner_id, role="owner"),
        StorySpaceMember(space_id=space.id, user_id=viewer_id, role="member"),
    ])
    db_session.commit()
    db_session.refresh(channel)
    space_post = StorySpacePost(
        space_id=space.id, channel_id=channel.id, author_user_id=owner_id,
        character_id=cid, content="In the workshop.", content_type="ic",
    )
    db_session.add(space_post)
    db_session.commit()

    return {
        "owner_token": owner_token, "owner_id": owner_id, "owner_username": "avown",
        "viewer_token": viewer_token, "viewer_id": viewer_id,
        "character_id": cid, "realm": realm, "post_id": post.id,
        "space_id": space.id, "channel_id": channel.id,
    }


def _pick(entries, post_id):
    for entry in entries:
        if entry["id"] == post_id:
            return entry
    raise AssertionError(f"post {post_id} absent from {entries}")


def _pick_payload(entries, post_id):
    for entry in entries:
        if entry.get("payload", {}).get("id") == post_id:
            return entry["payload"]
    raise AssertionError(f"post {post_id} absent from {entries}")


def home_avatar(client, ctx):
    """The avatar as the anonymous Character Home publishes it — the reference."""
    resp = client.get(f"/characters/{ctx['character_id']}/public-home")
    assert resp.status_code == 200, resp.text
    return resp.json()["avatar_url"]


def shared_surface_avatars(client, ctx, token):
    """``character_avatar_url`` for this character from every surface sharing it.

    Named per route so a failure says which one regressed. The anonymous
    comment list is included unconditionally: it takes no token, so "what an
    authenticated viewer sees" is not the whole question on that surface.
    """
    h = auth_headers(token)
    u, cid, rid, pid = (ctx["owner_username"], ctx["character_id"],
                        ctx["realm"].id, ctx["post_id"])

    def ok(resp):
        assert resp.status_code == 200, resp.text
        return resp.json()

    return {
        "feed": _pick(ok(client.get("/posts/feed", headers=h)), pid)["character_avatar_url"],
        "realm_posts": _pick(
            ok(client.get(f"/posts/realms/{rid}/posts", headers=h)), pid
        )["character_avatar_url"],
        "single_post": ok(client.get(f"/posts/{pid}", headers=h))["character_avatar_url"],
        "user_timeline": _pick_payload(
            ok(client.get(f"/users/{u}/timeline", headers=h)), pid
        )["character_avatar_url"],
        "user_mentions": _pick(
            ok(client.get(f"/users/{u}/mentions", headers=h)), pid
        )["character_avatar_url"],
        "character_posts": _pick_payload(
            ok(client.get(f"/characters/{cid}/posts", headers=h)), pid
        )["character_avatar_url"],
        "character_mentions": _pick_payload(
            ok(client.get(f"/characters/{cid}/mentions", headers=h)), pid
        )["character_avatar_url"],
        "comments": ok(
            client.get(f"/comments/posts/{pid}/comments", headers=h)
        )[0]["character_avatar_url"],
        "comments_anonymous": ok(
            client.get(f"/comments/posts/{pid}/comments")
        )[0]["character_avatar_url"],
        "story_space_posts": ok(client.get(
            f"/story-spaces/{ctx['space_id']}/channels/{ctx['channel_id']}/posts",
            headers=h,
        ))[0]["character_avatar_url"],
    }


@contextmanager
def image_lookups():
    """Record statements reading an image table, on the test engine."""
    seen = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if "character_images" in statement or "user_images" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


#: The provenance exclusions, one per layer the shared predicate checks.
UNSAFE_ROWS = [
    ("fal", {"adult_studio": True}),
    ("gpt-image", {"editor_generated": True}),
    ("replicate_nsfw", {}),
    ("self_hosted", {}),
    ("fal", {"provider": "replicate_nsfw"}),
]


# ── A. The bypass, closed on every surface at once ────────────────────────────

def test_unsafe_avatar_is_suppressed_on_every_shared_surface(client, db_session, avatars):
    """The Phase 3A gap: an avatar the Home refuses, rendered beside every post.

    Compared against the Home's own answer, not against ``None``, so if the
    Home ever starts publishing this row the failure lands on the Home rather
    than quietly widening what a logged-in reader is handed.
    """
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                metadata={"adult_studio": True})

    home = home_avatar(client, avatars)
    assert home is None

    seen = shared_surface_avatars(client, avatars, avatars["viewer_token"])
    assert seen == {k: home for k in seen}, seen


def test_unresolvable_avatar_is_suppressed_on_every_shared_surface(
    client, db_session, avatars
):
    """The G-2 case, now applied wherever the avatar travels.

    ``POST /characters/{id}/avatar`` crops and mints a derived file with no row
    behind it, so this is the COMMON shape for historical avatars, not an edge
    case. Provenance that cannot be established is not provenance.
    """
    home = home_avatar(client, avatars)
    assert home is None

    seen = shared_surface_avatars(client, avatars, avatars["viewer_token"])
    assert seen == {k: home for k in seen}, seen


def test_safe_avatar_renders_on_every_shared_surface(client, db_session, avatars):
    """Fail-closed has to stop at the avatars that deserve it."""
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png")

    home = home_avatar(client, avatars)
    assert home == AVATAR

    seen = shared_surface_avatars(client, avatars, avatars["viewer_token"])
    assert seen == {k: home for k in seen}, seen


def test_absolute_r2_avatar_renders(client, db_session, avatars):
    """Current avatars are absolute R2 urls; only legacy ones are relative."""
    url = "https://pub-abc.r2.dev/generated/summer.png"
    _set_avatar(db_session, avatars["character_id"], url)
    _char_image(db_session, avatars["character_id"], avatars["owner_id"], file_path=url)

    assert home_avatar(client, avatars) == url
    seen = shared_surface_avatars(client, avatars, avatars["viewer_token"])
    assert seen == {k: url for k in seen}, seen


@pytest.mark.parametrize("provider,metadata", UNSAFE_ROWS)
def test_every_exclusion_layer_reaches_the_feed_and_anonymous_comments(
    client, db_session, avatars, provider, metadata
):
    """All five provenance layers, on the two surfaces that matter most.

    The full ten-surface sweep runs once above; running it five more times buys
    nothing, because every surface shares one serializer. What is worth
    repeating per layer is that the shared predicate is reached at all — here
    on the busiest authenticated surface and on the one that takes no token.
    """
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                provider=provider, metadata=metadata)

    h = auth_headers(avatars["viewer_token"])
    feed = _pick(client.get("/posts/feed", headers=h).json(), avatars["post_id"])
    anon = client.get(f"/comments/posts/{avatars['post_id']}/comments").json()

    assert home_avatar(client, avatars) is None
    assert feed["character_avatar_url"] is None
    assert anon[0]["character_avatar_url"] is None


def test_an_archived_avatar_row_still_publishes(client, db_session, avatars):
    """Status is a POST-ATTACHMENT rule, not an avatar rule, and stays that way.

    ``is_public_surface_safe`` deliberately knows nothing about status or kind
    — those are per-surface lifecycle questions, and the avatar surface has
    always answered them differently from the attachment surface. Pinned so
    "apply the safety rule to avatars too" is never quietly read as "apply the
    post rule to avatars".
    """
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                status=ImageStatusEnum.ARCHIVED, kind=ImageKindEnum.IDENTITY_FACE_REF)

    assert home_avatar(client, avatars) == AVATAR
    seen = shared_surface_avatars(client, avatars, avatars["viewer_token"])
    assert seen == {k: AVATAR for k in seen}, seen


def test_ambiguous_avatar_resolution_fails_closed(client, db_session, avatars):
    """One url, two rows, one unsafe — the unsafe one decides, as on the Home."""
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png")
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                provider="replicate_nsfw")

    home = home_avatar(client, avatars)
    assert home is None
    seen = shared_surface_avatars(client, avatars, avatars["viewer_token"])
    assert seen == {k: home for k in seen}, seen


# ── B. Suppression is media-only, and presentation-only ───────────────────────

def test_the_character_is_still_named_and_the_text_still_publishes(
    client, db_session, avatars
):
    """Dropping the portrait must not drop the identity or the writing."""
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                metadata={"adult_studio": True})

    h = auth_headers(avatars["viewer_token"])
    post = client.get(f"/posts/{avatars['post_id']}", headers=h).json()
    comment = client.get(f"/comments/posts/{avatars['post_id']}/comments").json()[0]

    assert post["character_avatar_url"] is None
    assert post["character_name"] == "Summer"
    assert post["content"] == "A scene."
    assert comment["character_avatar_url"] is None
    assert comment["character_name"] == "Summer"
    assert comment["content"] == "And a reply."


def test_suppression_does_not_touch_the_stored_avatar_pointer(
    client, db_session, avatars
):
    """Presentation only, and reversible the moment the row becomes eligible."""
    img = _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                      file_path="static/generated/summer-avatar.png",
                      provider="replicate_nsfw")
    h = auth_headers(avatars["viewer_token"])

    assert client.get(f"/posts/{avatars['post_id']}", headers=h).json()[
        "character_avatar_url"] is None

    db_session.expire_all()
    row = db_session.query(Character).filter(
        Character.id == avatars["character_id"]).first()
    assert row.avatar_url == AVATAR

    img = db_session.query(CharacterImage).filter(CharacterImage.id == img.id).first()
    img.provider = "fal"
    db_session.commit()
    assert client.get(f"/posts/{avatars['post_id']}", headers=h).json()[
        "character_avatar_url"] == AVATAR


def test_no_character_cover_is_serialised_beside_a_post_or_comment(client, avatars):
    """The cover has no denormalised path to a shared surface, and must not gain one.

    ``Character.cover_url`` is resolved on the Home and nowhere else, because
    nowhere else carries it. This is the regression guard for that: a field
    added here later would arrive unresolved, exactly as the avatar did.
    """
    h = auth_headers(avatars["viewer_token"])
    post = client.get(f"/posts/{avatars['post_id']}", headers=h).json()
    comment = client.get(f"/comments/posts/{avatars['post_id']}/comments").json()[0]

    for payload in (post, comment):
        assert not [k for k in payload if "cover" in k], payload.keys()


# ── C. The author is not a shared surface ─────────────────────────────────────

def test_the_author_keeps_their_own_unsafe_avatar_everywhere(
    client, db_session, avatars
):
    """Their own character, shown back to them. Same policy as their attachment."""
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                metadata={"adult_studio": True})

    assert home_avatar(client, avatars) is None

    mine = shared_surface_avatars(client, avatars, avatars["owner_token"])
    # The anonymous comment read takes no token and is therefore never "mine".
    assert mine.pop("comments_anonymous") is None
    assert mine == {k: AVATAR for k in mine}, mine


def test_the_author_keeps_an_unresolvable_avatar_too(client, avatars):
    """Fail-closed is a publication rule, not a possession rule."""
    mine = shared_surface_avatars(client, avatars, avatars["owner_token"])
    assert mine.pop("comments_anonymous") is None
    assert mine == {k: AVATAR for k in mine}, mine


def test_a_second_member_of_the_space_is_not_the_owner(client, db_session, avatars):
    """Story Spaces are collaborative, so a co-member is still a shared surface.

    Membership admits you to the room; it does not make you the character's
    owner, and the avatar rule keys on ownership.
    """
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                provider="self_hosted")
    url = (f"/story-spaces/{avatars['space_id']}"
           f"/channels/{avatars['channel_id']}/posts")

    theirs = client.get(url, headers=auth_headers(avatars["viewer_token"])).json()
    ours = client.get(url, headers=auth_headers(avatars["owner_token"])).json()
    assert theirs[0]["character_avatar_url"] is None
    assert ours[0]["character_avatar_url"] == AVATAR


# ── D. Batch resolution: constant cost, no borrowed verdicts ──────────────────

def test_a_page_of_posts_costs_a_fixed_number_of_avatar_lookups(
    client, db_session, avatars
):
    """Twelve posts, one avatar question. Not twelve of them.

    The avatar is denormalised onto every post, so the naive form asks the same
    question about the same url once per row. Two image-table queries for the
    whole page, whatever its size — and no attachment on these posts, so the
    attachment batch is skipped entirely rather than querying for nothing.
    """
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png")
    for i in range(11):
        db_session.add(Post(
            realm_id=avatars["realm"].id, author_user_id=avatars["owner_id"],
            character_id=avatars["character_id"], content=f"Post {i}.",
            content_type=ContentTypeEnum.IC, post_kind="general",
            created_at=datetime(2026, 1, 2, 12, 0, 0),
        ))
    db_session.commit()

    h = auth_headers(avatars["viewer_token"])
    with image_lookups() as seen:
        body = client.get("/posts/feed", headers=h).json()

    assert len(body) == 12
    assert all(p["character_avatar_url"] == AVATAR for p in body)
    assert len(seen) == 2, seen


def test_a_page_of_comments_costs_a_fixed_number_of_avatar_lookups(
    client, db_session, avatars
):
    """Same property on the comment list, which has no attachment to batch."""
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png")
    for i in range(9):
        db_session.add(Comment(
            post_id=avatars["post_id"], author_user_id=avatars["owner_id"],
            character_id=avatars["character_id"], content=f"Reply {i}.",
        ))
    db_session.commit()

    with image_lookups() as seen:
        body = client.get(f"/comments/posts/{avatars['post_id']}/comments").json()

    assert len(body) == 10
    assert all(c["character_avatar_url"] == AVATAR for c in body)
    assert len(seen) == 2, seen


def test_a_channel_of_space_posts_costs_a_fixed_number_of_avatar_lookups(
    client, db_session, avatars
):
    """And on Story Space channels, which resolve outside the shared serializer."""
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png")
    for i in range(9):
        db_session.add(StorySpacePost(
            space_id=avatars["space_id"], channel_id=avatars["channel_id"],
            author_user_id=avatars["owner_id"], character_id=avatars["character_id"],
            content=f"Beat {i}.", content_type="ic",
        ))
    db_session.commit()

    h = auth_headers(avatars["viewer_token"])
    with image_lookups() as seen:
        body = client.get(
            f"/story-spaces/{avatars['space_id']}"
            f"/channels/{avatars['channel_id']}/posts", headers=h,
        ).json()

    assert len(body) == 10
    assert all(p["character_avatar_url"] == AVATAR for p in body)
    assert len(seen) == 2, seen


def test_a_post_carrying_both_an_attachment_and_an_avatar_costs_four(
    client, db_session, avatars
):
    """Two independent questions, two independent batches, both page-constant.

    Four rather than two because an attachment and an avatar answer to
    different predicates and cannot share a verdict. Pinned as a number so a
    later change back to per-post resolution shows up as arithmetic rather than
    as a slow feed nobody measures.
    """
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png")
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/attach.png")
    for i in range(7):
        db_session.add(Post(
            realm_id=avatars["realm"].id, author_user_id=avatars["owner_id"],
            character_id=avatars["character_id"], content=f"Post {i}.",
            content_type=ContentTypeEnum.IC, post_kind="general",
            image_url="/static/generated/attach.png",
            created_at=datetime(2026, 1, 2, 12, 0, 0),
        ))
    db_session.commit()

    h = auth_headers(avatars["viewer_token"])
    with image_lookups() as seen:
        body = client.get("/posts/feed", headers=h).json()

    assert len([p for p in body if p["image_url"]]) == 7
    assert all(p["character_avatar_url"] == AVATAR for p in body)
    assert len(seen) == 4, seen


def test_an_attachment_verdict_cannot_decide_an_avatar(client, db_session, avatars):
    """The two maps are separate because the two rules are.

    An ARCHIVED row is ineligible as an attachment and perfectly eligible as an
    avatar. One url wearing both hats is the sharpest form of that: if the
    verdicts were merged, one of these two assertions has to be wrong.
    """
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                status=ImageStatusEnum.ARCHIVED)
    db_session.add(Post(
        realm_id=avatars["realm"].id, author_user_id=avatars["owner_id"],
        character_id=avatars["character_id"], content="Both at once.",
        content_type=ContentTypeEnum.IC, post_kind="general",
        image_url=AVATAR, created_at=datetime(2026, 1, 3, 12, 0, 0),
    ))
    db_session.commit()

    h = auth_headers(avatars["viewer_token"])
    entry = client.get("/posts/feed", headers=h).json()[0]
    assert entry["content"] == "Both at once."
    assert entry["image_url"] is None        # post rule: archived is withdrawn
    assert entry["character_avatar_url"] == AVATAR   # avatar rule: status is not its business


def test_two_characters_do_not_borrow_each_others_avatar_verdicts(
    client, db_session, avatars
):
    """The batch's one genuinely new failure mode, on the avatar map this time."""
    from app.services.character_home_media import resolve_public_media_urls

    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/clean-face.png")
    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/studio-face.png",
                metadata={"adult_studio": True})

    clean = "/static/generated/clean-face.png"
    studio = "/static/generated/studio-face.png"
    missing = "/static/generated/no-row.png"

    assert resolve_public_media_urls(db_session, [clean, studio, missing]) == \
        {clean: clean, studio: None, missing: None}
    assert resolve_public_media_urls(db_session, [missing, studio, clean]) == \
        {clean: clean, studio: None, missing: None}
    assert resolve_public_media_urls(db_session, []) == {}
    assert resolve_public_media_urls(db_session, [None, ""]) == {}


def test_a_url_missing_from_the_avatar_map_resolves_to_none(client, db_session, avatars):
    """The fail-closed guard against a caller mapping a different row set."""
    from app.services.seeding import PostMedia, serialize_post_for_viewer

    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png")
    post = db_session.query(Post).filter(Post.id == avatars["post_id"]).first()
    viewer = db_session.query(User).filter(User.id == avatars["viewer_id"]).first()

    with_it = serialize_post_for_viewer(
        post, viewer, db_session,
        resolved_media=PostMedia(images={}, avatars={AVATAR: AVATAR}),
    )
    assert with_it.character_avatar_url == AVATAR

    without_it = serialize_post_for_viewer(
        post, viewer, db_session, resolved_media=PostMedia(images={}, avatars={}),
    )
    assert without_it.character_avatar_url is None


def test_an_anonymous_viewer_is_treated_as_a_non_owner(client, db_session, avatars):
    """``viewer=None`` must not read as the author through a falsy comparison.

    The comment list really does pass ``None`` — this is not a hypothetical
    branch here the way it is for posts.
    """
    from app.services.seeding import serialize_comment_for_viewer

    _char_image(db_session, avatars["character_id"], avatars["owner_id"],
                file_path="static/generated/summer-avatar.png",
                provider="replicate_nsfw")
    comment = db_session.query(Comment).filter(
        Comment.post_id == avatars["post_id"]).first()

    assert serialize_comment_for_viewer(
        comment, None, db_session).character_avatar_url is None


def test_a_characterless_comment_needs_no_avatar_decision(client, db_session, avatars):
    """A Wanderer comment has no character, so nothing to resolve and nothing to query."""
    db_session.add(Comment(post_id=avatars["post_id"],
                           author_user_id=avatars["viewer_id"],
                           content="Passing through."))
    db_session.commit()

    with image_lookups() as seen:
        body = client.get(f"/comments/posts/{avatars['post_id']}/comments").json()

    wanderer = [c for c in body if c["content"] == "Passing through."][0]
    assert wanderer["character_avatar_url"] is None
    # The character comment in the fixture still drives one batch; what matters
    # is that the characterless one adds no query of its own.
    assert len(seen) == 2, seen
