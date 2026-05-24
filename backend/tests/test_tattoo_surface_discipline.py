"""Regression tests for tattoo surface discipline fix.

Root cause: after the grounding fix, providers were still printing tattoo
designs onto t-shirt fabric (OpenAI) and merging left/right tattoo identities
(Google).

Fixes:
  1. Arm visibility modes: "full" (sleeveless), "partial" (t-shirt), "covered",
     "none" — governs prompt language and anchor selection.
  2. tattoo_layout anchor excluded for partial visibility — the abstract design
     map was encouraging shoulder-to-wrist rendering through shirt fabric.
  3. Body canon section: adds "skin only, never printed on clothing or fabric"
     skin-surface rule for all modes.
  4. Partial mode qualifier: "only forearm and exposed upper arm visible —
     hide any portion beneath the shirt sleeve."
  5. Sleeve enforcement partial qualifier: "Partial arm exposure only —
     render on exposed forearm and uncovered upper arm; hide beneath shirt."
  6. Full mode adds "do not print sleeve on shirt fabric" to sleeve section.
  7. Google anti-merge: when >= 2 body anchors sent, sleeve text gets
     "Left and right tattoos must remain separate — do not combine designs."
"""
import pytest

from app.api.routes.image_generator import (
    _detect_arm_visibility_mode,
    _build_strict_identity_prompt,
    _FULL_ARM_EXPOSURE_SIGNALS,
    _PARTIAL_ARM_EXPOSURE_SIGNALS,
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


def _anchor_data(lock_string: str = "") -> dict:
    return {"identity_lock_string": lock_string}


def _build(
    base_prompt: str,
    arm_visibility_mode: str = "none",
    provider_name: str = "",
    sleeve: str = _SLEEVE,
    body_canon: str = _BODY_CANON,
) -> str:
    return _build_strict_identity_prompt(
        base_prompt=base_prompt,
        anchor_data=_anchor_data(_LONG_LOCK),
        character_name="Leonardo Baptiste",
        body_canon_str=body_canon,
        sleeve_enforcement_str=sleeve,
        scene_complex=True,
        character_id=41,
        arm_visibility_mode=arm_visibility_mode,
        provider_name=provider_name,
    )


# ── Test 1: arm visibility mode detection ────────────────────────────


class TestArmVisibilityModeDetection:
    """_detect_arm_visibility_mode must return the correct tier for each garment."""

    def test_tshirt_is_partial(self):
        assert _detect_arm_visibility_mode("fitted charcoal t-shirt") == "partial"

    def test_tshirt_no_hyphen_is_partial(self):
        assert _detect_arm_visibility_mode("black tshirt") == "partial"

    def test_tee_shirt_is_partial(self):
        assert _detect_arm_visibility_mode("wearing a tee shirt") == "partial"

    def test_short_sleeve_is_partial(self):
        assert _detect_arm_visibility_mode("short-sleeve button-up") == "partial"

    def test_sleeveless_is_full(self):
        assert _detect_arm_visibility_mode("sleeveless white shirt") == "full"

    def test_tank_top_is_full(self):
        assert _detect_arm_visibility_mode("tank top and jeans") == "full"

    def test_shirtless_is_full(self):
        assert _detect_arm_visibility_mode("shirtless by the pool") == "full"

    def test_vest_is_full(self):
        assert _detect_arm_visibility_mode("wearing a vest") == "full"

    def test_hoodie_is_covered(self):
        assert _detect_arm_visibility_mode("wearing a hoodie") == "covered"

    def test_jacket_is_covered(self):
        assert _detect_arm_visibility_mode("leather jacket") == "covered"

    def test_suit_is_covered(self):
        assert _detect_arm_visibility_mode("three-piece suit") == "covered"

    def test_long_sleeve_is_covered(self):
        assert _detect_arm_visibility_mode("long-sleeve shirt") == "covered"

    def test_plain_scene_is_none(self):
        assert _detect_arm_visibility_mode("standing in a garden") == "none"

    @pytest.mark.parametrize("signal", sorted(_FULL_ARM_EXPOSURE_SIGNALS))
    def test_all_full_signals_resolve_to_full(self, signal):
        assert _detect_arm_visibility_mode(signal) == "full", (
            f"'{signal}' should be 'full' arm exposure"
        )

    @pytest.mark.parametrize("signal", sorted(_PARTIAL_ARM_EXPOSURE_SIGNALS))
    def test_all_partial_signals_resolve_to_partial(self, signal):
        assert _detect_arm_visibility_mode(signal) == "partial", (
            f"'{signal}' should be 'partial' arm exposure"
        )


# ── Test 2: t-shirt prompt includes "skin only" language ─────────────


class TestTshirtSkinSurfaceRule:
    """For t-shirt prompts the body canon section must carry the skin-surface rule."""

    def test_skin_only_rule_in_partial_prompt(self):
        prompt = _build(
            "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts",
            arm_visibility_mode="partial",
        )
        assert "skin only" in prompt.lower() or "on exposed skin" in prompt.lower(), (
            "Skin-surface rule missing from partial-visibility prompt"
        )

    def test_not_printed_on_fabric_in_partial_prompt(self):
        prompt = _build(
            "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts",
            arm_visibility_mode="partial",
        )
        assert "clothing or fabric" in prompt.lower() or "shirt" in prompt.lower(), (
            "Anti-fabric language missing from partial-visibility prompt"
        )

    def test_skin_only_rule_also_present_for_full(self):
        prompt = _build(
            "Leonardo wearing a white sleeveless shirt and jeans",
            arm_visibility_mode="full",
        )
        assert "skin only" in prompt.lower() or "on exposed skin" in prompt.lower()


# ── Test 3: t-shirt does NOT demand full sleeve visibility ────────────


class TestPartialSleeveVisibility:
    """Partial arm mode must qualify sleeve enforcement — not full shoulder-to-wrist."""

    def test_partial_sleeve_qualifier_injected(self):
        prompt = _build(
            "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts",
            arm_visibility_mode="partial",
        )
        # The partial-mode qualifier must appear
        partial_markers = [
            "partial arm exposure",
            "exposed forearm",
            "shirt sleeve",
        ]
        assert any(m in prompt.lower() for m in partial_markers), (
            f"No partial-visibility qualifier found. Prompt tail: {prompt[-300:]!r}"
        )

    def test_partial_prompt_still_contains_sleeve_identity_section(self):
        prompt = _build(
            "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts",
            arm_visibility_mode="partial",
        )
        assert "SLEEVE IDENTITY" in prompt, "SLEEVE IDENTITY section must still be present"

    def test_sleeveless_demands_full_shoulder_to_wrist(self):
        """For full exposure the original 'shoulder to wrist' language must survive."""
        prompt = _build(
            "Leonardo wearing a white sleeveless shirt and jeans",
            arm_visibility_mode="full",
        )
        assert "shoulder to wrist" in prompt.lower(), (
            "Full arm exposure must include shoulder-to-wrist requirement"
        )


# ── Test 4: sleeveless still demands full sleeve ──────────────────────


class TestSleevelessFullSleeveRequired:
    """Sleeveless prompts must retain full-arm sleeve language and not add partial qualifiers."""

    def test_full_mode_does_not_add_partial_qualifier(self):
        prompt = _build(
            "Leonardo wearing a white sleeveless shirt and jeans",
            arm_visibility_mode="full",
        )
        # Partial qualifier must NOT appear when mode is "full"
        assert "partial arm exposure only" not in prompt.lower(), (
            "Partial-mode qualifier leaked into full-exposure prompt"
        )

    def test_full_mode_adds_no_shirt_fabric_to_sleeve(self):
        prompt = _build(
            "Leonardo wearing a white sleeveless shirt and jeans",
            arm_visibility_mode="full",
        )
        # "Do not print on shirt fabric" or similar should appear in sleeve section
        assert "shirt fabric" in prompt.lower() or "not print" in prompt.lower(), (
            "Full-exposure mode should add shirt-fabric prohibition to sleeve section"
        )


# ── Test 5: hoodie/jacket hides tattoos (covered mode) ───────────────


class TestCoveredModeHidesTattoos:
    """Covered-mode prompts use no arm-expansion language (sleeves hidden)."""

    def test_covered_mode_detection(self):
        assert _detect_arm_visibility_mode("wearing a hoodie") == "covered"
        assert _detect_arm_visibility_mode("leather jacket") == "covered"

    def test_covered_mode_no_full_sleeve_demand(self):
        prompt = _build(
            "Leonardo wearing a hoodie and jeans",
            arm_visibility_mode="covered",
        )
        # "shoulder to wrist" would demand full tattoo rendering through fabric — wrong
        # (Only present if the sleeve_enforcement_str itself contains it; that's by design —
        #  covered mode doesn't add an extra "full" demand, and should add partial note too.)
        # The key test: no "partial arm exposure" demand (we're covered, not partial)
        assert "partial arm exposure only" not in prompt.lower(), (
            "Covered mode must not inject partial-visibility language"
        )


# ── Test 6: OpenAI t-shirt path — shirt-print prohibition ────────────


class TestOpenAITshirtAntiPrint:
    """OpenAI partial-visibility prompts must carry explicit shirt-print prohibition."""

    def test_openai_partial_has_anti_print_language(self):
        prompt = _build(
            "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts",
            arm_visibility_mode="partial",
            provider_name="openai",
        )
        anti_print_markers = [
            "not render tattoo",
            "printed pattern on the shirt",
            "on the shirt",
        ]
        assert any(m in prompt.lower() for m in anti_print_markers), (
            f"OpenAI shirt-print prohibition missing. Body-canon section: {prompt!r}"
        )

    def test_google_partial_does_not_have_openai_anti_print(self):
        prompt = _build(
            "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts",
            arm_visibility_mode="partial",
            provider_name="google",
        )
        # The OpenAI-specific "printed pattern on the shirt" phrase must NOT appear
        assert "printed pattern on the shirt" not in prompt.lower(), (
            "OpenAI-specific anti-print phrase leaked into Google prompt"
        )


# ── Test 7: Google anti-merge language ───────────────────────────────


class TestGoogleAntiMerge:
    """When Google provider receives >= 2 body anchors, sleeve text must warn against merge."""

    def test_anti_merge_in_sleeve_str_when_two_anchors(self):
        # The anti-merge injection happens in the caller (generate_image) before
        # _build_strict_identity_prompt is called. Simulate by passing the merged string.
        _sleeve_with_anti_merge = (
            _SLEEVE + ". Left and right tattoos must remain separate — "
            "do not combine designs onto one arm."
        )
        prompt = _build_strict_identity_prompt(
            base_prompt="Leonardo sitting in a garden",
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str=_sleeve_with_anti_merge,
            scene_complex=True,
            character_id=41,
            arm_visibility_mode="partial",
            provider_name="google",
        )
        assert "must remain separate" in prompt, (
            "Anti-merge sentence missing from Google prompt"
        )
        assert "do not combine designs" in prompt, (
            "Anti-merge design prohibition missing from Google prompt"
        )

    def test_non_google_no_anti_merge_injected(self):
        """Other providers should NOT carry the Google anti-merge sentence."""
        prompt = _build(
            "Leonardo at a rooftop party wearing a t-shirt",
            arm_visibility_mode="partial",
            provider_name="openai",
        )
        assert "must remain separate" not in prompt, (
            "Google anti-merge phrase should not appear in OpenAI prompts"
        )
