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
from typing import Optional

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


def post_image_resolution(db, posts) -> dict:
    """Resolve the image of every post in *posts* in one batch.

    Exists so the four routes that serialise posts inside their own loop —
    where :func:`serialize_posts_for_viewer` cannot be used because each row is
    zipped with a realm name — can still pay two queries instead of two per
    post. Pass the result to :func:`serialize_post_for_viewer` as
    ``resolved_images``.

    Imported lazily for the same reason the schema is: the media resolver pulls
    in the model and schema layers, and this module is imported early.
    """
    from app.services.character_home_media import resolve_public_post_image_urls

    return resolve_public_post_image_urls(
        db, [getattr(p, "image_url", None) for p in posts]
    )


def serialize_post_for_viewer(post, viewer: Optional[User], db, *, resolved_images=None):
    """Serialize a Post ORM row to its schema, for a viewer who may not be the author.

    Two policies, both about what a NON-AUTHOR may see.

    **Identity.** For a character-attributed post (``character_id`` set) viewed
    by anyone other than its author, the author's identity
    (``author_username`` and ``author_user_id``) is omitted so the post is
    attributed to the CHARACTER only and cannot be traced back to (or clustered
    by) the owning account. Characterless (legacy account-authored) posts keep
    normal ``@username`` attribution so they can link to the creator's profile.
    This is a permanent policy and is NOT gated by seeding mode.

    **Media.** An attached image is resolved through the same predicate the
    anonymous Character Home uses, so a post attachment that Ficshon will not
    publish is suppressed for every viewer but its author — being logged in is
    not a reason to see it. Before this, the resolver ran on the anonymous Home
    alone and every authenticated surface returned ``image_url`` straight from
    the row, so an image the Home withheld was served in full to the Commons
    feed. The post's text is untouched; only the image is dropped.

    ``db`` is REQUIRED rather than optional on purpose. An optional session
    would let a new call site omit it and silently fall back to publishing the
    raw URL, which is exactly the failure this change exists to remove.

    ``resolved_images`` is the batched form: a mapping produced by
    :func:`post_image_resolution`. When given, it is consulted instead of
    querying per post. A url missing from the mapping resolves to ``None``,
    which keeps the batch path fail-closed against a caller that builds the
    map from a different set of posts than it serialises.
    """
    # Imported here to avoid importing the schema layer at module load time.
    from app.schemas.post import Post as PostSchema

    schema = PostSchema.model_validate(post)
    is_author = viewer is not None and getattr(post, "author_user_id", None) == viewer.id
    is_character_post = getattr(post, "character_id", None) is not None
    if is_character_post and not is_author:
        schema.author_username = None
        schema.author_user_id = None

    # The author keeps their own attachment whatever its provenance — this is
    # their library shown back to them. Everyone else is a shared surface.
    if schema.image_url and not is_author:
        if resolved_images is None:
            from app.services.character_home_media import resolve_public_post_image_url

            schema.image_url = resolve_public_post_image_url(db, schema.image_url)
        else:
            schema.image_url = resolved_images.get(schema.image_url)

    return schema


def serialize_posts_for_viewer(posts, viewer: Optional[User], db):
    """Apply :func:`serialize_post_for_viewer` across an iterable of posts.

    Resolves every attachment in one batch first, so a feed page costs two
    queries rather than two per post.
    """
    posts = list(posts)
    resolved = post_image_resolution(db, posts)
    return [
        serialize_post_for_viewer(p, viewer, db, resolved_images=resolved)
        for p in posts
    ]


def serialize_comment_for_viewer(comment, viewer: Optional[User]):
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
    """
    from app.schemas.comment import Comment as CommentSchema

    schema = CommentSchema.model_validate(comment)
    is_author = viewer is not None and getattr(comment, "author_user_id", None) == viewer.id
    is_character_comment = getattr(comment, "character_id", None) is not None
    if is_character_comment and not is_author:
        schema.author_username = None
        schema.author_user_id = None
        schema.author_avatar_url = None
    return schema


def serialize_comments_for_viewer(comments, viewer: Optional[User]):
    """Apply :func:`serialize_comment_for_viewer` across an iterable of comments."""
    return [serialize_comment_for_viewer(c, viewer) for c in comments]
