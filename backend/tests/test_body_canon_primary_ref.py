"""Regression tests for body-canon primary reference fix.

Root cause: even with correct body anchors and prompt language, the provider
was still merging tattoos because face anchors were in position 0, making the
face portrait the dominant conditioning signal.

Correct principle:
  When tattoos/body markings are visible, the body-canon reference (tattoo_layout
  or body_front) must be the primary (first) visual reference so the provider
  grounds placement from the body card before conditioning on the face.

Fix:
  _reorder_anchor_refs gains a `tattoo_primary: bool = False` parameter.
  When tattoo_primary=True, ordering becomes:
    tattoo_layout → body_front → front (no dup) → three_quarter → body_anchor → other → torso

  When tattoo_primary=False (default, face-only scenes), ordering is unchanged:
    front → body_anchor → body_front → three_quarter → torso → other → tattoo_layout

  For OpenAI: images.edit uses the first image as the edit base — highest weight.
  For Google: earlier images receive higher attention weight.
  Both providers now receive body-canon as position 0 in tattoo-visible mode.
"""
import pytest

from app.api.routes.image_generator import _reorder_anchor_refs

_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def _mk(types: list[str]) -> tuple[list[bytes], list[str]]:
    return [_STUB] * len(types), types


# ── Test 1: tattoo visible → first ref is tattoo_layout or body_front ─


class TestTattooPrimaryFirstRef:
    """In tattoo_primary mode the first ref must be tattoo_layout or body_front."""

    def test_tattoo_layout_is_first_when_present(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front", "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:tattoo_layout", (
            f"Expected tattoo_layout at position 0, got: {out_types}"
        )

    def test_body_front_is_first_when_no_tattoo_layout(self):
        """When no tattoo_layout is loaded (partial/none mode), body_front must be first."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:body_front", (
            f"Expected body_front at position 0, got: {out_types}"
        )

    def test_face_first_mode_still_has_front_at_position_zero(self):
        """Face-first mode (tattoo_primary=False) must not change front position."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_anchor:bm_right", "body_identity:tattoo_layout"]),
            tattoo_primary=False,
        )
        assert out_types[0] == "front", (
            f"Face-first mode must still put 'front' at position 0, got: {out_types}"
        )


# ── Test 2: tattoo visible → front duplicate removed ──────────────────


class TestTattooPrimaryNoDuplicate:
    """Tattoo-primary mode must always drop the face-boost duplicate."""

    def test_front_duplicate_dropped_in_tattoo_primary(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front", "body_anchor:bm_right", "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types.count("front") == 1, (
            f"Tattoo-primary mode must drop front duplicate. Got: {out_types}"
        )

    def test_front_duplicate_dropped_even_without_body_anchors(self):
        """In tattoo_primary mode, front dup is ALWAYS dropped (no body-anchor exception)."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types.count("front") == 1, (
            "Front duplicate must be dropped in tattoo_primary mode "
            "regardless of whether body_anchor:* entries are present"
        )

    def test_front_duplicate_kept_in_face_first_mode_without_body_anchors(self):
        """Face-first mode without body anchors must still boost via front dup."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front", "three_quarter"]),
            tattoo_primary=False,
        )
        assert out_types.count("front") == 2, (
            "Face-first mode with no body anchors must keep the face-boost duplicate"
        )


# ── Test 3: t-shirt prompt → body refs before face refs ───────────────


class TestTshirtBodyRefOrder:
    """For t-shirt scenes (partial, no tattoo_layout), body_front must precede front."""

    def test_body_front_before_front_in_tshirt_mode(self):
        # t-shirt: tattoo_layout excluded (partial), body_front loaded
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front"]),
            tattoo_primary=True,
        )
        bf_idx = out_types.index("body_identity:body_front")
        front_idx = out_types.index("front")
        assert bf_idx < front_idx, (
            f"body_front ({bf_idx}) must precede front ({front_idx}) "
            f"in tattoo-primary mode. Order: {out_types}"
        )

    def test_body_anchors_present_after_face_in_tshirt_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front"]),
            tattoo_primary=True,
        )
        front_idx = out_types.index("front")
        ba_indices = [i for i, t in enumerate(out_types) if t.startswith("body_anchor:")]
        assert all(i > front_idx for i in ba_indices), (
            "body_anchor:* entries must come after front in tattoo-primary order. "
            f"front={front_idx}, body_anchor indices={ba_indices}"
        )


# ── Test 4: sleeveless prompt → body-first ordering ───────────────────


