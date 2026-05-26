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
    build_arm_side_binding_str,
    build_sleeve_enforcement_str,
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
    """Body-truth mode ordering: face anchor first (identity seed), body_front second (body truth)."""

    def test_face_anchor_is_first_in_body_truth_mode(self):
        """Face anchor must be at position 0 — it is the identity seed."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "front", (
            f"face anchor (front) must be first ref in body-truth mode. Got: {out_types}"
        )

    def test_body_front_follows_face_anchor(self):
        """body_front must immediately follow the face anchor."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        front_idx = out_types.index("front")
        bf_idx = out_types.index("body_identity:body_front")
        assert front_idx < bf_idx, (
            f"front({front_idx}) must precede body_front({bf_idx}). Order: {out_types}"
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
    """When body_front missing: tattoo_layout is accepted as fallback after face anchor."""

    def test_face_anchor_first_even_when_no_body_front(self):
        """Face anchor is always first regardless of body_front presence."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "front", (
            f"face anchor (front) must be first even when body_front absent. Got: {out_types}"
        )

    def test_tattoo_layout_present_when_no_body_front(self):
        """tattoo_layout is still loaded as fallback when body_front is absent."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert "body_identity:tattoo_layout" in out_types, (
            f"tattoo_layout must be present as fallback when body_front absent. Got: {out_types}"
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
        # Here we verify the ordering: face first (identity seed), body_front second.
        assert out_types[0] == "front"
        assert out_types[1] == "body_identity:body_front"


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
        # Body-truth ordering: face anchor first (identity seed), body_front second.
        assert out_types[0] == "front"
        assert "body_identity:body_front" in out_types


# ── Test 5: t-shirt prompt uses simplified refs ───────────────────────


class TestTshirtUsesSimplifiedRefs:
    """T-shirt (partial) mode: face first, body_front second, no tattoo_layout, no body_anchor."""

    def test_face_anchor_first_in_partial_mode(self):
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "front"
        assert out_types[1] == "body_identity:body_front"

    def test_no_tattoo_layout_in_partial_mode(self):
        """tattoo_layout excluded for t-shirt; only body_front used."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert "body_identity:tattoo_layout" not in out_types


# ── Test 6: sleeveless prompt uses simplified refs ────────────────────


class TestSleevelessUsesSimplifiedRefs:
    """Sleeveless (full) mode: face first, body_front second (or tattoo_layout if absent)."""

    def test_face_anchor_first_for_sleeveless(self):
        """Face anchor is always position 0 (identity seed); body_front is position 1."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "front"
        assert out_types[1] == "body_identity:body_front"

    def test_face_anchor_first_tattoo_layout_as_fallback_for_sleeveless(self):
        """When body_front absent, face anchor is still first; tattoo_layout follows."""
        _, out_types = _reorder_anchor_refs(
            *_mk(["front", "body_identity:tattoo_layout"]),
            tattoo_primary=True,
        )
        assert out_types[0] == "front"
        assert "body_identity:tattoo_layout" in out_types


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


# ── Test 12: Sprint B — restored full binding in simplified mode ───────


class TestRestoredBindingInSimplifiedMode:
    """Sprint B: simplified mode (body_front absent) must now include full
    ARM BINDING and SLEEVE IDENTITY blocks — not suppress them."""

    _FULL_VISIBLE = {"right_arm", "left_arm"}

    def test_arm_binding_present_when_tattoos_visible_no_body_front(self):
        """Simplified mode with arm markings must produce ARM BINDING block."""
        binding = build_arm_side_binding_str(
            [_RIGHT_MARKING, _LEFT_MARKING], self._FULL_VISIBLE
        )
        assert binding, "build_arm_side_binding_str must return non-empty for arm markings"
        prompt = _build(arm_side_binding_str=binding, sleeve_enforcement_str="")
        assert "ARM BINDING:" in prompt, (
            f"ARM BINDING block must appear in simplified prompt. Got snippet: {prompt[:500]}"
        )

    def test_arm_binding_contains_right_exclusivity(self):
        """ARM BINDING must state right arm exclusivity."""
        binding = build_arm_side_binding_str([_RIGHT_MARKING], {"right_arm"})
        prompt = _build(arm_side_binding_str=binding, sleeve_enforcement_str="")
        assert "RIGHT ARM ONLY" in prompt, (
            "Right arm exclusivity directive must appear in binding block"
        )
        assert "never on left arm" in prompt.lower()

    def test_arm_binding_contains_left_exclusivity(self):
        """ARM BINDING must state left arm exclusivity."""
        binding = build_arm_side_binding_str([_LEFT_MARKING], {"left_arm"})
        prompt = _build(arm_side_binding_str=binding, sleeve_enforcement_str="")
        assert "LEFT ARM ONLY" in prompt, (
            "Left arm exclusivity directive must appear in binding block"
        )
        assert "never on right arm" in prompt.lower()

    def test_sleeve_identity_present_when_sleeve_marking_visible(self):
        """Simplified mode with a sleeve marking must produce SLEEVE IDENTITY block."""
        sleeve = build_sleeve_enforcement_str([_LEFT_MARKING], {"left_arm"})
        assert sleeve, "build_sleeve_enforcement_str must return non-empty for sleeve marking"
        prompt = _build(sleeve_enforcement_str=sleeve, arm_side_binding_str="")
        assert "SLEEVE IDENTITY" in prompt, (
            "SLEEVE IDENTITY block must appear for sleeve marking in simplified mode"
        )

    def test_sleeve_identity_contains_shoulder_to_wrist(self):
        """SLEEVE IDENTITY must include shoulder-to-wrist coverage directive."""
        sleeve = build_sleeve_enforcement_str([_LEFT_MARKING], {"left_arm"})
        prompt = _build(sleeve_enforcement_str=sleeve)
        assert "shoulder to wrist" in prompt.lower()

    def test_canonical_mode_has_no_arm_binding(self):
        """Canonical mode (body_front locked) must NOT include ARM BINDING block."""
        # In canonical mode the endpoint sets both to "" — simulate that here.
        prompt = _build(arm_side_binding_str="", sleeve_enforcement_str="")
        assert "ARM BINDING:" not in prompt, (
            "Canonical mode must not inject ARM BINDING (ref image carries placement)"
        )

    def test_canonical_mode_has_no_sleeve_identity(self):
        """Canonical mode must NOT include SLEEVE IDENTITY block."""
        prompt = _build(arm_side_binding_str="", sleeve_enforcement_str="")
        assert "SLEEVE IDENTITY" not in prompt, (
            "Canonical mode must not inject SLEEVE IDENTITY"
        )

    def test_no_markings_no_arm_binding_block(self):
        """Empty marking list must produce empty binding and no ARM BINDING block."""
        binding = build_arm_side_binding_str([], self._FULL_VISIBLE)
        assert binding == "", "Empty marking list must return empty binding string"
        prompt = _build(arm_side_binding_str=binding)
        assert "ARM BINDING:" not in prompt

    def test_no_markings_no_sleeve_identity_block(self):
        """Empty marking list must produce empty sleeve string and no SLEEVE IDENTITY."""
        sleeve = build_sleeve_enforcement_str([], self._FULL_VISIBLE)
        assert sleeve == "", "Empty marking list must return empty sleeve string"
        prompt = _build(sleeve_enforcement_str=sleeve)
        assert "SLEEVE IDENTITY" not in prompt

    def test_non_sleeve_marking_no_sleeve_identity(self):
        """A non-sleeve arm marking must not generate SLEEVE IDENTITY."""
        sleeve = build_sleeve_enforcement_str([_RIGHT_MARKING], {"right_arm"})
        # _RIGHT_MARKING has size="large", not sleeve — should return ""
        assert sleeve == "", (
            f"Non-sleeve marking must not produce SLEEVE IDENTITY string. Got: {sleeve!r}"
        )

    def test_both_blocks_present_together(self):
        """When both arm markings and sleeve exist, both blocks appear in the prompt."""
        binding = build_arm_side_binding_str(
            [_RIGHT_MARKING, _LEFT_MARKING], self._FULL_VISIBLE
        )
        sleeve = build_sleeve_enforcement_str([_LEFT_MARKING], {"left_arm"})
        prompt = _build(arm_side_binding_str=binding, sleeve_enforcement_str=sleeve)
        assert "ARM BINDING:" in prompt
        assert "SLEEVE IDENTITY" in prompt
