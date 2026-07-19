"""Regression tests for tattoo anatomical side binding fix.

Root cause: body canon was grounding tattoos visually but providers still
swapped left/right arm assignments. The side-binding signal in the prompt
was implicit (buried in body_canon_str prose) and the anchor ordering did
not distinguish right from left.

Fixes:
  1. build_arm_side_binding_str() → dedicated "ARM BINDING" block with
     explicit "RIGHT ARM ONLY: ... — never on left arm" /
     "LEFT ARM ONLY: ... — never on right arm" statements.
  2. body_anchor type labels changed from opaque ID to semantic region:
     body_anchor:{_bm_region}  e.g. "body_anchor:right_arm", "body_anchor:left_arm"
  3. _reorder_anchor_refs sorts body_anchor bucket: right_arm first, left_arm second,
     matching the ARM BINDING text block order for cross-channel alignment.
  4. Mirror guard: "Mirror errors are incorrect. Do not swap left and right arm tattoos."
     prepended to sleeve enforcement when tattoo_layout is used.
  5. _build_strict_identity_prompt gains arm_side_binding_str parameter, injected
     as a dedicated section between body_canon and sleeve.
"""

from app.services.body_canon import (
    build_arm_side_binding_str,
    BodyMarking,
)

# ── Shared fixtures ───────────────────────────────────────────────────

_LONG_LOCK = (
    "Blonde hair, Blue eyes, Fair skin, Facial hair, angular face, "
    "square jaw, broad nose, balanced lips, tall stature, athletic build, "
    "defined shoulders, balanced physique"
)
_BODY_CANON = (
    "BODY MARKINGS: large right arm tribal wolf mark tattoo covering full right arm; "
    "full sleeve left arm gothic script sleeve tattoo covering full left arm"
)
_SLEEVE = (
    "SLEEVE IDENTITY: left arm: left arm gothic script sleeve tattoo "
    "from shoulder to wrist — must be present if left arm is visible"
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


# ── Test 1: right arm text includes "never on left arm" ───────────────


class TestRightArmBinding:
    """Right-arm markings must carry explicit left-arm exclusion."""

    def test_right_arm_binding_str_contains_never_on_left(self):
        result = build_arm_side_binding_str(
            [_RIGHT_MARKING], {"right_arm"}
        )
        assert "never on left arm" in result.lower(), (
            f"Right arm binding must forbid left arm. Got: {result!r}"
        )

    def test_right_arm_binding_str_format(self):
        result = build_arm_side_binding_str(
            [_RIGHT_MARKING], {"right_arm"}
        )
        assert result.startswith("ARM BINDING:"), (
            f"ARM BINDING header missing. Got: {result!r}"
        )
        assert "RIGHT ARM ONLY" in result

    def test_right_arm_style_present_in_binding(self):
        result = build_arm_side_binding_str(
            [_RIGHT_MARKING], {"right_arm"}
        )
        assert "tribal wolf" in result.lower(), (
            "Right arm marking style must appear in binding text"
        )

    def test_right_arm_not_included_when_right_arm_not_visible(self):
        result = build_arm_side_binding_str(
            [_RIGHT_MARKING], {"left_arm"}  # only left arm visible
        )
        assert "RIGHT ARM ONLY" not in result


# ── Test 2: left arm text includes "never on right arm" ───────────────


class TestLeftArmBinding:
    """Left-arm markings must carry explicit right-arm exclusion."""

    def test_left_arm_binding_str_contains_never_on_right(self):
        result = build_arm_side_binding_str(
            [_LEFT_MARKING], {"left_arm"}
        )
        assert "never on right arm" in result.lower(), (
            f"Left arm binding must forbid right arm. Got: {result!r}"
        )

    def test_left_arm_binding_str_format(self):
        result = build_arm_side_binding_str(
            [_LEFT_MARKING], {"left_arm"}
        )
        assert "LEFT ARM ONLY" in result

    def test_left_arm_style_present_in_binding(self):
        result = build_arm_side_binding_str(
            [_LEFT_MARKING], {"left_arm"}
        )
        assert "gothic script" in result.lower()

    def test_left_arm_not_included_when_left_arm_not_visible(self):
        result = build_arm_side_binding_str(
            [_LEFT_MARKING], {"right_arm"}  # only right arm visible
        )
        assert "LEFT ARM ONLY" not in result


# ── Test 3: tattoo_layout mirror guard ────────────────────────────────


# ── Test 4: body anchor ordering — right before left ──────────────────


# ── Test 5: canonical Leonardo prompt includes left/right blocks ───────


class TestLeonardoCanonicalBinding:
    """The canonical Leonardo t-shirt prompt must contain both binding blocks."""


    def test_neck_marking_not_in_arm_binding(self):
        """Non-arm markings (neck) must not generate ARM BINDING entries."""
        arm_binding = build_arm_side_binding_str(
            [_NECK_MARKING], {"right_arm", "left_arm"}
        )
        # Neck has no arm side, so binding should be empty
        assert arm_binding == "", (
            "Neck markings must not generate arm side binding text"
        )

    def test_empty_visible_regions_produces_empty_binding(self):
        arm_binding = build_arm_side_binding_str(
            [_RIGHT_MARKING, _LEFT_MARKING], set()  # no visible regions
        )
        assert arm_binding == ""

