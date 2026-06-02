"""Tests for the closed-loop face verification gate (Phase 2)."""
from unittest.mock import patch

from app.schemas.canon import FaceCanonData
from app.services.face_verifier import passes


# ── passes() semantics ─────────────────────────────────────────────────

def test_passes_unverified_is_treated_as_pass():
    """An unevaluable verdict must never block generation."""
    assert passes({"ok": False, "skip_reason": "no_api_key"}, 0.6) is True


def test_passes_high_similarity_match():
    assert passes({"ok": True, "match": True, "similarity": 0.92}, 0.6) is True


def test_passes_below_threshold_fails():
    assert passes({"ok": True, "match": True, "similarity": 0.40}, 0.6) is False


def test_passes_not_same_person_fails():
    assert passes({"ok": True, "match": False, "similarity": 0.80}, 0.6) is False


# ── _verify_and_regenerate orchestration ───────────────────────────────

class _FakeProvider:
    supports_multi_image_input = True

    def __init__(self):
        self.calls = 0

    def generate_with_anchors(self, *, prompt, anchor_images, size="1024x1024"):
        self.calls += 1
        return b"retry-image-bytes"


def _canon_with_face():
    canon = object.__new__(type("C", (), {}))  # bare holder; load_face_canon is patched
    return canon


def test_regenerates_on_confident_mismatch_and_recovers():
    from app.api.routes import image_generator as ig

    provider = _FakeProvider()
    verdicts = iter([
        {"ok": True, "match": False, "similarity": 0.30},  # initial → mismatch
        {"ok": True, "match": True, "similarity": 0.88},   # retry → recovered
    ])
    with patch.object(ig, "load_face_canon",
                      return_value=FaceCanonData(face_front_image_url="/static/face.png")), \
         patch.object(ig, "load_image_bytes", return_value=b"ref-bytes"), \
         patch.object(ig, "verify_face_match", side_effect=lambda r, c: next(verdicts)):
        png, meta = ig._verify_and_regenerate(
            provider=provider,
            canon=_canon_with_face(),
            compiled_prompt="a scene",
            ref_bytes=[b"r1", b"r2"],
            provider_supports_multi=True,
            initial_png=b"initial-image-bytes",
            character_id=1,
        )
    assert png == b"retry-image-bytes"
    assert meta["face_verify_result"] == "recovered"
    assert provider.calls == 1


def test_keeps_initial_when_verification_passes():
    from app.api.routes import image_generator as ig

    provider = _FakeProvider()
    with patch.object(ig, "load_face_canon",
                      return_value=FaceCanonData(face_front_image_url="/static/face.png")), \
         patch.object(ig, "load_image_bytes", return_value=b"ref-bytes"), \
         patch.object(ig, "verify_face_match",
                      return_value={"ok": True, "match": True, "similarity": 0.91}):
        png, meta = ig._verify_and_regenerate(
            provider=provider,
            canon=_canon_with_face(),
            compiled_prompt="a scene",
            ref_bytes=[b"r1"],
            provider_supports_multi=True,
            initial_png=b"initial-image-bytes",
            character_id=1,
        )
    assert png == b"initial-image-bytes"
    assert meta["face_verify_result"] == "passed"
    assert provider.calls == 0  # no retry needed


def test_skips_cleanly_when_no_face_ref():
    from app.api.routes import image_generator as ig

    with patch.object(ig, "load_face_canon", return_value=FaceCanonData()):
        png, meta = ig._verify_and_regenerate(
            provider=_FakeProvider(),
            canon=_canon_with_face(),
            compiled_prompt="a scene",
            ref_bytes=[],
            provider_supports_multi=False,
            initial_png=b"initial-image-bytes",
            character_id=1,
        )
    assert png == b"initial-image-bytes"
    assert meta["face_verify_skipped"] == "no_face_ref"
