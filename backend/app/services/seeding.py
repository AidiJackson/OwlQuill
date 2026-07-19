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


def serialize_post_for_viewer(post, viewer: Optional[User]):
    """Serialize a Post ORM row to its schema, applying character-first policy.

    For a character-attributed post (``character_id`` set) viewed by anyone
    other than its author, the author's identity (``author_username`` and
    ``author_user_id``) is omitted so the post is attributed to the CHARACTER
    only and cannot be traced back to (or clustered by) the owning account.
    Characterless (legacy account-authored) posts keep normal ``@username``
    attribution so they can link to the creator's profile. The author always
    sees full attribution on their own posts. This is a permanent policy and
    is NOT gated by seeding mode.
    """
    # Imported here to avoid importing the schema layer at module load time.
    from app.schemas.post import Post as PostSchema

    schema = PostSchema.model_validate(post)
    is_author = viewer is not None and getattr(post, "author_user_id", None) == viewer.id
    is_character_post = getattr(post, "character_id", None) is not None
    if is_character_post and not is_author:
        schema.author_username = None
        schema.author_user_id = None
    return schema


def serialize_posts_for_viewer(posts, viewer: Optional[User]):
    """Apply :func:`serialize_post_for_viewer` across an iterable of posts."""
    return [serialize_post_for_viewer(p, viewer) for p in posts]


def serialize_comment_for_viewer(comment, viewer: Optional[User]):
    """Serialize a Comment ORM row, applying the same character-first policy as
    :func:`serialize_post_for_viewer` — a character-attributed comment omits the
    author's account identity to non-author viewers; characterless comments keep
    ``@username`` attribution for creator-profile links.
    """
    from app.schemas.comment import Comment as CommentSchema

    schema = CommentSchema.model_validate(comment)
    is_author = viewer is not None and getattr(comment, "author_user_id", None) == viewer.id
    is_character_comment = getattr(comment, "character_id", None) is not None
    if is_character_comment and not is_author:
        schema.author_username = None
        schema.author_user_id = None
    return schema


def serialize_comments_for_viewer(comments, viewer: Optional[User]):
    """Apply :func:`serialize_comment_for_viewer` across an iterable of comments."""
    return [serialize_comment_for_viewer(c, viewer) for c in comments]
