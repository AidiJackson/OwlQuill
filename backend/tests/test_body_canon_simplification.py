"""Regression tests for Body Canon Conditioning Simplification v1.

Hypothesis: A single coherent body-identity image (body_front) is a stronger
conditioning signal than fragmented per-arm close-ups + long text essays.

Simplified ref strategy (when tattoo_visibility_requested=True):
  Primary:  body_front (if locked)
  Fallback: tattoo_layout (only when body_front missing)
  Skip:     body_anchor:*, torso, front duplicate, tattoo_layout when body_front exists

Simplified text (when tattoo_visibility_requested=True):
  Short canonical instruction + compact per-arm side note (Right arm: X. Left arm: Y.)
  No sleeve enforcement essay, no mirror guard, no anti-merge essay.
"""

from app.services.body_canon import (
    build_short_arm_side_str,
    BodyMarking,
)

# ── Shared fixtures ───────────────────────────────────────────────────

_LONG_LOCK = (
    "Blonde hair, Blue eyes, Fair skin, Facial hair, angular face, "
    "square jaw, broad nose, balanced lips, tall stature, athletic build, "
    "defined shoulders, balanced physique"
)

_RIGHT_MARKING = BodyMarking(
    id="bm_right",
    type="tattoo",
    placement="right_full_arm",
    style="large right arm tribal wolf mark tattoo",
    size="large",
    description="tribal wolf sleeve on right arm",
)
_LEFT_MARKING = BodyMarking(
    id="bm_left",
    type="tattoo",
    placement="left_full_arm",
    style="left arm gothic script sleeve tattoo",
    size="full_sleeve",
    description="gothic script sleeve on left arm",
)
_NECK_MARKING = BodyMarking(
    id="bm_neck",
    type="tattoo",
    placement="neck",
    style="small cross tattoo",
    size="small",
    description="cross tattoo on neck",
)

_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def _mk(types: list[str]) -> tuple[list[bytes], list[str]]:
    return [_STUB] * len(types), types


# ── Test 1: ref strategy — tattoo visible + body_front locked ─────────


# ── Test 2: fallback — body_front missing, use tattoo_layout ─────────


# ── Test 3: no body_anchor refs in simplified mode ────────────────────


# ── Test 4: no front duplicate in simplified mode ─────────────────────


# ── Test 5: t-shirt prompt uses simplified refs ───────────────────────


# ── Test 6: sleeveless prompt uses simplified refs ────────────────────


# ── Test 7: jacket prompt — tattoo refs suppressed ────────────────────


# ── Test 8: simplified prompt contains short marking instruction ───────


# ── Test 9: simplified prompt does NOT contain long essays ────────────


# ── Test 10: short arm side str format ───────────────────────────────


class TestBuildShortArmSideStr:
    """build_short_arm_side_str must produce compact 'Right arm: X. Left arm: Y.' format."""

    def test_right_arm_format(self):
        result = build_short_arm_side_str([_RIGHT_MARKING], {"right_arm"})
        assert result.startswith("Right arm:"), f"Expected 'Right arm: ...' Got: {result!r}"
        assert "tribal wolf" in result.lower()

    def test_left_arm_format(self):
        result = build_short_arm_side_str([_LEFT_MARKING], {"left_arm"})
        assert result.startswith("Left arm:"), f"Expected 'Left arm: ...' Got: {result!r}"
        assert "gothic script" in result.lower()

    def test_both_arms_right_before_left(self):
        result = build_short_arm_side_str(
            [_RIGHT_MARKING, _LEFT_MARKING], {"right_arm", "left_arm"}
        )
        right_pos = result.find("Right arm:")
        left_pos = result.find("Left arm:")
        assert right_pos < left_pos, (
            f"Right arm must precede left arm in short binding. Got: {result!r}"
        )

    def test_no_arm_keywords_for_non_arm_marking(self):
        result = build_short_arm_side_str([_NECK_MARKING], {"right_arm", "left_arm"})
        assert result == "", (
            f"Non-arm marking must produce empty short binding. Got: {result!r}"
        )

    def test_right_arm_hidden_produces_empty(self):
        result = build_short_arm_side_str([_RIGHT_MARKING], set())
        assert result == ""


# ── Test 11: prompt budget respected ─────────────────────────────────


# ── Test 12: Sprint B — restored full binding in simplified mode ───────