class TestSleevelessBodyFirstOrder:
    """For sleeveless scenes (full exposure), tattoo_layout must be first ref."""

    def test_tattoo_layout_first_for_sleeveless(self):
        # Sleeveless: tattoo_layout loaded, full arm exposure
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front",                      # front + boost dup from _prioritise_face_anchors
                  "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front",
                  "three_quarter", "torso",
                  "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:tattoo_layout", (
            f"tattoo_layout must be position 0 for sleeveless scene. Order: {out_types}"
        )

    def test_sleeveless_body_front_before_face_anchor(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front",
                  "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front",
                  "three_quarter", "torso",
                  "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        bf_idx = out_types.index("body_identity:body_front")
        front_idx = out_types.index("front")
        tl_idx = out_types.index("body_identity:tattoo_layout")
        assert tl_idx < bf_idx < front_idx, (
            f"Expected tattoo_layout({tl_idx}) < body_front({bf_idx}) < front({front_idx}). "
            f"Order: {out_types}"
        )

    def test_sleeveless_no_front_duplicate(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front",
                  "body_identity:tattoo_layout",
                  "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types.count("front") == 1


# ── Test 5: covered jacket → face-first ordering unchanged ────────────


class TestCoveredFaceFirstUnchanged:
    """When tattoo_primary=False (covered clothing, no tattoo visibility),
    face-first ordering must be completely unchanged."""

    def test_front_is_first_in_face_first_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "three_quarter", "torso"]),
            tattoo_primary=False,
        )
        assert out_types[0] == "front"

    def test_tattoo_layout_is_last_in_face_first_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_anchor:bm_right", "body_identity:tattoo_layout"]),
            tattoo_primary=False,
        )
        assert out_types[-1] == "body_identity:tattoo_layout", (
            f"tattoo_layout must be last in face-first mode. Order: {out_types}"
        )

    def test_face_first_body_anchor_before_body_front(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_anchor:bm_right", "body_identity:body_front",
                  "body_identity:tattoo_layout"]),
            tattoo_primary=False,
        )
        ba_idx = out_types.index("body_anchor:bm_right")
        bf_idx = out_types.index("body_identity:body_front")
        tl_idx = out_types.index("body_identity:tattoo_layout")
        assert ba_idx < bf_idx < tl_idx, (
            f"Face-first: body_anchor({ba_idx}) < body_front({bf_idx}) < tattoo_layout({tl_idx}). "
            f"Order: {out_types}"
        )


# ── Test 6: OpenAI payload — first image is body/tattoo ref ───────────


class TestOpenAIPayloadFirstImage:
    """OpenAI images.edit treats position 0 as the edit base (strongest signal).
    In tattoo-visible mode the first image in the list MUST be body-canon."""

    def test_openai_first_image_is_tattoo_layout(self):
        """Simulate the full t-shirt payload with tattoo_layout (full arm mode)."""
        out_imgs, out_types = _reorder_anchor_refs(
            *_mk(["front", "front",
                  "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front",
                  "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types[0] in {"body_identity:tattoo_layout", "body_identity:body_front"}, (
            f"First image sent to OpenAI must be body-canon reference. "
            f"Got position-0: {out_types[0]!r}. Full order: {out_types}"
        )
        # Verify the images list aligns with types list
        assert len(out_imgs) == len(out_types)

    def test_openai_first_image_is_body_front_when_no_tattoo_layout(self):
        """Partial mode (t-shirt): no tattoo_layout loaded, body_front must be first."""
        out_imgs, out_types = _reorder_anchor_refs(
            *_mk(["front", "front",
                  "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:body_front", (
            f"Without tattoo_layout, body_front must be position 0. Order: {out_types}"
        )


# ── Test 7: Google payload — body-first order ─────────────────────────


class TestGooglePayloadOrder:
    """Google inlineData parts: earlier images receive higher attention weight.
    Body-canon must precede face anchors in tattoo-visible mode."""

    def test_google_body_refs_before_face_refs(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front",
                  "body_anchor:bm_right", "body_anchor:bm_left",
                  "body_identity:body_front",
                  "three_quarter",
                  "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        body_ref_indices = [
            i for i, t in enumerate(out_types)
            if t in {"body_identity:tattoo_layout", "body_identity:body_front"}
        ]
        face_ref_indices = [
            i for i, t in enumerate(out_types)
            if t in {"front", "three_quarter"}
        ]
        assert body_ref_indices, "No body refs in output"
        assert face_ref_indices, "No face refs in output"
        assert min(body_ref_indices) < min(face_ref_indices), (
            f"Body refs ({body_ref_indices}) must precede face refs ({face_ref_indices}). "
            f"Order: {out_types}"
        )

    def test_google_canonical_leonardo_sleeveless_order(self):
        """Full canonical ordering for Leo sleeveless prompt after all pipeline stages."""
        # Simulate: front boosted to [front, front], then body anchors, body_front,
        # three_quarter, torso, tattoo_layout added.
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front",
                  "body_anchor:bm_0ca124b8",
                  "body_anchor:bm_c1849df9",
                  "body_identity:body_front",
                  "three_quarter",
                  "torso",
                  "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        # tattoo_layout first
        assert out_types[0] == "body_identity:tattoo_layout"
        # body_front second
        assert out_types[1] == "body_identity:body_front"
        # front third (single — dup dropped)
        assert out_types[2] == "front"
        assert out_types.count("front") == 1
        # three_quarter fourth
        assert out_types[3] == "three_quarter"
        # body_anchors follow
        ba_start = 4
        assert out_types[ba_start].startswith("body_anchor:")
        assert out_types[ba_start + 1].startswith("body_anchor:")
        # torso last (lowest priority in tattoo mode)
        assert out_types[-1] == "torso"
