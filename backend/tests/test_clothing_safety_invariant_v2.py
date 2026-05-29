"""Clothing safety invariant v2 — hard scene-generation rules for body markings.

Covers the four required invariant tests:
  1. Prompt includes skin-only / hide-if-covered rule when markings exist.
  2. Prompt forbids clothing graphics, logos, and decorative text (unless requested).
  3. Body markings + t-shirt prompt do not instruct visible tattoo on covered area.
  4. No markings → no clothing safety invariant injected.

Root issue that prompted these tests:
  Wolf tattoo rendered as a printed graphic ON the T-shirt sleeve/fabric (Leonardo,
  pink T-shirt). The invariant lacked an explicit "hide if covered" clause and
  any prohibition on clothing graphics / printed wolf designs.
"""
import pytest

from app.api.routes.image_generator import (
    _CLOTHING_SAFETY_INVARIANT,
    _build_strict_identity_prompt,
)
from app.services.body_canon import BodyMarking, build_body_canon_lock_string


# ── Shared helpers ────────────────────────────────────────────────────────────


def _wolf_marking() -> BodyMarking:
    return BodyMarking(
        type="tattoo",
        placement="right_upper_arm",
        style="wolf graphic",
        size="large",
        description="large wolf graphic tattoo on right upper arm",
    )


def _body_canon_with_invariant(markings: list) -> str:
    """Simulate what generate_image builds: lock string + invariant suffix."""
    bc = build_body_canon_lock_string(markings)
    if bc:
        return bc + ". " + _CLOTHING_SAFETY_INVARIANT
    return ""


def _make_anchor_data(lock: str = "black hair, brown eyes, tan skin") -> dict:
    return {"identity_lock_string": lock}


def _prompt(
    base: str,
    body_canon: str = "",
    arm_visibility_mode: str = "none",
    provider_name: str = "",
) -> str:
    return _build_strict_identity_prompt(
        base_prompt=base,
        anchor_data=_make_anchor_data(),
        character_name="Leonardo",
        body_canon_str=body_canon,
        arm_visibility_mode=arm_visibility_mode,
        provider_name=provider_name,
        character_id=99,
    )


# ── Test 1: skin-only / hide-if-covered rule ──────────────────────────────────


class TestSkinOnlyAndHideIfCoveredRule:
    """Invariant must declare markings as skin-only and say they are hidden when covered."""

    def test_skin_only_phrase_in_invariant_constant(self):
        """The constant itself must contain the skin-only declaration."""
        assert "skin-only" in _CLOTHING_SAFETY_INVARIANT, (
            "Invariant must declare body markings as 'skin-only'"
        )

    def test_hide_if_covered_phrase_in_invariant_constant(self):
        """The constant must say the marking is hidden when clothing covers it."""
        assert "If clothing covers" in _CLOTHING_SAFETY_INVARIANT, (
            "Invariant must contain 'If clothing covers' clause"
        )
        assert "hidden" in _CLOTHING_SAFETY_INVARIANT, (
            "Invariant must say the marking is 'hidden' when covered"
        )

    def test_skin_only_present_in_prompt_when_markings_exist(self):
        """When markings exist, the assembled prompt must carry the skin-only rule."""
        bc = _body_canon_with_invariant([_wolf_marking()])
        p = _prompt("Leonardo standing outdoors", body_canon=bc)
        assert "skin-only" in p, (
            "skin-only rule missing from prompt when markings exist"
        )

    def test_hide_if_covered_present_in_prompt_when_markings_exist(self):
        """When markings exist, the assembled prompt must carry the hide-if-covered rule."""
        bc = _body_canon_with_invariant([_wolf_marking()])
        p = _prompt("Leonardo standing outdoors", body_canon=bc)
        assert "If clothing covers" in p, (
            "hide-if-covered rule missing from prompt when markings exist"
        )
        assert "hidden" in p, (
            "'hidden' clause missing from prompt when markings exist"
        )


# ── Test 2: clothing graphics / logos / decorative text prohibition ────────────


class TestNoClothingGraphicsRule:
    """Invariant must prohibit clothing graphics, logos, and decorative text."""

    def test_no_clothing_graphics_phrase_in_invariant_constant(self):
        """The constant must ban clothing graphics."""
        assert "No clothing graphics" in _CLOTHING_SAFETY_INVARIANT, (
            "Invariant must contain 'No clothing graphics' prohibition"
        )

    def test_logos_banned_in_invariant_constant(self):
        """The constant must explicitly ban logos."""
        assert "logos" in _CLOTHING_SAFETY_INVARIANT, (
            "Invariant must ban logos on clothing"
        )

    def test_printed_wolf_graphics_banned_in_invariant_constant(self):
        """The constant must name printed wolf graphics as prohibited."""
        assert "printed wolf graphics" in _CLOTHING_SAFETY_INVARIANT, (
            "Invariant must explicitly ban printed wolf graphics — root bug was wolf appearing on shirt"
        )

    def test_typography_banned_in_invariant_constant(self):
        """The constant must ban typography / text on clothing."""
        assert "typography" in _CLOTHING_SAFETY_INVARIANT, (
            "Invariant must ban typography on clothing"
        )

    def test_no_clothing_graphics_present_in_prompt_when_markings_exist(self):
        """When markings exist, the assembled prompt must carry the clothing-graphics prohibition."""
        bc = _body_canon_with_invariant([_wolf_marking()])
        p = _prompt("Leonardo in a pink t-shirt", body_canon=bc, arm_visibility_mode="partial")
        assert "No clothing graphics" in p, (
            "Clothing-graphics prohibition missing from prompt when markings exist"
        )
        assert "printed wolf graphics" in p, (
            "Printed-wolf prohibition missing from prompt — wolf tattoo printed on shirt is the exact bug"
        )


