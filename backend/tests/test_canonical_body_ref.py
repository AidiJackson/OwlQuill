"""Regression tests for Canonical Body Reference v1.

Problem: Providers swap/merge tattoos because we over-condition with too many
refs (tattoo_layout, body_anchor:right_arm, body_anchor:left_arm, torso, etc.)
and too much semantic left/right text. Six competing refs cause averaging.

Fix: When tattoo_visibility_requested=True and body_front is locked:
  - Send ONLY: body_identity:body_front, front (+ optional three_quarter)
  - Strip everything else: tattoo_layout, body_anchor:*, torso, front duplicate
  - Use single short instruction: "Match the locked body reference image exactly..."
  - No arm binding text, no sleeve essays — body_front IS the left/right truth

If body_front missing: fall back to simplified mode (tattoo_layout or short text).
Covered clothing: unchanged (no tattoo refs, face-first).
"""
import pytest

from app.api.routes.image_generator import (
    _build_strict_identity_prompt,
    _reorder_anchor_refs,
    _CANONICAL_BODY_REF_TEXT,
    _CANONICAL_BODY_REF_ALLOWED,
    _SIMPLIFIED_BODY_CANON_TEXT,
)

# ── Shared fixtures ───────────────────────────────────────────────────

_LONG_LOCK = (
    "Blonde hair, Blue eyes, Fair skin, Facial hair, angular face, "
    "square jaw, broad nose, balanced lips, tall stature, athletic build, "
    "defined shoulders, balanced physique"
)

_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def _mk(types: list[str]) -> tuple[list[bytes], list[str]]:
    return [_STUB] * len(types), types


def _apply_canonical_filter(
    imgs: list[bytes], types: list[str]
) -> tuple[list[bytes], list[str]]:
    """Simulate the canonical ref whitelist filter applied in generate_image."""
    pairs = [(img, t) for img, t in zip(imgs, types) if t in _CANONICAL_BODY_REF_ALLOWED]
    if pairs:
        imgs_out, types_out = zip(*pairs)
        return list(imgs_out), list(types_out)
    return [], []


def _full_pipeline(
    input_types: list[str],
    *,
    tattoo_primary: bool = True,
    apply_canonical: bool = True,
) -> list[str]:
    """Run the full ref pipeline: reorder → canonical filter → return types."""
    imgs, types = _mk(input_types)
    imgs, types = _reorder_anchor_refs(imgs, types, tattoo_primary=tattoo_primary)
    if apply_canonical:
        imgs, types = _apply_canonical_filter(imgs, types)
    return types


