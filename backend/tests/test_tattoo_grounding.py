"""Regression tests for tattoo grounding fix (Task 9).

Root cause confirmed via runtime trace:
  1. body_anchor:* photos (real tattoo close-ups on Leo's arms) were filtered
     out by the tattoo_layout gate — only abstract design sheet was kept.
  2. body_front anchor was never loaded for "t-shirt" prompts because
     "t-shirt" was absent from _BODY_VISIBLE_SIGNALS.
  3. _prioritise_face_anchors prepended a front duplicate even when body
     anchors were present, diluting tattoo signal 4:1.

Fixes:
  - tattoo_layout no longer removes body_anchor:* entries (supplements them).
  - "t-shirt" and short-sleeve variants added to _BODY_VISIBLE_SIGNALS.
  - _reorder_anchor_refs discards the front duplicate when body anchors exist.
  - New canonical ordering: front → body_anchor:* → body_front → supporting
    → tattoo_layout.
"""
import pytest

from app.api.routes.image_generator import (
    _reorder_anchor_refs,
    _BODY_VISIBLE_SIGNALS,
    _detect_visible_body_regions,
)

# Minimal 1×1 PNG — content does not matter for ordering tests.
_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def _mk(types: list[str]) -> tuple[list[bytes], list[str]]:
    """Build (images, types) tuples from a list of type strings."""
    return [_STUB] * len(types), types


# ── Test 1: body_anchor refs survive the tattoo_layout gate ──────────


class TestBodyAnchorsNotFiltered:
    """body_anchor:* entries must reach the provider — they must not be removed."""

    def test_body_anchor_right_survives(self):
        imgs, types = _mk(["front", "body_anchor:bm_right", "body_identity:tattoo_layout"])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        assert "body_anchor:bm_right" in out_types, (
            "body_anchor:bm_right was filtered out — tattoo close-up photos must survive"
        )

    def test_body_anchor_left_survives(self):
        imgs, types = _mk(["front", "body_anchor:bm_left", "body_identity:tattoo_layout"])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        assert "body_anchor:bm_left" in out_types, (
            "body_anchor:bm_left was filtered out — tattoo close-up photos must survive"
        )

    def test_both_body_anchors_survive(self):
        imgs, types = _mk([
            "front",
            "body_anchor:bm_0ca124b8",
            "body_anchor:bm_c1849df9",
            "body_identity:tattoo_layout",
        ])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        assert "body_anchor:bm_0ca124b8" in out_types
        assert "body_anchor:bm_c1849df9" in out_types


# ── Test 2: tattoo_layout supplements rather than replaces ───────────


class TestTattooLayoutSupplements:
    """tattoo_layout must appear alongside body_anchor refs, not instead of them."""

    def test_tattoo_layout_present_with_body_anchors(self):
        imgs, types = _mk([
            "front",
            "body_anchor:bm_right",
            "body_anchor:bm_left",
            "body_identity:tattoo_layout",
        ])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        assert "body_identity:tattoo_layout" in out_types, "tattoo_layout must still be present"
        assert "body_anchor:bm_right" in out_types, "body_anchor:bm_right must also be present"
        assert "body_anchor:bm_left" in out_types, "body_anchor:bm_left must also be present"

    def test_tattoo_layout_last_when_body_anchors_present(self):
        imgs, types = _mk([
            "front",
            "body_anchor:bm_right",
            "body_identity:tattoo_layout",
        ])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        tl_idx = out_types.index("body_identity:tattoo_layout")
        ba_idx = out_types.index("body_anchor:bm_right")
        assert tl_idx > ba_idx, (
            "tattoo_layout must come AFTER body_anchor refs, not before"
        )


# ── Test 3: front duplicate removed when body anchors exist ──────────


