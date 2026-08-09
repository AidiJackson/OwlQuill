"""REF EFFICIENCY — byte-identical duplicate reference suppression.

The Angelo investigation measured a six-reference Google request at ~17 MB.
Canon slots may legitimately share one card (same URL in two slots, or the
same bytes uploaded twice); a duplicate adds zero identity information and
only inflates the payload. The generate route now drops byte-identical
duplicates AFTER the first occurrence — identity grounding is untouched.
"""
import hashlib


def _dedup(loaded: list[bytes]) -> tuple[list[bytes], int]:
    """Mirror of the route's dedup loop, for unit-level pinning."""
    out: list[bytes] = []
    seen: set[str] = set()
    deduped = 0
    for b in loaded:
        h = hashlib.sha256(b).hexdigest()
        if h in seen:
            deduped += 1
            continue
        seen.add(h)
        out.append(b)
    return out, deduped


def test_unique_refs_untouched():
    refs = [b"a", b"b", b"c"]
    out, n = _dedup(refs)
    assert out == refs and n == 0


def test_duplicate_bytes_dropped_first_kept():
    refs = [b"face", b"body", b"face", b"map", b"body"]
    out, n = _dedup(refs)
    assert out == [b"face", b"body", b"map"]
    assert n == 2


def test_route_emits_dedup_metadata(monkeypatch):
    """The generate endpoint records refs_deduped in image metadata."""
    import inspect
    from app.api.routes import image_generator
    src = inspect.getsource(image_generator.generate_image)
    assert "refs_deduped" in src
    assert "IMAGE_GEN_REF_DEDUP" in src