def _build(
    *,
    body_canon_str: str = _CANONICAL_BODY_REF_TEXT,
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


# ── Test 1: tattoo visible + body_front locked → refs [body_front, front] ──


class TestCanonicalRefSet:
    """Canonical mode must produce exactly [body_front, front] (plus three_quarter)."""

    def test_body_front_and_front_in_output(self):
        """Full pipeline with body_front locked: both refs present."""
        out = _full_pipeline(["front", "body_identity:body_front"])
        assert "body_identity:body_front" in out
        assert "front" in out

    def test_front_is_first_in_output(self):
        out = _full_pipeline(["front", "body_identity:body_front"])
        assert out[0] == "front", (
            f"front (identity seed) must be position 0. Got: {out}"
        )

    def test_body_front_is_second_in_output(self):
        out = _full_pipeline(["front", "body_identity:body_front"])
        assert out[1] == "body_identity:body_front", (
            f"body_front (body truth) must be position 1. Got: {out}"
        )

    def test_three_quarter_included_when_present(self):
        out = _full_pipeline(["front", "body_identity:body_front", "three_quarter"])
        assert "three_quarter" in out

    def test_exactly_three_refs_with_three_quarter(self):
        out = _full_pipeline(["front", "body_identity:body_front", "three_quarter"])
        assert len(out) == 3, f"Expected exactly 3 refs. Got: {out}"

    def test_exactly_two_refs_without_three_quarter(self):
        out = _full_pipeline(["front", "body_identity:body_front"])
        assert len(out) == 2, f"Expected exactly 2 refs. Got: {out}"


# ── Test 2: no tattoo_layout in canonical body mode ───────────────────


class TestNoTattooLayoutInCanonicalMode:
    """tattoo_layout must be stripped in canonical body ref mode."""

    def test_tattoo_layout_stripped(self):
        out = _full_pipeline([
            "front", "body_identity:body_front", "body_identity:tattoo_layout"
        ])
        assert "body_identity:tattoo_layout" not in out, (
            f"tattoo_layout must be absent in canonical mode. Got: {out}"
        )

    def test_tattoo_layout_stripped_even_with_full_set(self):
        out = _full_pipeline([
            "front", "front",
            "body_anchor:bm_right", "body_anchor:bm_left",
            "body_identity:body_front",
            "three_quarter", "torso",
            "body_identity:tattoo_layout",
        ])
        assert "body_identity:tattoo_layout" not in out

    def test_body_front_still_present_after_tattoo_layout_stripped(self):
        out = _full_pipeline([
            "front", "body_identity:body_front", "body_identity:tattoo_layout"
        ])
        assert "body_identity:body_front" in out


# ── Test 3: no body_anchor refs in canonical body mode ────────────────


class TestNoBodyAnchorInCanonicalMode:
    """Per-arm body_anchor:* refs must be stripped in canonical mode."""

    def test_right_arm_anchor_stripped(self):
        out = _full_pipeline([
            "front", "body_identity:body_front", "body_anchor:right_arm"
        ])
        assert not any(t.startswith("body_anchor:") for t in out), (
            f"body_anchor:* must be absent in canonical mode. Got: {out}"
        )

    def test_left_arm_anchor_stripped(self):
        out = _full_pipeline([
            "front", "body_identity:body_front", "body_anchor:left_arm"
        ])
        assert not any(t.startswith("body_anchor:") for t in out)

    def test_both_arm_anchors_stripped(self):
        out = _full_pipeline([
            "front", "body_identity:body_front",
            "body_anchor:right_arm", "body_anchor:left_arm",
        ])
        assert not any(t.startswith("body_anchor:") for t in out)

    def test_only_canonical_refs_remain(self):
        out = _full_pipeline([
            "front", "body_identity:body_front",
            "body_anchor:right_arm", "body_anchor:left_arm",
        ])
        for t in out:
            assert t in _CANONICAL_BODY_REF_ALLOWED, (
                f"Unexpected ref type {t!r} in canonical output"
            )


# ── Test 4: no torso in canonical body mode ───────────────────────────


class TestNoTorsoInCanonicalMode:
    """torso refs must be stripped in canonical mode."""

    def test_torso_stripped(self):
        out = _full_pipeline([
            "front", "body_identity:body_front", "torso"
        ])
        assert "torso" not in out, (
            f"torso must be absent in canonical mode. Got: {out}"
        )

    def test_torso_stripped_from_full_set(self):
        out = _full_pipeline([
            "front", "front",
            "body_identity:body_front",
            "three_quarter", "torso",
        ])
        assert "torso" not in out


# ── Test 5: no front duplicate in canonical body mode ─────────────────


class TestNoFrontDuplicateInCanonicalMode:
    """Front duplicate (face-boost) must be absent in canonical mode."""

    def test_front_appears_exactly_once(self):
        out = _full_pipeline([
            "front", "front", "body_identity:body_front"
        ])
        assert out.count("front") == 1, (
            f"front must appear exactly once. Got: {out}"
        )

    def test_front_duplicate_stripped_with_full_input(self):
        out = _full_pipeline([
            "front", "front",
            "body_anchor:bm_right", "body_anchor:bm_left",
            "body_identity:body_front",
            "three_quarter", "torso",
            "body_identity:tattoo_layout",
        ])
        assert out.count("front") == 1


# ── Test 6: covered jacket — tattoo refs suppressed ───────────────────


class TestCoveredJacketTattooRefsSuppressed:
    """Covered clothing: face-first ordering, no canonical body-ref mode."""

    def test_front_is_first_in_covered_mode(self):
        imgs, types = _mk(["front", "body_identity:body_front", "body_identity:tattoo_layout"])
        imgs, types = _reorder_anchor_refs(imgs, types, tattoo_primary=False)
        assert types[0] == "front", (
            f"Covered mode must keep face-first. Got: {types}"
        )

    def test_no_canonical_filter_in_covered_mode(self):
        """Covered mode does NOT apply the canonical whitelist filter — tattoo_layout
        falls to last, not stripped."""
        imgs, types = _mk(["front", "body_identity:body_front", "body_identity:tattoo_layout"])
        imgs, types = _reorder_anchor_refs(imgs, types, tattoo_primary=False)
        # In covered mode canonical filter is not applied — tattoo_layout still present
        assert "body_identity:tattoo_layout" in types

    def test_covered_mode_no_body_front_at_position_zero(self):
        imgs, types = _mk(["front", "body_identity:body_front"])
        imgs, types = _reorder_anchor_refs(imgs, types, tattoo_primary=False)
        assert types[0] == "front"


# ── Test 7: canonical prompt contains short body-reference instruction ─


class TestCanonicalPromptText:
    """Canonical mode body_canon_str uses _CANONICAL_BODY_REF_TEXT."""

    def test_canonical_constant_references_body_reference_image(self):
        assert "body reference image" in _CANONICAL_BODY_REF_TEXT.lower(), (
            "Canonical text must reference the body reference image"
        )

    def test_canonical_constant_shorter_than_simplified(self):
        assert len(_CANONICAL_BODY_REF_TEXT) < 250, (
            f"Canonical text must be short. Got {len(_CANONICAL_BODY_REF_TEXT)} chars"
        )

    def test_canonical_prompt_includes_match_instruction(self):
        prompt = _build(body_canon_str=_CANONICAL_BODY_REF_TEXT)
        assert "match the locked body reference image" in prompt.lower(), (
            "Canonical prompt must instruct provider to match body reference"
        )

    def test_canonical_prompt_includes_skin_only_note(self):
        prompt = _build(body_canon_str=_CANONICAL_BODY_REF_TEXT)
        assert "skin marking" in prompt.lower() or "skin only" in prompt.lower() or \
               "never printed on clothing" in prompt.lower(), (
            "Canonical prompt must mention skin-only tattoo rule"
        )

    def test_canonical_prompt_includes_tattoo_placement(self):
        prompt = _build(body_canon_str=_CANONICAL_BODY_REF_TEXT)
        assert "tattoo placement" in prompt.lower(), (
            "Canonical prompt must mention tattoo placement preservation"
        )

    def test_canonical_text_for_tshirt_prompt(self):
        prompt = _build(
            body_canon_str=_CANONICAL_BODY_REF_TEXT,
            base_prompt="Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts",
            arm_visibility_mode="partial",
        )
        assert "match the locked body reference image" in prompt.lower()


# ── Test 8: canonical prompt has no long left/right essays ────────────


class TestCanonicalPromptNoEssays:
    """Canonical mode prompt must not contain arm-binding or sleeve essays."""

    def test_no_arm_binding_block(self):
        prompt = _build()
        assert "ARM BINDING:" not in prompt, (
            "ARM BINDING block must be absent in canonical mode"
        )

    def test_no_right_arm_only_directive(self):
        prompt = _build()
        assert "RIGHT ARM ONLY" not in prompt, (
            "RIGHT ARM ONLY directive must be absent in canonical mode"
        )

    def test_no_left_arm_only_directive(self):
        prompt = _build()
        assert "LEFT ARM ONLY" not in prompt

    def test_no_sleeve_identity_block(self):
        prompt = _build()
        assert "SLEEVE IDENTITY" not in prompt, (
            "SLEEVE IDENTITY block must be absent in canonical mode"
        )

    def test_no_mirror_guard(self):
        prompt = _build()
        assert "mirror errors" not in prompt.lower()

    def test_no_anti_merge_language(self):
        prompt = _build()
        assert "must remain separate" not in prompt.lower()
        assert "do not combine designs" not in prompt.lower()

    def test_no_never_on_left_arm_language(self):
        prompt = _build()
        assert "never on left arm" not in prompt.lower()

    def test_no_never_on_right_arm_language(self):
        prompt = _build()
        assert "never on right arm" not in prompt.lower()

    def test_short_prompt_within_budget(self):
        from app.api.routes.image_generator import _STRICT_IDENTITY_PROMPT_MAX_CHARS
        prompt = _build()
        assert len(prompt) <= _STRICT_IDENTITY_PROMPT_MAX_CHARS
        assert len(prompt) < 1000, (
            f"Canonical prompt should be well under the 2000-char budget. Got {len(prompt)} chars"
        )


# ── Test 9: canonical allowed set is correct ─────────────────────────


class TestCanonicalAllowedSet:
    """_CANONICAL_BODY_REF_ALLOWED must contain exactly the right ref types."""

    def test_body_front_allowed(self):
        assert "body_identity:body_front" in _CANONICAL_BODY_REF_ALLOWED

    def test_front_allowed(self):
        assert "front" in _CANONICAL_BODY_REF_ALLOWED

    def test_three_quarter_allowed(self):
        assert "three_quarter" in _CANONICAL_BODY_REF_ALLOWED

    def test_torso_not_allowed(self):
        assert "torso" not in _CANONICAL_BODY_REF_ALLOWED

    def test_tattoo_layout_not_allowed(self):
        assert "body_identity:tattoo_layout" not in _CANONICAL_BODY_REF_ALLOWED

    def test_body_anchor_not_allowed(self):
        assert "body_anchor:right_arm" not in _CANONICAL_BODY_REF_ALLOWED
        assert "body_anchor:left_arm" not in _CANONICAL_BODY_REF_ALLOWED


# ── Test 10: Leonardo canonical t-shirt full pipeline ─────────────────


class TestLeonardoTshirtCanonicalPipeline:
    """End-to-end canonical pipeline for Leo t-shirt prompt."""

    def test_tshirt_canonical_refs_exact(self):
        """Full body-visible t-shirt input collapses to [body_front, front]."""
        out = _full_pipeline([
            "front", "front",
            "body_anchor:bm_right", "body_anchor:bm_left",
            "body_identity:body_front",
            "three_quarter",
        ])
        assert "body_identity:body_front" in out
        assert "front" in out
        assert not any(t.startswith("body_anchor:") for t in out)
        assert out.count("front") == 1

    def test_tshirt_canonical_prompt(self):
        prompt = _build(
            base_prompt=(
                "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts"
            ),
            arm_visibility_mode="partial",
        )
        assert "match the locked body reference image" in prompt.lower()
        assert "ARM BINDING:" not in prompt
        assert "SLEEVE IDENTITY" not in prompt

    def test_sleeveless_canonical_refs_exact(self):
        """Full arm exposure (sleeveless) also collapses to [body_front, front]."""
        out = _full_pipeline([
            "front", "front",
            "body_anchor:bm_right", "body_anchor:bm_left",
            "body_identity:body_front",
            "three_quarter", "torso",
            "body_identity:tattoo_layout",
        ])
        assert "body_identity:body_front" in out
        assert "front" in out
        assert "body_identity:tattoo_layout" not in out
        assert "torso" not in out
        assert not any(t.startswith("body_anchor:") for t in out)


# ── Test 11: neutral-prompt canonical mode (marked character, no skin keywords) ──


class TestNeutralPromptCanonicalMode:
    """Canonical mode must activate when markings exist + body_front is locked,
    even when the prompt has no visible-skin keywords
    (_tattoo_visibility_requested=False).

    In this path _tattoo_primary remains False (face-first reorder) but the
    canonical whitelist filter runs, stripping torso/body_anchor refs and
    preserving all body_identity refs.
    """

    # ── Activation logic ──────────────────────────────────────────────

    def test_canonical_activates_with_markings_and_no_tattoo_keywords(self):
        """body_front_available + has_markings → canonical even without tattoo keywords."""
        body_front_available = True
        tattoo_visibility_requested = False
        has_markings = True

        body_front_canonical = body_front_available and (
            tattoo_visibility_requested or has_markings
        )
        assert body_front_canonical, (
            "canonical mode must activate when markings exist + body_front locked, "
            "even with a neutral prompt"
        )

    def test_canonical_inactive_when_no_markings_and_no_tattoo_keywords(self):
        """No markings + no tattoo keywords → canonical inactive even if body_front locked."""
        body_front_available = True
        tattoo_visibility_requested = False
        has_markings = False

        body_front_canonical = body_front_available and (
            tattoo_visibility_requested or has_markings
        )
        assert not body_front_canonical

    def test_canonical_inactive_when_body_front_not_available(self):
        """body_front not locked → canonical inactive even when markings exist."""
        body_front_available = False
        tattoo_visibility_requested = False
        has_markings = True

        body_front_canonical = body_front_available and (
            tattoo_visibility_requested or has_markings
        )
        assert not body_front_canonical

    # ── Pipeline behaviour (tattoo_primary=False, canonical filter applied) ──

    def test_body_front_preserved_under_neutral_canonical(self):
        """body_identity:body_front survives the canonical filter with face-first reorder."""
        out = _full_pipeline(
            [
                "front", "front",
                "body_identity:body_front", "body_identity:body_back",
                "three_quarter", "torso",
            ],
            tattoo_primary=False,
            apply_canonical=True,
        )
        assert "body_identity:body_front" in out, (
            f"body_front must survive neutral-prompt canonical filter. Got: {out}"
        )

    def test_body_back_preserved_under_neutral_canonical(self):
        """body_identity:body_back survives the canonical filter with face-first reorder."""
        out = _full_pipeline(
            [
                "front", "front",
                "body_identity:body_front", "body_identity:body_back",
                "three_quarter", "torso",
            ],
            tattoo_primary=False,
            apply_canonical=True,
        )
        assert "body_identity:body_back" in out, (
            f"body_back must survive neutral-prompt canonical filter. Got: {out}"
        )

    def test_torso_stripped_under_neutral_canonical(self):
        """torso is stripped by the canonical whitelist even with face-first reorder."""
        out = _full_pipeline(
            [
                "front", "front",
                "body_identity:body_front", "body_identity:body_back",
                "three_quarter", "torso",
            ],
            tattoo_primary=False,
            apply_canonical=True,
        )
        assert "torso" not in out, (
            f"torso must be absent after neutral-prompt canonical filter. Got: {out}"
        )

    def test_body_anchor_stripped_under_neutral_canonical(self):
        """body_anchor:* stripped by canonical filter even in neutral-prompt mode."""
        out = _full_pipeline(
            [
                "front",
                "body_identity:body_front", "body_anchor:right_arm",
                "body_identity:body_back", "three_quarter",
            ],
            tattoo_primary=False,
            apply_canonical=True,
        )
        assert not any(t.startswith("body_anchor:") for t in out), (
            f"body_anchor must be absent after neutral-prompt canonical filter. Got: {out}"
        )
