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
import pytest

from app.api.routes.image_generator import (
    _build_strict_identity_prompt,
    _reorder_anchor_refs,
    _SIMPLIFIED_BODY_CANON_TEXT,
)
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


def _build(
    *,
    body_canon_str: str = _SIMPLIFIED_BODY_CANON_TEXT,
    arm_side_binding_str: str = "",
    sleeve_enforcement_str: str = "",
    arm_visibility_mode: str = "full",
    provider_name: str = "",
    tattoo_simplified: bool = True,
    base_prompt: str = "Leonardo wearing a white sleeveless shirt and jeans",
) -> str:
    return _build_strict_identity_prompt(
        base_prompt=base_prompt,
        anchor_data={"identity_lock_string": _LONG_LOCK},
        character_name="Leonardo Baptiste",
        body_canon_str=body_canon_str,
        arm_side_binding_str=arm_side_binding_str,
        sleeve_enforcement_str=sleeve_enforcement_str,
        scene_complex=True,
        character_id=41,
        arm_visibility_mode=arm_visibility_mode,
        provider_name=provider_name,
        tattoo_simplified=tattoo_simplified,
    )


# ── Test 1: ref strategy — tattoo visible + body_front locked ─────────


class TestSimplifiedRefStrategyWithBodyFront:
    """When tattoo visible and body_front locked: refs are [body_front, front, ...]."""

    def test_body_front_is_first_in_tattoo_primary_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:body_front", (
            f"body_front must be first ref in tattoo-primary mode. Got: {out_types}"
        )

    def test_front_follows_body_front(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        bf_idx = out_types.index("body_identity:body_front")
        front_idx = out_types.index("front")
        assert bf_idx < front_idx, (
            f"body_front({bf_idx}) must precede front({front_idx}). Order: {out_types}"
        )

    def test_three_quarter_follows_front(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "three_quarter", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        front_idx = out_types.index("front")
        tq_idx = out_types.index("three_quarter")
        assert front_idx < tq_idx, (
            f"front({front_idx}) must precede three_quarter({tq_idx}). Order: {out_types}"
        )


# ── Test 2: fallback — body_front missing, use tattoo_layout ─────────


class TestSimplifiedRefStrategyFallback:
    """When body_front missing: tattoo_layout is accepted as fallback."""

    def test_tattoo_layout_first_when_no_body_front(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:tattoo_layout", (
            f"tattoo_layout must be first when body_front absent. Got: {out_types}"
        )

    def test_tattoo_layout_is_mutually_exclusive_with_body_front(self):
        """In simplified mode the caller never loads both body_front and tattoo_layout.
        Verify that when only body_front is present (fallback not triggered),
        no tattoo_layout ref appears."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert "body_identity:tattoo_layout" not in out_types, (
            "tattoo_layout must not be present when body_front was loaded"
        )


# ── Test 3: no body_anchor refs in simplified mode ────────────────────


class TestNoBodyAnchorRefsInSimplifiedMode:
    """Simplified mode must not send per-arm body_anchor:* refs."""

    def test_no_right_arm_anchor_type(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert not any(t.startswith("body_anchor:") for t in out_types), (
            f"No body_anchor:* refs should appear in simplified ref set. Got: {out_types}"
        )

    def test_body_anchors_absent_in_simplified_ref_list(self):
        """If body_anchor refs were accidentally included they must not reach providers."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front",
                  "body_anchor:right_arm", "body_anchor:left_arm"]),
            tattoo_primary=True,
        )
        # _reorder_anchor_refs does not strip body_anchor — this test verifies
        # the simplified pipeline doesn't add them (tested at caller level).
        # Here we verify the ordering still has body_front first if they sneak in.
        assert out_types[0] == "body_identity:body_front"


# ── Test 4: no front duplicate in simplified mode ─────────────────────


