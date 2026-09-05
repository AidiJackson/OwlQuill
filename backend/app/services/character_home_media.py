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
(:func:`resolve_public_media_url`):

* resolvable to one or more image rows → :func:`is_public_surface_safe` decides,
  fail-closed across all matches (any unsafe match suppresses the URL);
* unresolvable → SUPPRESSED.

The second half used to be the opposite. An unresolvable URL was returned
unchanged, as a deliberate temporary exception whose stated justification was
that no Character Home was enabled yet, so the exception could not reach anyone.
That justification expired: a Home is published, and an audit found its avatar
was one of the unresolvable ones — being served to anonymous visitors, and
emitted as ``og:image`` into third-party crawler caches, with no eligibility
decision ever applied to it.

So the rule is now the same one the post path has always used. A URL that
resolves to nothing is a URL whose provenance cannot be established, and a
surface that shows images to people other than their owner does not show it.
The cost is real and accepted: ``POST /characters/{id}/avatar`` mints a derived
file with no row behind it when it crops locally, so historical avatars are
routinely unresolvable and some will disappear from public Homes until they are
re-pointed at an image that resolves. A portrait that vanishes is recoverable;
an unvetted image on an anonymous surface is not.

Nothing here decides what an OWNER sees. Both resolvers govern shared surfaces
only — the anonymous Character Home, and posts shown to someone other than
their author. A creator's own library and their own posts are unaffected.

Presentation only. Nothing here reads or writes a character's stored pointer,
an image row, or a file on disk — the owner keeps everything they had.
"""
from typing import Iterable, Optional

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
    """Return *url* if it may be shown on a shared surface, else ``None``.

    The one place the avatar and the cover both go, so the two cannot drift
    apart on what "safe enough to publish" means.

    Fail-closed twice over. If the URL matches several rows — a file promoted
    or copied between records — a single unsafe match withholds it. And if it
    matches NO row, it is withheld too: provenance that cannot be established
    is not provenance, and this function's answer is consumed by surfaces whose
    viewers are not the owner (see module docstring for what that replaced).

    Suppresses the URL only. No image row, no stored pointer and no file on
    disk is read for anything but this decision, or written at all — the owner
    keeps everything they had, and re-pointing the character's avatar at a
    resolvable image restores it with no data recovery needed.
    """
    if not url:
        return None

    rows = _rows_for_url(db, url)
    if not rows:
        return None
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

    An UNRESOLVABLE url returns ``None``, as it now does on the avatar/cover
    path too — the two agreed on everything except this, and the avatar side
    has since been brought into line. For a post the rule was never in doubt:
    nothing derives a post attachment, because ``POST /realms/{id}/posts``
    refuses any ``image_url`` that does not match an image row it can check, so
    an unresolvable post image is one whose provenance cannot be established.

    Fail-closed on ambiguity: a url matching several rows is withheld unless
    every match is eligible.

    Suppresses the image only. The post's text still publishes, and neither the
    post row nor any image row is touched.

    Use :func:`resolve_public_post_image_urls` for more than one post: this
    issues two queries per call, which is two per post in a feed.
    """
    if not url:
        return None

    rows = _rows_for_url(db, url)
    if not rows:
        return None
    if all(is_public_post_image(row) for row in rows):
        return url
    return None


def resolve_public_post_image_urls(
    db: Session, urls: "Iterable[Optional[str]]"
) -> dict[str, Optional[str]]:
    """Batched :func:`resolve_public_post_image_url` — two queries, not two per url.

    Same decision, same fail-closed semantics, same helpers. The only thing that
    differs is how many round trips it takes, and that difference is the whole
    reason this exists: a feed page serialises every post through the resolver,
    and the single-url form issues two queries each. Twenty posts became forty
    queries. This issues two, whatever the page size.

    Returns a mapping from the ORIGINAL url string to its resolved value, so a
    caller looks up by the string it already holds. Falsy urls are skipped
    entirely rather than mapped to ``None``: a post with no image has no
    decision to record, and a caller that asks for ``""`` should not find a key.

    Correctness rests on the mapping being per-url rather than global. Candidate
    spellings are unioned to fetch in one go, but each url is then matched only
    against rows whose ``file_path`` is in ITS OWN candidate set — never against
    the whole fetched set — so two posts carrying different images cannot
    borrow each other's verdicts. That is the one thing a batch rewrite of a
    per-item predicate can quietly get wrong, so it is asserted directly in
    ``test_post_image_safety_on_shared_surfaces.py``.
    """
    wanted = [u for u in urls if u]
    if not wanted:
        return {}

    per_url: dict[str, set[str]] = {u: _candidate_file_paths(u) for u in set(wanted)}
    everything: set[str] = set()
    for candidates in per_url.values():
        everything |= candidates

    all_candidates = list(everything)
    rows = list(
        db.query(CharacterImage)
        .filter(CharacterImage.file_path.in_(all_candidates))
        .all()
    )
    rows += list(
        db.query(UserImage).filter(UserImage.file_path.in_(all_candidates)).all()
    )

    by_path: dict[str, list] = {}
    for row in rows:
        by_path.setdefault(row.file_path, []).append(row)

    resolved: dict[str, Optional[str]] = {}
    for url, candidates in per_url.items():
        matches = [row for path in candidates for row in by_path.get(path, [])]
        if not matches:
            resolved[url] = None
        elif all(is_public_post_image(row) for row in matches):
            resolved[url] = url
        else:
            resolved[url] = None
    return resolved
