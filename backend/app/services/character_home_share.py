"""Share metadata for the public Character Home (link-preview V1).

WHY THIS EXISTS
---------------
``/c/{id}`` is the URL people paste into Discord, iMessage, Slack and X. Those
crawlers fetch the HTML and read ``<head>``; none of them executes the SPA or
waits for an API call. The compiled ``dist/index.html`` carries one static
title for every route, so a pasted Character Home unfurled as "Ficshon —
Roleplay Social Network" with no character and no image.

This module produces the ``<head>`` a crawler needs, and nothing else. It does
not render the page: the SPA shell is returned unchanged apart from its head,
so React mounts into the same ``<div id="root">`` from the same hashed bundle
and behaves exactly as before.

THE RULES IT ANSWERS TO
-----------------------
* **One response for everyone.** No user-agent sniffing anywhere. A browser and
  a crawler receive identical bytes, which is what lets a creator ``curl`` their
  own Home and see precisely what Discord will see, and what stops this route
  becoming an oracle that answers differently depending on who asks.
* **The publication gate is not reimplemented.** Admission runs through
  :func:`get_public_character_home` — the same function the anonymous API
  endpoint is, raising the same 404 for missing, PRIVATE, FRIENDS and
  PUBLIC-without-the-grant. A second copy of "is this Home public?" is exactly
  how the two would drift, and the one that drifted leniently would be the leak.
* **Unpublished and nonexistent stay indistinguishable.** Both fall to the
  untouched generic shell — byte-identical to each other and to ``/login``.
* **Every creator-controlled value is escaped.** ``name``, ``alias`` and
  ``short_bio`` are free text a creator types. Unescaped, a single ``"`` closes
  a ``content`` attribute and everything after it is markup. :func:`_esc` is
  applied at the single point of injection, never at the call sites, so a new
  tag cannot be added without it.
* **Media keeps its existing safety boundary.** Images arrive already filtered
  by ``resolve_public_media_url`` inside the projection; this module chooses
  between what it was given and absolutises it, and never re-resolves or widens.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.routes.character_home import get_public_character_home
from app.schemas.character_home import CharacterHomePublic

logger = logging.getLogger(__name__)

#: Longest description emitted, in characters.
#:
#: Chosen for the strictest consumer rather than the most generous: Google
#: truncates a description around 155-160 characters and X around 200, so a
#: longer string is not shown anywhere, it is merely cut somewhere we did not
#: choose. Truncating here means the cut lands on a word boundary with an
#: ellipsis instead of mid-word in someone else's renderer.
MAX_DESCRIPTION_CHARS = 200

#: The generic card, used only when a character has no publishable image.
#:
#: Deliberately an asset that ALREADY SHIPS — `frontend/public/brand/` is copied
#: into `dist/` by the Vite build, so it is served by the existing `/brand`
#: static path with no new plumbing. At 1536x860 it is close to the 1.91:1 that
#: large-image cards crop to, so it degrades well. Generating per-character
#: share cards is a separate piece of work and deliberately not started here.
GENERIC_OG_IMAGE_PATH = "/brand/ficshon-logo-v1.jpg"

#: Open Graph type. A Character Home is a persona page, which is what `profile`
#: describes. Its `profile:*` sub-properties are optional and map to a real
#: person's name fields, so none are emitted.
OG_TYPE = "profile"

SITE_NAME = "Ficshon"

_TITLE_RE = re.compile(r"<title\b[^>]*>.*?</title>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _esc(value: str) -> str:
    """Escape a value for use as HTML text OR as a quoted attribute value.

    ``quote=True`` covers ``"`` and ``'`` as well as ``&``, ``<`` and ``>``, so
    one function serves both positions and there is no per-site judgement about
    which escaping a given tag needs — the judgement is where mistakes live.
    """
    return html.escape(value, quote=True)


def _collapse(value: str) -> str:
    """Flatten runs of whitespace, including the newlines a bio really contains.

    A raw newline inside an attribute is legal but renders as a literal break in
    some preview cards and as nothing in others. One space is what every
    consumer agrees on.
    """
    return _WHITESPACE_RE.sub(" ", value).strip()


def truncate_description(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    """Shorten *text* to *limit* characters, breaking on a word where possible.

    Runs BEFORE escaping, never after. Cutting escaped text at a fixed length
    can slice ``&amp;`` into ``&am``, which is both wrong and a stray ``&`` in
    the output. Measuring the text a human wrote is also the only measurement
    that matches what a preview card will show.
    """
    text = _collapse(text)
    if len(text) <= limit:
        return text

    # Reserve one character for the ellipsis, then step back to a word boundary
    # unless that would discard most of the string (a single long token).
    cut = text[: limit - 1]
    spaced = cut.rsplit(" ", 1)[0]
    if len(spaced) >= limit // 2:
        cut = spaced
    return cut.rstrip(" ,.;:—-") + "…"


def build_description(name: str, short_bio: Optional[str]) -> str:
    """The description a preview card shows, from the public projection alone.

    ``short_bio`` is the creator's own one-line introduction and the only field
    written to be read by a stranger. Everything else is deliberately excluded:
    ``long_bio`` is a page of prose that truncates into a fragment, ``tags``,
    ``species`` and ``role`` are keywords rather than sentences, and generation
    prompts and canon are private working data that must never reach a public
    surface at all.

    The fallback is the footer's own sentence, so a character with no bio gets a
    card that reads as a statement rather than as a missing field.
    """
    if short_bio and short_bio.strip():
        return truncate_description(short_bio)
    return f"{_collapse(name)} has a home on Ficshon."


def absolutize_media_url(url: Optional[str], base_url: Optional[str]) -> Optional[str]:
    """Make *url* absolute, or return None when it cannot be.

    Stored media comes in two shapes and both reach this function: R2 uploads
    are already absolute and are returned untouched, while historical local
    files are ``/static/...`` or ``static/...`` and are only meaningful to a
    crawler once joined to the site's own origin.

    Returns None without a base URL rather than emitting the relative path.
    Every crawler requires an absolute ``og:image``; a relative one is not a
    degraded preview, it is a broken one.
    """
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/{url.lstrip('/')}"


def choose_share_image(
    cover_url: Optional[str],
    avatar_url: Optional[str],
    base_url: Optional[str],
) -> Optional[str]:
    """The image a preview card shows: cover, then avatar, then the generic card.

    Cover first because it is the establishing shot the page itself leads with,
    and it is the wider of the two — closer to the landscape crop a large card
    applies. The avatar is the fallback that still shows the character. The
    generic Ficshon card is last and says nothing about who this is, so it is
    only ever better than no image at all.

    Both character images arrive having already passed
    ``resolve_public_media_url`` inside the projection, which returns None for
    anything the public-surface safety rule withholds. Nothing here re-resolves
    or second-guesses that: a None reaching this function IS the safety verdict,
    and falling through to the next candidate is the correct response to it.
    """
    for candidate in (cover_url, avatar_url):
        resolved = absolutize_media_url(candidate, base_url)
        if resolved:
            return resolved
    return absolutize_media_url(GENERIC_OG_IMAGE_PATH, base_url)


def canonical_url(character_id: int, base_url: Optional[str]) -> Optional[str]:
    """The one address for this Home, or None when the origin is unknown.

    Built from configuration and the id alone. The request's ``Host`` header is
    never consulted: it is attacker-controlled, so deriving the canonical origin
    from it would let anyone serve a page declaring some other domain to be the
    canonical home of a Ficshon character.

    A query string cannot survive because none is read — crawlers arrive with
    ``?utm_source=...`` appended by whatever shared the link, and every one of
    those must resolve to the same canonical address or the preview fragments
    across a dozen near-duplicate URLs.
    """
    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/c/{character_id}"


def build_head_tags(home: CharacterHomePublic, base_url: Optional[str]) -> str:
    """The ``<head>`` block for a published Character Home.

    Every value passes through :func:`_esc` HERE, at the single point where text
    becomes markup, rather than being escaped by each caller that supplies it.
    One place to audit, and a tag added later cannot forget.

    Tags whose value is unknown are OMITTED rather than emitted empty: an empty
    ``og:image`` makes a card render a broken thumbnail, and an empty canonical
    is a worse claim than no claim.
    """
    title = f"{_collapse(home.name)} | {SITE_NAME}"
    description = build_description(home.name, home.short_bio)
    image = choose_share_image(home.cover_url, home.avatar_url, base_url)
    url = canonical_url(home.id, base_url)

    lines = [
        f"<title>{_esc(title)}</title>",
        f'<meta name="description" content="{_esc(description)}" />',
        f'<meta property="og:site_name" content="{_esc(SITE_NAME)}" />',
        f'<meta property="og:type" content="{_esc(OG_TYPE)}" />',
        f'<meta property="og:title" content="{_esc(title)}" />',
        f'<meta property="og:description" content="{_esc(description)}" />',
    ]
    if url:
        lines.append(f'<meta property="og:url" content="{_esc(url)}" />')
    if image:
        lines.append(f'<meta property="og:image" content="{_esc(image)}" />')
        lines.append(
            f'<meta property="og:image:alt" content="{_esc(_collapse(home.name))}" />'
        )

    # summary_large_image only when there is an image to make large; X renders a
    # card declaring one it never receives as an empty box.
    lines.append(
        f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}" />'
    )
    lines.append(f'<meta name="twitter:title" content="{_esc(title)}" />')
    lines.append(f'<meta name="twitter:description" content="{_esc(description)}" />')
    if image:
        lines.append(f'<meta name="twitter:image" content="{_esc(image)}" />')
    if url:
        lines.append(f'<link rel="canonical" href="{_esc(url)}" />')

    return "\n    " + "\n    ".join(lines) + "\n  "


def inject_head_metadata(shell_html: str, head_tags: str) -> str:
    """Return *shell_html* with its title replaced and *head_tags* added.

    Only ``<head>`` is touched. ``<div id="root">``, the hashed module script and
    the stylesheet link are all downstream of the insertion point and are
    returned byte-for-byte, so React mounts and hydrates exactly as it does from
    the static file.

    The existing ``<title>`` is REMOVED before the new one is inserted, rather
    than substituted in place: a document with two titles has undefined
    precedence across crawlers, and removing first also handles a shell that has
    no title to substitute.

    ``re.sub`` is given a callable-free empty replacement, and the new markup is
    concatenated rather than passed as a replacement template — a replacement
    string would interpret ``\\g`` and backslashes inside escaped creator text.

    Fails safe: a shell with no ``</head>`` is returned untouched rather than
    guessed at, because a malformed injection would break the page for every
    visitor to save a preview for some.
    """
    lowered = shell_html.lower()
    idx = lowered.find("</head>")
    if idx == -1:
        logger.warning("share_metadata_no_head_close — shell returned unmodified")
        return shell_html

    without_title = _TITLE_RE.sub("", shell_html, count=1)
    # The removal may have shifted the offset; find it again on the new string.
    idx = without_title.lower().find("</head>")
    if idx == -1:  # pragma: no cover - defensive, title regex cannot eat </head>
        return shell_html
    return without_title[:idx] + head_tags + without_title[idx:]


def render_character_home_shell(
    db: Session,
    character_id: Optional[int],
    shell_html: str,
    base_url: Optional[str],
) -> str:
    """The SPA shell for ``/c/{id}`` — head-injected when published, plain when not.

    The whole security posture of this module is these few lines.

    Admission is :func:`get_public_character_home`, called directly rather than
    reimplemented, so this route and the anonymous JSON endpoint cannot disagree
    about which Homes are public. Its 404 — identical for missing, PRIVATE,
    FRIENDS and PUBLIC-without-the-grant — becomes the UNCHANGED generic shell,
    so an unpublished character and one that never existed produce the same
    bytes, and neither carries a name, an image or any other trace.

    A non-numeric id short-circuits to the same shell without a query. It cannot
    identify a character, and the SPA already renders its own "no public home"
    state for it.

    Any unexpected failure also degrades to the generic shell, logged. This is a
    public front door: a visitor meeting a stack trace because a preview could
    not be built is a worse outcome than a visitor meeting a page with a generic
    preview, and the fallback cannot leak because it is the same shell every
    unpublished character already returns.
    """
    if character_id is None:
        return shell_html

    try:
        home = get_public_character_home(character_id, db)
    except HTTPException:
        # The publication gate said no. Indistinguishable by construction.
        return shell_html
    except Exception:
        logger.exception(
            "share_metadata_failed character_id=%s — serving generic shell",
            character_id,
        )
        return shell_html

    return inject_head_metadata(shell_html, build_head_tags(home, base_url))
