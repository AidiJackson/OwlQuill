"""Seeding / roster-privacy helpers (Step 2).

Two related concerns live here:

1. **Seeder exemption** — which accounts are exempt from the
   one-character-per-account limit. A caller is a "seeder account" when any of:
   - ``user.is_admin`` is set (founders are provisioned as admins), or
   - ``user.is_seeder`` is set (dedicated seeder flag, no admin powers), or
   - the caller's email is listed in ``ADMIN_EMAILS`` / ``ADMIN_EMAIL``, or
   - the caller's email is listed in ``SEEDER_EMAILS``.

   Seeders may own multiple characters for seeding; normal users may own one.

2. **Roster privacy** — whether a viewer may enumerate/see a target user's
   character roster. Gated by ``settings.SEEDING_MODE`` (default ON): when on,
   a roster is visible only to its owner. This covers MULTIPLE seeding accounts
   — no seeder can enumerate another user's roster either.

Note: the *character-first attribution* and *owner-link-to-owner-only* behaviours
(omitting ``owner_username`` / ``author_username`` from character-attributed
payloads for non-owner viewers) are PERMANENT product decisions and are applied
directly in the route/serialization layer — they are intentionally NOT gated by
``SEEDING_MODE``.
"""
from typing import NamedTuple, Optional

from app.core.config import settings
from app.models.user import User


def is_seeder_account(user: Optional[User]) -> bool:
    """True when ``user`` is exempt from the one-character-per-account limit.

    Exemption is scoped to admins (``is_admin`` flag or ADMIN_EMAILS config) and
    dedicated seeders (``is_seeder`` flag or SEEDER_EMAILS config). Any of these
    grants the exemption; a plain user matches none and is capped at one.
    """
    if user is None:
        return False
    if bool(getattr(user, "is_admin", False)) or bool(getattr(user, "is_seeder", False)):
        return True
    email = (getattr(user, "email", "") or "").lower()
    if not email:
        return False
    return email in settings.get_admin_emails() or email in settings.get_seeder_emails()


def seeding_mode_enabled() -> bool:
    """True when roster-hiding (seeding mode) is active. Default ON."""
    return bool(settings.SEEDING_MODE)


def roster_visible_to(viewer: Optional[User], target_user_id: int) -> bool:
    """True when ``viewer`` may see ``target_user_id``'s character roster.

    In seeding mode a roster is visible only to its owner (so no user — seeder or
    not — can enumerate another user's roster). With seeding mode off, rosters are
    visible to everyone (public-character discovery is handled by the caller).
    """
    if not seeding_mode_enabled():
        return True
    return viewer is not None and viewer.id == target_user_id


class PostMedia(NamedTuple):
    """The two media verdicts a page of posts needs, each keyed by its own url.

    Two maps rather than one because the two answers come from DIFFERENT
    predicates — an attachment answers to the post rule, an avatar to the
    avatar/cover rule — and the same url string could in principle appear in
    both. Merging them would let one surface's verdict decide the other's.
    """

    images: dict
    avatars: dict


def post_media_resolution(db, posts) -> PostMedia:
    """Resolve the attachment AND the character avatar of every post, in batches.

    Exists so the four routes that serialise posts inside their own loop —
    where :func:`serialize_posts_for_viewer` cannot be used because each row is
    zipped with a realm name — can still pay a fixed number of queries instead
    of a number that grows with the page. Pass the result to
    :func:`serialize_post_for_viewer` as ``resolved_media``.

    Four image-table queries per page, not two, now that the avatar is resolved
    too. Still constant in the page size, which is the property that matters;
    folding the two into one fetch would mean carrying a per-url predicate
    through the batch, and the cost of that complexity outweighs two queries.

    Reading ``character_avatar_url`` adds no query of its own: the property
    walks ``post.character``, which :func:`serialize_post_for_viewer` loads for
    every post anyway when it validates the schema.

    Imported lazily for the same reason the schema is: the media resolver pulls
    in the model and schema layers, and this module is imported early.
    """
    from app.services.character_home_media import (
        resolve_public_media_urls,
        resolve_public_post_image_urls,
    )

    posts = list(posts)
    return PostMedia(
        images=resolve_public_post_image_urls(
            db, [getattr(p, "image_url", None) for p in posts]
        ),
        avatars=resolve_public_media_urls(
            db, [getattr(p, "character_avatar_url", None) for p in posts]
        ),
    )


def character_avatar_resolution(db, rows) -> dict:
    """Batch the avatar verdict for any rows exposing ``character_avatar_url``.

    Comments carry the same denormalised avatar posts do, and reach the same
    non-owner readers — more of them, in fact, since a public realm's comments
    are served without a token at all. They have no attachment, so they need
    only this half of :func:`post_media_resolution`.
    """
    from app.services.character_home_media import resolve_public_media_urls

    return resolve_public_media_urls(
        db, [getattr(r, "character_avatar_url", None) for r in rows]
    )


