"""Visibility-aware marking partitioning (Task #18) and body identity pack
as ground truth (Task #26).

Body markings have FIXED anatomical locations.

Task #18 helpers (kept intact — the Task #18 tests use them):
  - _classify_marking_region(placement)
  - _classify_region_exposure(region, prompt_lower)
  - _partition_markings_by_visibility(markings, prompt_lower)
  - _build_partitioned_marking_blocks(visible, hidden)

Task #26 helpers (always-on refs, permanent-features block):
  - _classify_marking_coverage(marking, prompt_lower)
  - _build_permanent_marking_block(markings, prompt_lower)
  - _build_arm_side_lock_str(exposed, covered)
"""
import pytest

from app.schemas.body_canon import BodyMarking
from app.api.routes.image_generator import (
    _classify_marking_region,
    _classify_region_exposure,
    _partition_markings_by_visibility,
    _build_partitioned_marking_blocks,
    _classify_marking_coverage,
    _build_permanent_marking_block,
    _build_arm_side_lock_str,
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


# ══════════════════════════════════════════════════════════════════════
# Task #26 — Body identity pack as ground truth (always-on refs)
# ══════════════════════════════════════════════════════════════════════
#
# New contract: body identity ref images are ALWAYS loaded — never
# withheld. The prompt uses a permanent-features block to tell the model
# which markings are exposed (reproduce from refs) and which are covered
# (one-line clothing note). No "DO NOT RENDER" block language.


_BAR_PROMPT = "leonardo in a dark button-up shirt with sleeves rolled to the forearms at a bar"


class TestCoverageClassifier:
    """_classify_marking_coverage returns 'exposed' or 'covered'."""

    def test_upper_arm_exposed_when_sleeveless(self):
        m = _mark("right_upper_arm", style="grey wolf")
        assert _classify_marking_coverage(m, "in a sleeveless top") == "exposed"

    def test_upper_arm_covered_under_rolled_sleeves(self):
        # Rolled sleeves only expose the forearm — upper arm stays covered.
        m = _mark("right_upper_arm", style="wolf", size="medium")
        assert _classify_marking_coverage(m, "button shirt with sleeves rolled up") == "covered"

    def test_forearm_exposed_under_rolled_sleeves(self):
        m = _mark("left_forearm", style="gothic script")
        assert _classify_marking_coverage(m, "button shirt with sleeves rolled up") == "exposed"

    def test_full_sleeve_exposed_via_sleeve_exception_rolled(self):
        # A full-sleeve tattoo's forearm portion IS exposed when sleeves are rolled.
        m = _mark("left_full_arm", style="gothic script sleeve", size="full_sleeve")
        assert _classify_marking_coverage(m, _BAR_PROMPT) == "exposed"

    def test_full_sleeve_covered_under_long_sleeve(self):
        m = _mark("left_full_arm", style="gothic script sleeve", size="full_sleeve")
        assert _classify_marking_coverage(m, "wearing a long sleeve coat") == "covered"

    def test_upper_arm_covered_under_long_sleeve(self):
        m = _mark("right_upper_arm", style="wolf")
        assert _classify_marking_coverage(m, "wearing a long sleeve coat") == "covered"

    def test_all_exposed_when_sleeveless(self):
        markings = [
            _mark("right_upper_arm", style="wolf"),
            _mark("left_full_arm", style="script sleeve", size="full_sleeve"),
        ]
        assert all(
            _classify_marking_coverage(m, "in a sleeveless tank top") == "exposed"
            for m in markings
        )

    def test_all_covered_under_long_sleeve(self):
        markings = [
            _mark("right_upper_arm", style="wolf"),
            _mark("left_forearm", style="script"),
        ]
        assert all(
            _classify_marking_coverage(m, "wearing a long sleeve coat") == "covered"
            for m in markings
        )

    def test_neck_always_exposed(self):
        m = _mark("neck", style="vine")
        assert _classify_marking_coverage(m, "wearing a heavy jacket") == "exposed"

    def test_wolf_covered_under_button_shirt_rolled(self):
        # Bar scene: wolf (right_upper_arm) is covered — shirt sleeve hides it.
        m = _mark("right_upper_arm", style="grey wolf head")
        assert _classify_marking_coverage(m, _BAR_PROMPT) == "covered"


class TestPermanentMarkingBlock:
    """_build_permanent_marking_block uses PERMANENT / COVERED sections."""

    def test_empty_returns_empty_string(self):
        assert _build_permanent_marking_block([], "anything") == ""

    def test_all_exposed_has_permanent_section_only(self):
        markings = [_mark("left_forearm", style="gothic script")]
        block = _build_permanent_marking_block(markings, "sleeveless top")
        assert "PERMANENT BODY MARKINGS" in block
        assert "COVERED BY CLOTHING" not in block
        assert "gothic script" in block

    def test_all_covered_has_covered_section_only(self):
        markings = [_mark("right_upper_arm", style="wolf")]
        block = _build_permanent_marking_block(markings, "long sleeve coat")
        assert "COVERED BY CLOTHING" in block
        assert "PERMANENT BODY MARKINGS" not in block
        assert "wolf" in block

    def test_mixed_has_both_sections(self):
        markings = [
            _mark("right_upper_arm", style="grey wolf head"),
            _mark("left_full_arm", style="gothic script sleeve", size="full_sleeve"),
        ]
        block = _build_permanent_marking_block(markings, _BAR_PROMPT)
        assert "PERMANENT BODY MARKINGS" in block
        assert "COVERED BY CLOTHING" in block

    def test_bar_scene_sleeve_in_permanent_wolf_in_covered(self):
        # Bar scene: sleeve (left_full_arm) is exposed at the forearm; wolf is covered.
        markings = [
            _mark("right_upper_arm", style="grey wolf head"),
            _mark("left_full_arm", style="gothic script sleeve", size="full_sleeve"),
        ]
        block = _build_permanent_marking_block(markings, _BAR_PROMPT)
        perm_idx = block.index("PERMANENT BODY MARKINGS")
        cov_idx = block.index("COVERED BY CLOTHING")
        # Sleeve appears in the PERMANENT section (before COVERED).
        sleeve_idx = block.index("gothic script sleeve")
        wolf_idx = block.index("grey wolf head")
        assert perm_idx < sleeve_idx < cov_idx
        assert wolf_idx > cov_idx

    def test_no_do_not_render_language(self):
        # Task #26 contract: no "DO NOT RENDER" / "Do not relocate" block language.
        markings = [
            _mark("right_upper_arm", style="wolf"),
            _mark("left_forearm", style="script"),
        ]
        block = _build_permanent_marking_block(markings, "long sleeve coat")
        lower = block.lower()
        assert "do not render" not in lower
        assert "do not relocate" not in lower

    def test_ref_match_instruction_for_exposed(self):
        markings = [_mark("left_forearm", style="gothic script")]
        block = _build_permanent_marking_block(markings, "sleeveless top")
        lower = block.lower()
        assert "reference images" in lower


class TestSideLock:
    """_build_arm_side_lock_str with exposed/covered markings."""

    def test_no_side_lock_when_nothing_exposed(self):
        assert _build_arm_side_lock_str([], [_mark("left_forearm", style="script")]) == ""

    def test_no_side_lock_when_both_arms_exposed(self):
        exposed = [_mark("left_upper_arm", style="rose"), _mark("right_upper_arm", style="wolf")]
        assert _build_arm_side_lock_str(exposed, []) == ""

    def test_side_lock_left_exposed_right_bare(self):
        exposed = [_mark("left_upper_arm", style="script")]
        out = _build_arm_side_lock_str(exposed, [])
        assert "left arm has visible tattoos" in out
        assert "right arm is bare skin" in out
        assert "No tattoos, writing, symbols, or marks on the right arm" in out

    def test_side_lock_right_exposed_left_bare(self):
        exposed = [_mark("right_full_arm", style="serpent", size="full_sleeve")]
        out = _build_arm_side_lock_str(exposed, [])
        assert "right arm has visible tattoos" in out
        assert "left arm is bare skin" in out

    def test_side_lock_ignores_non_arm_markings(self):
        assert _build_arm_side_lock_str([_mark("neck", style="vine")], []) == ""


class TestBarSceneAcceptance:
    """Acceptance test — bar scene (button-up, sleeves rolled).

    New contract (Task #26):
    - Refs always loaded (including body_front and body_right_detail).
    - Scripture sleeve (left_full_arm) → exposed → PERMANENT BODY MARKINGS.
    - Wolf (right_upper_arm) → covered → COVERED BY CLOTHING (one-line note only).
    - Side-lock declares left arm visible, right arm bare.
    - No ref exclusion, no 'DO NOT RENDER' language.
    """

    _MARKINGS = [
        lambda: _mark("right_upper_arm", style="grey wolf head"),
        lambda: _mark("left_full_arm", style="gothic script sleeve", size="full_sleeve"),
    ]

    def _markings(self):
        return [f() for f in self._MARKINGS]

    def test_sleeve_exposed_wolf_covered(self):
        markings = self._markings()
        assert _classify_marking_coverage(markings[0], _BAR_PROMPT) == "covered"  # wolf
        assert _classify_marking_coverage(markings[1], _BAR_PROMPT) == "exposed"  # sleeve

    def test_permanent_block_correct_sections(self):
        markings = self._markings()
        block = _build_permanent_marking_block(markings, _BAR_PROMPT)
        assert "PERMANENT BODY MARKINGS" in block
        assert "gothic script sleeve" in block
        assert "COVERED BY CLOTHING" in block
        assert "grey wolf head" in block

    def test_side_lock_left_visible_right_bare(self):
        markings = self._markings()
        exposed = [m for m in markings if _classify_marking_coverage(m, _BAR_PROMPT) == "exposed"]
        covered = [m for m in markings if _classify_marking_coverage(m, _BAR_PROMPT) == "covered"]
        lock = _build_arm_side_lock_str(exposed, covered)
        assert "left arm has visible tattoos" in lock
        assert "right arm is bare skin" in lock
        assert "No tattoos, writing, symbols, or marks on the right arm" in lock

    def test_no_do_not_render_in_block(self):
        markings = self._markings()
        block = _build_permanent_marking_block(markings, _BAR_PROMPT)
        lower = block.lower()
        assert "do not render" not in lower
        assert "do not relocate" not in lower
        assert "do not print" not in lower