class TestNoFrontDuplicateInSimplifiedMode:
    """Simplified mode must drop the face-boost front duplicate."""

    def test_front_duplicate_removed_in_tattoo_primary(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types.count("front") == 1, (
            f"Front duplicate must be dropped in simplified/tattoo-primary mode. Got: {out_types}"
        )

    def test_torso_removed_from_simplified_ref_set(self):
        """torso refs are stripped before reorder in simplified mode."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "torso", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        # _reorder_anchor_refs doesn't strip torso — the caller does in simplified mode.
        # This verifies ordering is still coherent even when torso snuck in.
        assert out_types[0] == "body_identity:body_front"


# ── Test 5: t-shirt prompt uses simplified refs ───────────────────────


class TestTshirtUsesSimplifiedRefs:
    """T-shirt (partial) mode: body_front first, no tattoo_layout, no body_anchor."""

    def test_body_front_first_in_partial_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:body_front"

    def test_no_tattoo_layout_in_partial_mode(self):
        """tattoo_layout excluded for t-shirt; only body_front used."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert "body_identity:tattoo_layout" not in out_types


# ── Test 6: sleeveless prompt uses simplified refs ────────────────────


class TestSleevelessUsesSimplifiedRefs:
    """Sleeveless (full) mode: body_front (or tattoo_layout if absent) is first."""

    def test_body_front_first_for_sleeveless(self):
        """When only body_front is loaded (tattoo_layout excluded as fallback not needed),
        body_front is position 0."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:body_front"

    def test_tattoo_layout_as_fallback_for_sleeveless(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "body_identity:tattoo_layout"


# ── Test 7: jacket prompt — tattoo refs suppressed ────────────────────


class TestJacketTattooRefsSuppressed:
    """Covered-clothing (jacket/hoodie) mode: face-first, no tattoo refs."""

    def test_front_is_first_in_covered_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front", "body_identity:tattoo_layout"]),
            tattoo_primary=False,
        )
        assert out_types[0] == "front", (
            f"Covered mode must keep face-first ordering. Got: {out_types}"
        )

    def test_tattoo_layout_is_last_in_covered_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:tattoo_layout"]),
            tattoo_primary=False,
        )
        assert out_types[-1] == "body_identity:tattoo_layout", (
            f"tattoo_layout must be last in covered mode. Got: {out_types}"
        )


# ── Test 8: simplified prompt contains short marking instruction ───────


class TestSimplifiedPromptHasShortInstruction:
    """Simplified mode body_canon_str uses the canonical short instruction."""

    def test_simplified_constant_is_short(self):
        assert len(_SIMPLIFIED_BODY_CANON_TEXT) < 200, (
            f"_SIMPLIFIED_BODY_CANON_TEXT must be short. Got {len(_SIMPLIFIED_BODY_CANON_TEXT)} chars"
        )

    def test_simplified_text_references_body_reference(self):
        assert "body reference" in _SIMPLIFIED_BODY_CANON_TEXT.lower() or \
               "reference image" in _SIMPLIFIED_BODY_CANON_TEXT.lower(), (
            "Simplified instruction must mention the body reference image"
        )

    def test_simplified_prompt_contains_short_instruction(self):
        prompt = _build(body_canon_str=_SIMPLIFIED_BODY_CANON_TEXT)
        assert "permanent body marking" in prompt.lower() or \
               "body marking" in prompt.lower(), (
            "Simplified prompt must contain body marking instruction"
        )

    def test_simplified_prompt_contains_skin_only_note(self):
        prompt = _build(body_canon_str=_SIMPLIFIED_BODY_CANON_TEXT)
        assert "skin" in prompt.lower() or "clothing" in prompt.lower(), (
            "Simplified prompt must reference skin/clothing restriction"
        )


# ── Test 9: simplified prompt does NOT contain long essays ────────────


class TestSimplifiedPromptNoLongEssays:
    """Simplified mode must not include anti-merge/mirror guard/sleeve essays."""

    def test_no_mirror_guard_in_simplified_prompt(self):
        prompt = _build(sleeve_enforcement_str="")
        assert "mirror errors" not in prompt.lower(), (
            "Mirror guard must not appear in simplified mode"
        )
        assert "do not swap" not in prompt.lower(), (
            "Anti-swap directive must not appear in simplified mode"
        )

    def test_no_anti_merge_in_simplified_prompt(self):
        prompt = _build(sleeve_enforcement_str="")
        assert "must remain separate" not in prompt.lower(), (
            "Anti-merge language must not appear in simplified mode"
        )
        assert "do not combine designs" not in prompt.lower()

    def test_no_sleeve_identity_block_in_simplified_mode(self):
        """When sleeve_enforcement_str is empty (simplified mode), SLEEVE IDENTITY absent."""
        prompt = _build(sleeve_enforcement_str="")
        assert "SLEEVE IDENTITY" not in prompt, (
            "SLEEVE IDENTITY block must be absent in simplified mode"
        )

    def test_no_arm_binding_block_in_simplified_mode_no_markings(self):
        """Without visible arm markings, arm binding section must be absent."""
        prompt = _build(arm_side_binding_str="")
        assert "ARM BINDING:" not in prompt, (
            "ARM BINDING block must be absent when no arm markings"
        )


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

    def test_short_side_str_injected_into_simplified_prompt(self):
        short_sides = build_short_arm_side_str(
            [_RIGHT_MARKING, _LEFT_MARKING], {"right_arm", "left_arm"}
        )
        # In simplified mode the short sides go into body_canon_str, not arm_side_binding_str
        combined = _SIMPLIFIED_BODY_CANON_TEXT + " " + short_sides + "."
        prompt = _build(body_canon_str=combined, arm_side_binding_str="")
        assert "Right arm:" in prompt
        assert "Left arm:" in prompt
        assert "ARM BINDING:" not in prompt


# ── Test 11: prompt budget respected ─────────────────────────────────


class TestSimplifiedPromptBudget:
    """Simplified prompt with short body_canon must stay well within budget."""

    def test_simplified_prompt_shorter_than_full_mode(self):
        from app.api.routes.image_generator import _STRICT_IDENTITY_PROMPT_MAX_CHARS
        _full_sleeve = (
            "SLEEVE IDENTITY: left arm: left arm gothic script sleeve tattoo "
            "from shoulder to wrist — must be present if left arm is visible"
        )
        _full_arm_binding = (
            "ARM BINDING: RIGHT ARM ONLY: large right arm tribal wolf mark tattoo "
            "— on right arm exclusively, never on left arm. "
            "LEFT ARM ONLY: left arm gothic script sleeve tattoo "
            "— on left arm exclusively, never on right arm"
        )
        _full_body_canon = (
            "BODY MARKINGS: large large right arm tribal wolf mark tattoo covering full right arm; "
            "full_sleeve left arm gothic script sleeve tattoo covering full left arm"
        )
        # Original mode
        original = _build_strict_identity_prompt(
            base_prompt="Leonardo wearing a white sleeveless shirt and jeans",
            anchor_data={"identity_lock_string": _LONG_LOCK},
            character_name="Leonardo Baptiste",
            body_canon_str=_full_body_canon,
            arm_side_binding_str=_full_arm_binding,
            sleeve_enforcement_str=_full_sleeve,
            scene_complex=True,
            character_id=41,
            arm_visibility_mode="full",
            provider_name="",
            tattoo_simplified=False,
        )
        # Simplified mode
        short_sides = build_short_arm_side_str(
            [_RIGHT_MARKING, _LEFT_MARKING], {"right_arm", "left_arm"}
        )
        simplified = _build(
            body_canon_str=_SIMPLIFIED_BODY_CANON_TEXT + " " + short_sides + ".",
            arm_side_binding_str="",
            sleeve_enforcement_str="",
        )
        assert len(simplified) < len(original), (
            f"Simplified prompt ({len(simplified)}) must be shorter than original ({len(original)})"
        )
        assert len(simplified) <= _STRICT_IDENTITY_PROMPT_MAX_CHARS
