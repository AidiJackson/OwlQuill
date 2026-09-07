"""Ficshon's built-in account sigils — the ONLY account avatar that is a string.

WHAT A SIGIL IS. Eight small inline SVG marks the product offers as an account
avatar. They are not media: there are no bytes in a bucket, no ``UserImage``
row, nothing to own and nothing for a lifecycle or a safety state to describe.
They exist so an account has a face without anyone uploading anything, and for a
Wanderer — who has no character — the sigil is the avatar shown beside their
public username on comments.

WHY THE SERVER HOLDS THEM. Before Beta Boundary 2, ``PATCH /users/me`` accepted
ANY string as ``avatar_url``. The product only ever sent one of these eight, but
the contract accepted an arbitrary external URL, and that value is rendered by
the browser on comment threads that are served to ANONYMOUS readers. The gap
between "what the UI sends" and "what the endpoint accepts" was the whole
vulnerability, so the eight values are now stated here and matched exactly.

EXACT MATCHING, NOT A PATTERN. ``is_account_sigil`` is a set membership test
against fully-derived strings. Deliberately NOT a ``data:image/svg+xml`` prefix
check, which would accept arbitrary caller-supplied SVG — markup that the
browser executes as a document, and therefore a strictly worse thing to accept
than a remote image. A caller cannot construct a value that passes this unless
it is byte-identical to one Ficshon already ships.

DERIVED, NOT PASTED. The URLs are built here from the same spec table and the
same template the client uses, because eight 600-character opaque literals are
unreviewable — nobody can tell whether a pasted blob is the sigil it claims to
be. ``_encode_uri_component`` reproduces JavaScript's ``encodeURIComponent``
exactly (verified byte-for-byte against Node), so both sides derive the same
strings from the same source of truth rather than one side transcribing the
other.

THE TWO-SIDED PIN. ``frontend/src/lib/accountSigils.ts`` holds the client half.
Neither file imports the other, so they are pinned the way this codebase already
pins ``PUBLIC_GALLERY_KINDS`` against ``galleryKinds.ts``: each side asserts the
same digest of its own derived set (``SIGIL_SET_DIGEST``). Editing the template
or the palette on one side alone fails that side's test, which is the point —
a drifted sigil is not a cosmetic bug, it is an account avatar the server would
refuse and the user would watch fail to save.
"""
from __future__ import annotations

import hashlib
from typing import Optional
from urllib.parse import quote

#: Characters JavaScript's ``encodeURIComponent`` leaves unescaped beyond the
#: unreserved alphanumerics. Python's ``quote`` escapes ``!~*'()`` by default and
#: JS does not, so the two agree only when this is passed explicitly.
_ENCODE_URI_COMPONENT_SAFE = "-_.!~*'()"

#: ``(id, gradient_from, gradient_to, glyph_path)`` for each sigil, in the order
#: the picker shows them. Mirrors ``AVATAR_PRESETS`` in accountSigils.ts.
_SIGIL_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("ember", "#f59e0b", "#7c2d12",
     "M32 14 L38 28 L52 32 L38 36 L32 50 L26 36 L12 32 L26 28 Z"),
    ("tide", "#38bdf8", "#1e3a8a",
     "M12 38 Q22 28 32 38 T52 38 Q42 48 32 42 T12 38 Z"),
    ("grove", "#34d399", "#064e3b",
     "M32 12 Q46 26 32 52 Q18 26 32 12 Z"),
    ("dusk", "#a78bfa", "#312e81",
     "M40 14 A18 18 0 1 0 50 40 A14 14 0 1 1 40 14 Z"),
    ("rose", "#fb7185", "#881337",
     "M32 18 A8 8 0 0 1 46 24 Q46 38 32 46 Q18 38 18 24 A8 8 0 0 1 32 18 Z"),
    ("aurum", "#fbbf24", "#78350f",
     "M32 12 L36 28 L52 32 L36 36 L32 52 L28 36 L12 32 L28 28 Z"),
    ("mist", "#94a3b8", "#1e293b",
     "M20 40 A12 12 0 1 1 30 22 A10 10 0 1 1 46 30 A8 8 0 1 1 44 40 Z"),
    ("sol", "#f97316", "#7c2d12",
     "M32 20 A12 12 0 1 0 32 44 A12 12 0 1 0 32 20 Z"),
)


def _encode_uri_component(value: str) -> str:
    """Python's equivalent of JavaScript's ``encodeURIComponent``."""
    return quote(value, safe=_ENCODE_URI_COMPONENT_SAFE)


def _sigil_url(gradient_from: str, gradient_to: str, glyph: str) -> str:
    """One sigil's ``data:`` URL, built from the shared template.

    The template is duplicated in accountSigils.ts and must stay identical
    character for character — including the attribute order and the absence of
    whitespace between elements, both of which change the encoded output. The
    digest pin below is what makes a divergence fail loudly instead of silently
    refusing a user's avatar.
    """
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{gradient_from}"/>'
        f'<stop offset="1" stop-color="{gradient_to}"/>'
        "</linearGradient></defs>"
        '<rect width="64" height="64" fill="url(#g)"/>'
        f'<path d="{glyph}" fill="rgba(255,255,255,0.85)"/>'
        "</svg>"
    )
    return "data:image/svg+xml," + _encode_uri_component(svg)


#: ``sigil id -> data URL``, in picker order.
ACCOUNT_SIGILS: dict[str, str] = {
    sigil_id: _sigil_url(gradient_from, gradient_to, glyph)
    for sigil_id, gradient_from, gradient_to, glyph in _SIGIL_SPECS
}

#: The allowlist itself. A frozenset because the only question ever asked of it
#: is membership, and because it must not be mutable at runtime.
ACCOUNT_SIGIL_URLS: frozenset[str] = frozenset(ACCOUNT_SIGILS.values())

#: sha256 over the sorted sigil URLs, joined by newline. The client derives the
#: same digest from its own copy; the two tests assert the same constant. See
#: the module docstring for why this is a digest rather than a shared import.
SIGIL_SET_DIGEST: str = hashlib.sha256(
    "\n".join(sorted(ACCOUNT_SIGIL_URLS)).encode("utf-8")
).hexdigest()


def is_account_sigil(value: Optional[str]) -> bool:
    """Is *value* exactly one of Ficshon's built-in account sigils?

    Exact membership. ``None``, the empty string, a sigil with a byte changed, a
    caller-authored ``data:image/svg+xml`` payload, an ``https://`` URL and a
    storage path all answer False — there is no near-miss that passes.
    """
    if not value:
        return False
    return value in ACCOUNT_SIGIL_URLS
