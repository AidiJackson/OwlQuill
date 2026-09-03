"""Public-surface resolution for a character's denormalised avatar/cover URLs.

``Character.avatar_url`` and ``Character.cover_url`` are plain strings, not
foreign keys. They were written at different times by different paths, and only
some of those paths left a row behind that can be traced:

* ``POST /characters/{id}/cover`` stores ``file_path_to_url(image.file_path)``,
  so the URL points straight at the source image row and IS resolvable;
* ``POST /characters/{id}/avatar`` crops the source to 512×512 and calls
  ``save_image()``, which mints a NEW file with a fresh uuid and records no
  image row at all — the resulting URL is *derived* and resolves to nothing.

So "look the URL up and apply the safety rule" answers cleanly for some columns
and not at all for others, and the dev audit confirmed the unresolvable case is
the common one for historical avatars.

The rule this module implements for a character's AVATAR and COVER
(:func:`resolve_public_media_url`), Character Home V1:

* resolvable to one or more image rows → :func:`is_public_surface_safe` decides,
  fail-closed across all matches (any unsafe match suppresses the URL);
* unresolvable → returned unchanged.

The second half is a deliberate, temporary exception, safe only because of the
Step 2 publication gate: no Character Home is enabled, publication is
admin-controlled, and the first character will be audited before it is turned
on. Blanking every unresolvable URL today would suppress a large number of
legitimate historical avatars for no gain while zero Homes are public.

A post ATTACHMENT (:func:`resolve_public_post_image_url`) shares the resolution
but not that exception — see its own docstring. One normalisation rule, two
policies, rather than two normalisation rules that quietly disagree.

Presentation only. Nothing here reads or writes a character's stored pointer,
an image row, or a file on disk — the owner keeps everything they had.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character_image import CharacterImage
from app.models.user_image import UserImage
from app.schemas.character_image import is_public_post_image, is_public_surface_safe


def _candidate_file_paths(url: str) -> set[str]:
    """Every ``file_path`` spelling that ``file_path_to_url`` maps onto *url*.

    That function is not injective: ``static/generated/a.png``,
    ``/static/generated/a.png`` and ``generated/a.png`` all serve as
    ``/static/generated/a.png``. Inverting it therefore means enumerating the
    spellings rather than transforming the string once, so a row stored in any
    of them is still found. Absolute http(s) URLs are stored verbatim and match
    themselves.
    """
    if url.startswith(("http://", "https://")):
        return {url}

    path = url.lstrip("/")
    candidates = {path, f"/{path}"}
    if path.startswith("static/"):
        bare = path[len("static/"):]
        candidates |= {bare, f"/{bare}"}
    return candidates


def _rows_for_url(db: Session, url: str) -> list:
    """Image rows — character or user — whose stored file serves *url*.

    Both tables are searched because both feed the avatar/cover writers: a
    founder may set either from their own device uploads (``UserImage``) or
    from the character's own generated material (``CharacterImage``).

    Not scoped to the character. A ``file_path`` names a specific stored file,
    so matching on it identifies the image itself; narrowing by character would
    only lose the provenance of a cover set from a user image.
    """
    candidates = list(_candidate_file_paths(url))
    rows = list(
        db.query(CharacterImage)
        .filter(CharacterImage.file_path.in_(candidates))
        .all()
    )
    rows += list(
        db.query(UserImage).filter(UserImage.file_path.in_(candidates)).all()
    )
    return rows


def resolve_public_media_url(db: Session, url: Optional[str]) -> Optional[str]:
    """Return *url* if it may be shown anonymously, else ``None``.

    The one place the avatar and the cover both go, so the two cannot drift
    apart on what "safe enough to publish" means.

    Fail-closed on the resolvable path: if the URL matches several rows — a
    file promoted or copied between records — a single unsafe match withholds
    it. A URL that matches nothing is returned unchanged (see module docstring).
    """
    if not url:
        return None

    rows = _rows_for_url(db, url)
    if not rows:
        return url
    if all(is_public_surface_safe(row) for row in rows):
        return url
    return None


def resolve_public_post_image_url(db: Session, url: Optional[str]) -> Optional[str]:
    """Return a post's *url* if it may be shown anonymously, else ``None``.

    Shares :func:`_rows_for_url` with the avatar/cover resolver on purpose —
    two normalisation rules for the same denormalised URLs would eventually
    disagree, and the one that disagreed leniently would be the leak — but
    applies a STRICTER policy on top of it, in two ways.

    Eligibility is :func:`is_public_post_image` rather than
    :func:`is_public_surface_safe` alone, so an archived row (the owner's
    delete) and a row whose kind has left the post-attachable allowlist are
    both withheld.

    And an UNRESOLVABLE url returns ``None`` here, where the avatar/cover path
    returns it unchanged. The asymmetry is deliberate and evidence-based rather
    than a matter of taste: avatars are routinely unresolvable because
    ``POST /characters/{id}/avatar`` mints a derived file with no row behind it,
    so blanking them would suppress legitimate portraits wholesale. Nothing
    derives a post attachment — ``POST /realms/{id}/posts`` refuses any
    ``image_url`` that does not match an image row it can check — so a post
    image that resolves to nothing is an image whose provenance cannot be
    established, and the anonymous surface withholds it. DEV post 22 is exactly
    that shape.

    Fail-closed on ambiguity: a url matching several rows is withheld unless
    every match is eligible.

    Suppresses the image only. The post's text still publishes, and neither the
    post row nor any image row is touched.
    """
    if not url:
        return None

    rows = _rows_for_url(db, url)
    if not rows:
        return None
    if all(is_public_post_image(row) for row in rows):
        return url
    return None