class TestFrontDuplicateRemoved:
    """When body_anchor:* entries are present the front boost-duplicate must be dropped."""

    def test_no_duplicate_front_with_body_anchors(self):
        # Simulate input after _prioritise_face_anchors has run (front appears twice).
        imgs, types = _mk([
            "front",           # original
            "front",           # boost duplicate added by _prioritise_face_anchors
            "body_anchor:bm_right",
            "body_anchor:bm_left",
        ])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        assert out_types.count("front") == 1, (
            f"Expected 1 'front' entry but got {out_types.count('front')}: {out_types}"
        )

    def test_front_duplicate_kept_without_body_anchors(self):
        """When there are NO body anchors the front duplicate must be preserved (face-boost)."""
        imgs, types = _mk([
            "front",
            "front",   # boost duplicate
            "three_quarter",
        ])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        assert out_types.count("front") == 2, (
            "Without body anchors the face-boost duplicate must be kept"
        )


# ── Test 4: t-shirt prompt triggers body_visible ─────────────────────


class TestTshirtBodyVisible:
    """'t-shirt' and short-sleeve variants must be in _BODY_VISIBLE_SIGNALS."""

    @pytest.mark.parametrize("signal", [
        "t-shirt", "tshirt", "tee shirt", "tee-shirt",
        "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
    ])
    def test_signal_in_body_visible_signals(self, signal):
        assert signal in _BODY_VISIBLE_SIGNALS, (
            f"'{signal}' missing from _BODY_VISIBLE_SIGNALS — body_front won't load for this garment"
        )

    def test_tshirt_prompt_exposes_both_arms(self):
        vis = _detect_visible_body_regions(
            "leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts"
        )
        assert "right_arm" in vis
        assert "left_arm" in vis


# ── Test 5: canonical Leonardo ordering ──────────────────────────────


class TestCanonicalLeonardoOrdering:
    """Final ordered refs must follow: front → body_anchor:* → body_front → supporting → tattoo_layout."""

    def test_canonical_ordering(self):
        # Representative full payload (pre-cap) for Leonardo t-shirt prompt.
        imgs, types = _mk([
            "front",                          # face anchor
            "front",                          # boost duplicate (from _prioritise_face_anchors)
            "body_anchor:bm_0ca124b8",        # right-arm wolf tattoo photo
            "body_anchor:bm_c1849df9",        # left-arm gothic script photo
            "body_identity:body_front",       # full-body anatomical context
            "three_quarter",                  # supporting face angle
            "torso",                          # supporting body shot
            "body_identity:tattoo_layout",    # abstract design sheet
        ])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)

        # front appears exactly once (duplicate removed because body anchors exist)
        assert out_types[0] == "front"
        assert out_types.count("front") == 1

        # body_anchor entries come before body_front
        front_end = 1
        ba_indices = [i for i, t in enumerate(out_types) if t.startswith("body_anchor:")]
        bf_indices = [i for i, t in enumerate(out_types) if t == "body_identity:body_front"]
        tl_indices = [i for i, t in enumerate(out_types) if t == "body_identity:tattoo_layout"]

        assert ba_indices, "body_anchor:* entries missing from output"
        assert bf_indices, "body_identity:body_front missing from output"
        assert min(ba_indices) > front_end - 1, "body_anchor must follow front"
        assert min(bf_indices) > max(ba_indices), (
            "body_front must come after all body_anchor entries"
        )
        if tl_indices:
            assert min(tl_indices) > min(bf_indices), (
                "tattoo_layout must come after body_front"
            )

    def test_output_length_equals_input_minus_duplicate(self):
        imgs, types = _mk([
            "front", "front",
            "body_anchor:bm_right", "body_anchor:bm_left",
            "body_identity:body_front",
            "three_quarter", "torso",
            "body_identity:tattoo_layout",
        ])
        out_imgs, out_types = _reorder_anchor_refs(imgs, types)
        # 8 in, 1 duplicate removed = 7 out
        assert len(out_types) == 7, f"Expected 7, got {len(out_types)}: {out_types}"
        assert len(out_imgs) == len(out_types)