def serialize_post_for_viewer(post, viewer: Optional[User], db, *, resolved_media=None):
    """Serialize a Post ORM row to its schema, for a viewer who may not be the author.

    Two policies, both about what a NON-AUTHOR may see.

    **Identity.** For a character-attributed post (``character_id`` set) viewed
    by anyone other than its author, the author's identity
    (``author_username`` and ``author_user_id``) is omitted so the post is
    attributed to the CHARACTER only and cannot be traced back to (or clustered
    by) the owning account. Characterless (legacy account-authored) posts keep
    normal ``@username`` attribution so they can link to the creator's profile.
    This is a permanent policy and is NOT gated by seeding mode.

    **Media.** A post carries TWO images, and both are resolved through the
    predicates the anonymous Character Home uses, so neither reaches a viewer
    who is not the author when Ficshon would not publish it — being logged in
    is not a reason to see it.

    * the ATTACHMENT (``image_url``), through the post-attachment rule. Before
      this, the resolver ran on the anonymous Home alone and every
      authenticated surface returned ``image_url`` straight from the row, so an
      image the Home withheld was served in full to the Commons feed.
    * the character's AVATAR (``character_avatar_url``), through the
      avatar/cover rule. It is denormalised off ``Character.avatar_url`` by a
      model property, which is the same column the Home resolves — and it was
      being read straight through, so an avatar the Home suppressed still
      rendered beside every post that character had written.

    The post's text, its attribution and every other field are untouched; only
    the images are dropped, and each independently of the other.

    ``db`` is REQUIRED rather than optional on purpose. An optional session
    would let a new call site omit it and silently fall back to publishing the
    raw URL, which is exactly the failure this change exists to remove.

    ``resolved_media`` is the batched form: a :class:`PostMedia` produced by
    :func:`post_media_resolution`. When given, it is consulted instead of
    querying per post. A url missing from either mapping resolves to ``None``,
    which keeps the batch path fail-closed against a caller that builds the
    maps from a different set of posts than it serialises.
    """
    # Imported here to avoid importing the schema layer at module load time.
    from app.schemas.post import Post as PostSchema

    schema = PostSchema.model_validate(post)
    is_author = viewer is not None and getattr(post, "author_user_id", None) == viewer.id
    is_character_post = getattr(post, "character_id", None) is not None
    if is_character_post and not is_author:
        schema.author_username = None
        schema.author_user_id = None

    # The author keeps their own media whatever its provenance — this is their
    # library shown back to them. Everyone else is a shared surface.
    if not is_author:
        if schema.image_url:
            if resolved_media is None:
                from app.services.character_home_media import (
                    resolve_public_post_image_url,
                )

                schema.image_url = resolve_public_post_image_url(db, schema.image_url)
            else:
                schema.image_url = resolved_media.images.get(schema.image_url)

        if schema.character_avatar_url:
            if resolved_media is None:
                from app.services.character_home_media import resolve_public_media_url

                schema.character_avatar_url = resolve_public_media_url(
                    db, schema.character_avatar_url
                )
            else:
                schema.character_avatar_url = resolved_media.avatars.get(
                    schema.character_avatar_url
                )

    return schema


def serialize_posts_for_viewer(posts, viewer: Optional[User], db):
    """Apply :func:`serialize_post_for_viewer` across an iterable of posts.

    Resolves every attachment and every avatar in batches first, so a feed page
    costs a fixed number of queries rather than a number per post.
    """
    posts = list(posts)
    resolved = post_media_resolution(db, posts)
    return [
        serialize_post_for_viewer(p, viewer, db, resolved_media=resolved)
        for p in posts
    ]


def serialize_comment_for_viewer(comment, viewer: Optional[User], db, *, resolved_avatars=None):
    """Serialize a Comment ORM row, applying the same character-first policy as
    :func:`serialize_post_for_viewer`.

    Two public identities, one per account type:

    * **Writer** (character-attributed comment) — the character only. The
      account username *and* the account sigil are stripped for every viewer
      but the author, so a Writer's public output never carries the private
      account identity.
    * **Wanderer** (characterless comment) — the public Wanderer username and
      the account sigil are kept, because for a Wanderer that *is* the public
      identity, not a leak of a private one.

    And the same MEDIA policy as posts, for the same reason: a comment carries
    the writing character's avatar, denormalised off ``Character.avatar_url``
    by a model property. It is resolved through the avatar/cover rule for every
    viewer but the author.

    This surface needs it more than posts do, not less. ``GET
    /posts/{id}/comments`` authenticates optionally — a public realm's comments
    are served to a caller with no token at all — so an unresolved avatar here
    was reaching genuinely anonymous readers, which is precisely the audience
    the Character Home resolver was written for.

    ``db`` is required for the same reason it is on the post serializer: an
    optional session is an invitation for a new call site to publish the raw
    url. ``resolved_avatars`` is the batched form, from
    :func:`character_avatar_resolution`; a url missing from it resolves to
    ``None``, keeping the batch path fail-closed.
    """
    from app.schemas.comment import Comment as CommentSchema

    schema = CommentSchema.model_validate(comment)
    is_author = viewer is not None and getattr(comment, "author_user_id", None) == viewer.id
    is_character_comment = getattr(comment, "character_id", None) is not None
    if is_character_comment and not is_author:
        schema.author_username = None
        schema.author_user_id = None
        schema.author_avatar_url = None

    if schema.character_avatar_url and not is_author:
        if resolved_avatars is None:
            from app.services.character_home_media import resolve_public_media_url

            schema.character_avatar_url = resolve_public_media_url(
                db, schema.character_avatar_url
            )
        else:
            schema.character_avatar_url = resolved_avatars.get(
                schema.character_avatar_url
            )
    return schema


def serialize_comments_for_viewer(comments, viewer: Optional[User], db):
    """Apply :func:`serialize_comment_for_viewer` across an iterable of comments.

    Resolves every avatar in one batch first — a busy post's comment list would
    otherwise pay two queries per comment to answer the same question about the
    same one or two characters.
    """
    comments = list(comments)
    resolved = character_avatar_resolution(db, comments)
    return [
        serialize_comment_for_viewer(c, viewer, db, resolved_avatars=resolved)
        for c in comments
    ]
