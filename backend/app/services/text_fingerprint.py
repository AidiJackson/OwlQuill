"""Shingle fingerprinting for AI-output matching.

Text is reduced to a set of hashes of overlapping 8-word windows. Two texts
sharing a passage share the hashes covering it, so an exact or lightly-edited
paste is detectable by an indexed integer lookup — no substring search, no
storage of the text being compared.

Sampling is applied **identically on both sides** (registration and lookup):
a hash is kept when its low bits are zero. Symmetry is the whole point — any
scheme whose kept-set depends on the length of the text would fail to match a
passage against the larger document it was copied from.
"""
import hashlib
import re

#: Words per shingle. Long enough that shared idiom does not collide; short
#: enough that light editing still leaves matching windows either side.
SHINGLE_WORDS = 8

#: Texts shorter than this are not fingerprinted at all, on either side. Short
#: passages carry too little signal to attribute confidently, and attributing
#: them wrongly is the expensive error.
MIN_WORDS = 50

#: Keep ~1 hash in 4. Cuts storage without meaningfully hurting detection: a
#: copied paragraph still contributes many windows.
_SAMPLE_MASK = 0b11

#: Bound on hashes kept for one text. Only bites on texts beyond ~64k words.
MAX_HASHES = 2000

_WORD_RE = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    """Normalise to lowercase word tokens, discarding punctuation and layout.

    Whitespace, capitalisation and punctuation are exactly what differ between
    a generation and its paste, so none of them may contribute to the hash.
    """
    return _WORD_RE.findall((text or "").lower())


def _hash_window(words: list[str]) -> int:
    digest = hashlib.blake2b(" ".join(words).encode("utf-8"), digest_size=8).digest()
    # Signed so it fits a BigInteger column on both SQLite and Postgres.
    return int.from_bytes(digest, "big", signed=True)


def fingerprint(text: str) -> list[int]:
    """Return the sampled shingle hashes for ``text``, in order of appearance.

    Empty for anything shorter than :data:`MIN_WORDS` — callers treat that as
    "not fingerprintable", never as "no match".
    """
    words = _tokens(text)
    if len(words) < MIN_WORDS:
        return []

    kept: list[int] = []
    for i in range(len(words) - SHINGLE_WORDS + 1):
        h = _hash_window(words[i : i + SHINGLE_WORDS])
        if h & _SAMPLE_MASK == 0:
            kept.append(h)
            if len(kept) >= MAX_HASHES:
                break
    return kept


def overlap(hashes: list[int], known: set[int]) -> tuple[int, float]:
    """Score ``hashes`` against a set of known hashes.

    Returns ``(matched_count, matched_ratio)``. The ratio is over the candidate
    text's own hashes, so it answers "how much of this post is known AI output",
    not "how much of the AI output appears here" — a short quote inside a long
    original post scores low, which is the intent.
    """
    if not hashes:
        return 0, 0.0
    matched = sum(1 for h in hashes if h in known)
    return matched, matched / len(hashes)
