"""Visibility-aware marking partitioning (Task #18).

Body markings have FIXED anatomical locations. When a marking's region is covered
by clothing in the current scene, it must be listed under a HIDDEN block (never
rendered, relocated, or printed on fabric) rather than slipped onto nearby exposed
skin. Exposed regions are listed under a VISIBLE block.

These tests exercise the pure helpers added to image_generator.py:
  - _classify_marking_region(placement)
  - _classify_region_exposure(region, prompt_lower)
  - _partition_markings_by_visibility(markings, prompt_lower)
  - _build_partitioned_marking_blocks(visible, hidden)
"""
import pytest

from app.schemas.body_canon import BodyMarking
from app.api.routes.image_generator import (
    _classify_marking_region,
    _classify_region_exposure,
    _partition_markings_by_visibility,
    _build_partitioned_marking_blocks,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _mark(placement: str, style: str = "test design", size: str = "large") -> BodyMarking:
    return BodyMarking(
        type="tattoo",
        placement=placement,
        style=style,
        size=size,
        description=f"{style} {placement}",
    )


def _placements(markings) -> set[str]:
    return {getattr(m.placement, "value", str(m.placement)) for m in markings}


# ── Region classification ─────────────────────────────────────────────


class TestRegionClassification:
    def test_precise_arm_regions(self):
        assert _classify_marking_region("right_upper_arm") == "right_upper_arm"
        assert _classify_marking_region("left_forearm") == "left_forearm"

    def test_broad_arm_placements_map_to_broad_region(self):
        assert _classify_marking_region("right_arm") == "broad_right_arm"
        assert _classify_marking_region("right_full_arm") == "broad_right_arm"
        assert _classify_marking_region("left_arm") == "broad_left_arm"
        assert _classify_marking_region("left_full_arm") == "broad_left_arm"

    def test_torso_and_neck_regions(self):
        assert _classify_marking_region("chest") == "chest"
        assert _classify_marking_region("ribs") == "chest"
        assert _classify_marking_region("full_back") == "back"
        assert _classify_marking_region("neck") == "neck"


# ── Test 1: right_upper_arm hidden under rolled sleeves / button shirt ──


class TestUpperArmHiddenUnderCoveredGarments:
    def test_right_upper_arm_hidden_rolled_sleeves(self):
        assert _classify_region_exposure("right_upper_arm", "wearing a shirt with rolled sleeves") == "covered"

    def test_right_upper_arm_hidden_button_shirt(self):
        assert _classify_region_exposure("right_upper_arm", "wearing a button shirt at a bar") == "covered"

    def test_right_upper_arm_marking_partitions_to_hidden(self):
        markings = [_mark("right_upper_arm", style="grey wolf")]
        visible, hidden = _partition_markings_by_visibility(
            markings, "wearing a button shirt with rolled sleeves"
        )
        assert _placements(visible) == set()
        assert _placements(hidden) == {"right_upper_arm"}


# ── Test 2: right_upper_arm visible when sleeveless / tank ─────────────


class TestUpperArmVisibleWhenBare:
    def test_right_upper_arm_visible_sleeveless(self):
        assert _classify_region_exposure("right_upper_arm", "in a sleeveless top") == "exposed"

    def test_right_upper_arm_visible_tank_top(self):
        assert _classify_region_exposure("right_upper_arm", "wearing a tank top") == "exposed"

    def test_right_upper_arm_marking_partitions_to_visible(self):
        markings = [_mark("right_upper_arm", style="grey wolf")]
        visible, hidden = _partition_markings_by_visibility(markings, "wearing a tank top")
        assert _placements(visible) == {"right_upper_arm"}
        assert _placements(hidden) == set()


# ── Test 3: left_forearm visible when sleeves rolled ──────────────────


class TestForearmVisibleWhenRolled:
    def test_left_forearm_visible_rolled_sleeve(self):
        assert _classify_region_exposure("left_forearm", "shirt with rolled sleeve") == "exposed"

    def test_left_forearm_visible_t_shirt(self):
        assert _classify_region_exposure("left_forearm", "wearing a t-shirt") == "exposed"

    def test_left_forearm_hidden_button_shirt_no_roll(self):
        assert _classify_region_exposure("left_forearm", "wearing a plain button shirt") == "covered"

    def test_left_forearm_marking_partitions_to_visible(self):
        markings = [_mark("left_forearm", style="gothic script")]
        visible, hidden = _partition_markings_by_visibility(
            markings, "button shirt with sleeves rolled up"
        )
        assert _placements(visible) == {"left_forearm"}
        assert _placements(hidden) == set()


# ── Test 4: shoulder hidden under t-shirt ─────────────────────────────


class TestShoulderHiddenUnderTShirt:
    def test_shoulder_hidden_t_shirt(self):
        assert _classify_region_exposure("shoulder", "wearing a t-shirt") == "covered"

    def test_shoulder_hidden_blazer(self):
        assert _classify_region_exposure("shoulder", "wearing a blazer") == "covered"

    def test_shoulder_visible_shirtless(self):
        assert _classify_region_exposure("shoulder", "shirtless on the beach") == "exposed"


# ── Test 5: shirtless → all arm markings visible ──────────────────────


class TestShirtlessAllVisible:
    def test_all_arm_markings_visible_when_shirtless(self):
        markings = [
            _mark("right_upper_arm", style="wolf"),
            _mark("left_upper_arm", style="rose"),
            _mark("right_forearm", style="anchor"),
            _mark("left_forearm", style="script"),
        ]
        visible, hidden = _partition_markings_by_visibility(markings, "standing shirtless")
        assert len(visible) == 4
        assert hidden == []

    def test_upper_and_forearm_exposed_when_shirtless(self):
        assert _classify_region_exposure("right_upper_arm", "shirtless") == "exposed"
        assert _classify_region_exposure("left_forearm", "shirtless") == "exposed"


# ── Test 6: long sleeves → all arm markings hidden ────────────────────


class TestLongSleevesAllHidden:
    def test_all_arm_markings_hidden_long_sleeves(self):
        markings = [
            _mark("right_upper_arm", style="wolf"),
            _mark("left_forearm", style="script"),
        ]
        visible, hidden = _partition_markings_by_visibility(
            markings, "wearing a long sleeve shirt"
        )
        assert visible == []
        assert len(hidden) == 2

    def test_jacket_covers_arms(self):
        assert _classify_region_exposure("right_upper_arm", "wearing a jacket") == "covered"
        assert _classify_region_exposure("left_forearm", "wearing a jacket") == "covered"


# ── Test 7: hidden markings excluded from the VISIBLE block ───────────


class TestHiddenExcludedFromVisibleBlock:
    def test_hidden_marking_not_in_visible_block(self):
        # Leonardo bar scene: button shirt, sleeves rolled up.
        markings = [
            _mark("right_upper_arm", style="grey wolf head"),
            _mark("left_forearm", style="gothic script"),
        ]
        visible, hidden = _partition_markings_by_visibility(
            markings, "leonardo in a button shirt with rolled sleeves at a bar"
        )
        block = _build_partitioned_marking_blocks(visible, hidden)
        v_idx = block.index("VISIBLE BODY MARKINGS")
        h_idx = block.index("HIDDEN BODY MARKINGS")
        visible_section = block[v_idx:h_idx]
        # The wolf (hidden) must not appear in the VISIBLE section.
        assert "grey wolf head" not in visible_section
        assert "gothic script" in visible_section
        # Wolf appears only in the hidden section.
        assert "grey wolf head" in block[h_idx:]


# ── Test 8: prompt contains the literal relocation rule ───────────────


class TestRelocationRulePresent:
    def test_hidden_block_contains_do_not_relocate(self):
        markings = [_mark("right_upper_arm", style="wolf")]
        visible, hidden = _partition_markings_by_visibility(markings, "wearing a long sleeve shirt")
        block = _build_partitioned_marking_blocks(visible, hidden)
        assert "do not relocate hidden markings" in block.lower()

    def test_hidden_block_contains_render_and_print_rules(self):
        markings = [_mark("right_upper_arm", style="wolf")]
        visible, hidden = _partition_markings_by_visibility(markings, "wearing a jacket")
        block = _build_partitioned_marking_blocks(visible, hidden)
        lower = block.lower()
        assert "do not render hidden markings" in lower
        assert "do not print hidden markings" in lower


# ── Test 9: no markings → no blocks ───────────────────────────────────


class TestNoMarkingsNoBlocks:
    def test_empty_markings_produce_empty_block(self):
        visible, hidden = _partition_markings_by_visibility([], "wearing a t-shirt")
        assert visible == []
        assert hidden == []
        assert _build_partitioned_marking_blocks(visible, hidden) == ""

    def test_block_builder_empty_for_no_markings(self):
        assert _build_partitioned_marking_blocks([], []) == ""


# ── Test 10: broad "right arm" hidden unless full arm exposed ─────────


class TestBroadArmSafeFallback:
    def test_broad_full_arm_non_sleeve_hidden_t_shirt(self):
        # Non-sleeve broad-arm marking under a t-shirt: safe fallback keeps it hidden
        # because we cannot know which sub-region the mark occupies.
        markings = [_mark("right_full_arm", style="geometric tribal pattern", size="large")]
        visible, hidden = _partition_markings_by_visibility(markings, "wearing a t-shirt")
        assert _placements(visible) == set()
        assert _placements(hidden) == {"right_full_arm"}

    def test_broad_full_arm_non_sleeve_hidden_rolled(self):
        # Non-sleeve broad-arm marking under rolled sleeves: safe fallback → hidden.
        markings = [_mark("right_full_arm", style="geometric tribal pattern", size="large")]
        visible, hidden = _partition_markings_by_visibility(
            markings, "shirt with rolled sleeves"
        )
        assert _placements(visible) == set()
        assert _placements(hidden) == {"right_full_arm"}

    def test_broad_full_arm_visible_sleeveless(self):
        markings = [_mark("right_full_arm", style="full sleeve serpent")]
        visible, hidden = _partition_markings_by_visibility(markings, "in a sleeveless vest")
        assert _placements(visible) == {"right_full_arm"}
        assert _placements(hidden) == set()

    def test_broad_right_arm_visible_shirtless(self):
        assert _classify_region_exposure("broad_right_arm", "shirtless") == "exposed"

    def test_broad_right_arm_covered_long_sleeve(self):
        assert _classify_region_exposure("broad_right_arm", "long sleeve shirt") == "covered"

    # ── Sleeve exception ──────────────────────────────────────────────────
    # A full-sleeve tattoo definitively covers the forearm. Its forearm portion
    # IS visible when rolled sleeves or a t-shirt expose the forearm.

    def test_sleeve_marking_visible_under_rolled_sleeves(self):
        # left_full_arm gothic script sleeve — forearm exposed by rolled shirt.
        markings = [_mark("left_full_arm", style="gothic script sleeve tattoo",
                          size="full_sleeve")]
        visible, hidden = _partition_markings_by_visibility(
            markings, "button-up shirt with sleeves rolled to the forearms"
        )
        assert _placements(visible) == {"left_full_arm"}
        assert _placements(hidden) == set()

    def test_sleeve_marking_visible_under_t_shirt(self):
        # Full sleeve under a t-shirt: forearm portion is exposed → VISIBLE.
        markings = [_mark("right_full_arm", style="full sleeve serpent")]
        visible, hidden = _partition_markings_by_visibility(markings, "wearing a t-shirt")
        assert _placements(visible) == {"right_full_arm"}
        assert _placements(hidden) == set()

    def test_sleeve_marking_hidden_under_long_sleeve(self):
        # Full sleeve under a long-sleeve jacket: entire arm covered → HIDDEN.
        markings = [_mark("left_full_arm", style="gothic script sleeve tattoo",
                          size="full_sleeve")]
        visible, hidden = _partition_markings_by_visibility(
            markings, "wearing a long sleeve jacket"
        )
        assert _placements(visible) == set()
        assert _placements(hidden) == {"left_full_arm"}

    def test_non_sleeve_broad_arm_still_hidden_under_rolled(self):
        # Safety: a non-sleeve broad-arm marking (large wolf) stays hidden under
        # rolled sleeves — only the sleeve exception lifts the safe fallback.
        markings = [_mark("right_full_arm", style="tribal wolf mark", size="large")]
        visible, hidden = _partition_markings_by_visibility(
            markings, "dark button-up shirt with sleeves rolled to the forearms"
        )
        assert _placements(visible) == set()
        assert _placements(hidden) == {"right_full_arm"}


# ── Always-visible placements (neck/face/hands) ───────────────────────


class TestAlwaysVisiblePlacements:
    def test_neck_always_visible_even_with_jacket(self):
        markings = [_mark("neck", style="vine")]
        visible, hidden = _partition_markings_by_visibility(markings, "wearing a heavy jacket")
        assert _placements(visible) == {"neck"}
        assert hidden == []

    def test_hand_always_visible(self):
        markings = [_mark("right_hand", style="star")]
        visible, hidden = _partition_markings_by_visibility(markings, "wearing a long sleeve coat")
        assert _placements(visible) == {"right_hand"}


# ── Leonardo bar-shirt expected behaviour (Done-looks-like) ───────────


class TestLeonardoBarShirt:
    def test_leonardo_bar_partition(self):
        """Button shirt with rolled sleeves at a bar:
        VISIBLE left forearm gothic script; HIDDEN right upper-arm wolf."""
        markings = [
            _mark("right_upper_arm", style="grey wolf head"),
            _mark("left_forearm", style="gothic script"),
        ]
        visible, hidden = _partition_markings_by_visibility(
            markings, "leonardo in a button shirt with rolled sleeves at a bar"
        )
        assert _placements(visible) == {"left_forearm"}
        assert _placements(hidden) == {"right_upper_arm"}