# ── Test 3: t-shirt prompt must not instruct tattoo visible on covered area ───


class TestTshirtDoesNotInstructTattooOnFabric:
    """Body markings + T-shirt must not produce a prompt that causes tattoo-on-fabric rendering.

    The hide-if-covered rule must be present, and the prompt must not contain any
    unconditional instruction to show the tattoo on the shirt sleeve/fabric.
    """

    def _tshirt_prompt_with_wolf(self, provider: str = "") -> str:
        bc = _body_canon_with_invariant([_wolf_marking()])
        return _prompt(
            "Leonardo in a pink t-shirt",
            body_canon=bc,
            arm_visibility_mode="partial",
            provider_name=provider,
        )

    def test_hide_if_covered_rule_present_for_tshirt(self):
        """T-shirt prompt with markings must carry the hide-if-covered rule."""
        p = self._tshirt_prompt_with_wolf()
        assert "If clothing covers" in p, (
            "hide-if-covered rule missing from t-shirt prompt with markings"
        )
        assert "hidden" in p, (
            "'hidden' clause missing from t-shirt prompt — model won't know to hide tattoo"
        )

    def test_skin_only_rule_present_for_tshirt(self):
        """T-shirt prompt with markings must carry the skin-only rule."""
        p = self._tshirt_prompt_with_wolf()
        assert "skin-only" in p or "skin only" in p.lower(), (
            "skin-only rule missing from t-shirt prompt with markings"
        )

    def test_no_clothing_graphics_rule_present_for_tshirt(self):
        """T-shirt prompt must prohibit printed wolf graphics on fabric."""
        p = self._tshirt_prompt_with_wolf()
        assert "printed wolf graphics" in p, (
            "Printed-wolf prohibition missing from t-shirt prompt — root bug surface"
        )

    def test_partial_arm_qualifier_present_for_tshirt(self):
        """T-shirt (partial exposure) must add the sleeve-hide qualifier, not full demand."""
        p = self._tshirt_prompt_with_wolf()
        partial_markers = [
            "shirt sleeve",
            "beneath the shirt",
            "hide any portion",
            "partial arm exposure",
            "exposed forearm",
        ]
        assert any(m in p.lower() for m in partial_markers), (
            f"No partial-visibility qualifier found in t-shirt prompt: {p[-400:]!r}"
        )

    def test_tshirt_prompt_does_not_demand_full_shoulder_to_wrist_render(self):
        """T-shirt prompt must NOT unconditionally demand shoulder-to-wrist rendering
        without also qualifying that the covered portion is hidden."""
        p = self._tshirt_prompt_with_wolf()
        # If "shoulder to wrist" appears it must be accompanied by a hide/partial qualifier
        if "shoulder to wrist" in p.lower():
            hide_qualifiers = ["hide", "beneath", "partial", "hidden"]
            assert any(q in p.lower() for q in hide_qualifiers), (
                "'shoulder to wrist' present without a hide/partial qualifier — "
                "model will render full sleeve through shirt fabric"
            )

    def test_never_print_clause_present_for_tshirt(self):
        """T-shirt prompt must contain the 'never print/transfer' prohibition."""
        p = self._tshirt_prompt_with_wolf()
        assert "Never print" in p or "never printed" in p.lower(), (
            "Never-print prohibition missing from t-shirt prompt with markings"
        )


# ── Test 4: no markings → no invariant injection ──────────────────────────────


class TestNoMarkingsNoInvariant:
    """When a character has no body markings, the invariant must not appear in the prompt."""

    def test_invariant_absent_when_no_markings(self):
        """Empty body_canon_str must not produce invariant phrases in the prompt."""
        p = _prompt("Leonardo walking through a park", body_canon="")
        assert "skin-only" not in p, (
            "skin-only phrase leaked into prompt with no markings"
        )
        assert "If clothing covers" not in p, (
            "hide-if-covered clause leaked into prompt with no markings"
        )
        assert "No clothing graphics" not in p, (
            "clothing-graphics prohibition leaked into prompt with no markings"
        )
        assert "printed wolf graphics" not in p, (
            "printed-wolf prohibition leaked into prompt with no markings"
        )

    def test_build_body_canon_with_invariant_empty_for_no_markings(self):
        """Helper that mimics route logic: no markings → empty string (no invariant suffix)."""
        bc = _body_canon_with_invariant([])
        assert bc == "", (
            "No markings must produce empty body-canon string — invariant must not be injected"
        )

    def test_never_merge_absent_when_no_markings(self):
        """'Never merge' phrase from invariant must not appear with no markings."""
        p = _prompt("Leonardo sitting at a cafe", body_canon="")
        assert "Never merge" not in p
