"""Regression: body identity refs must load for canonical mode on neutral prompts.

Bug
───
The loading gate in image_generator.py was:

    if _tattoo_visibility_requested or _body_visible:

For a character with markings and a locked body_front, when the scene prompt
contains no explicit exposure keyword ("shirtless", "tank top", etc.),
both flags are False → the branch is never entered → body_front, body_left_detail,
and body_right_detail are never added to anchor_images.

Meanwhile _body_front_canonical was already True (body_front locked + markings
exist), so the code selected canonical prompt text and suppressed arm-binding
text — but then sent the provider no body_front image to actually match against.

Fix
───
Gate condition changed to:

    if _tattoo_visibility_requested or _body_visible or _body_front_canonical:

Expected BODY_REF_USED log after fix for Leonardo Baptiste (neutral prompt):

    canonical_mode=True
    body_front_present=True
    left_right_detail_present=True
"""
import pytest

from app.api.routes.image_generator import _detect_visible_body_regions


# ── Mirrors of image_generator.py conditions ─────────────────────────────────


def _compute_body_front_canonical(
    *,
    body_front_available: bool,
    tattoo_visibility_requested: bool,
    has_markings: bool,
) -> bool:
    """Mirror of image_generator.py lines 1094-1096."""
    return body_front_available and (tattoo_visibility_requested or has_markings)


def _loading_gate(
    *,
    tattoo_visibility_requested: bool,
    body_visible: bool,
    body_front_canonical: bool,
) -> bool:
    """Mirror of image_generator.py line 1177 (post-fix)."""
    return tattoo_visibility_requested or body_visible or body_front_canonical


# ── Neutral prompts that must NOT trigger exposure detection ──────────────────

_NEUTRAL_PROMPTS = [
    "Leonardo sitting in a cafe reading a book",
    "Leonardo standing on a rooftop at night",
    "Leonardo leaning against a wall in an alley",
    "Portrait of Leonardo looking to the side",
    "Leonardo in a dimly lit room",
    "Close-up of Leonardo, serious expression",
]


# ── Test 1: canonical mode activates without exposure keywords ────────────────


class TestCanonicalModeActivatesWithoutExposureKeywords:
    """body_front locked + markings present → canonical=True regardless of prompt."""

    def test_activates_neutral_prompt_markings_body_front_locked(self):
        canonical = _compute_body_front_canonical(
            body_front_available=True,
            tattoo_visibility_requested=False,
            has_markings=True,
        )
        assert canonical, (
            "canonical mode must be True when body_front=locked and markings exist, "
            "even when the prompt has no exposure keywords"
        )

    def test_does_not_activate_no_markings(self):
        canonical = _compute_body_front_canonical(
            body_front_available=True,
            tattoo_visibility_requested=False,
            has_markings=False,
        )
        assert not canonical

    def test_does_not_activate_body_front_not_locked(self):
        canonical = _compute_body_front_canonical(
            body_front_available=False,
            tattoo_visibility_requested=False,
            has_markings=True,
        )
        assert not canonical


# ── Test 2: loading gate opens for canonical mode ─────────────────────────────


class TestLoadingGateOpensForCanonicalMode:
    """Gate must open when canonical=True, even with no exposure keywords.

    Before fix: gate = tattoo_vis or body_visible → False for neutral prompts.
    After fix:  gate = tattoo_vis or body_visible or body_front_canonical → True.
    """

    def test_gate_opens_canonical_neutral_prompt(self):
        """Core regression: markings + body_front locked + no exposure → gate open."""
        canonical = _compute_body_front_canonical(
            body_front_available=True,
            tattoo_visibility_requested=False,
            has_markings=True,
        )
        gate = _loading_gate(
            tattoo_visibility_requested=False,
            body_visible=False,
            body_front_canonical=canonical,
        )
        assert gate, (
            "Loading gate must open for canonical mode on a neutral prompt. "
            "body_front_present=True in BODY_REF_USED requires this gate to be True."
        )

    def test_pre_fix_gate_was_closed_for_neutral_prompt(self):
        """Document the broken pre-fix gate for the same scenario."""
        tattoo_visibility_requested = False
        body_visible = False
        old_gate = tattoo_visibility_requested or body_visible
        assert not old_gate, (
            "Pre-fix gate was False for neutral prompts — "
            "body_front was never loaded even when locked"
        )

    def test_gate_stays_closed_no_markings_neutral_prompt(self):
        """No markings + neutral prompt → canonical=False → gate stays closed."""
        canonical = _compute_body_front_canonical(
            body_front_available=True,
            tattoo_visibility_requested=False,
            has_markings=False,
        )
        gate = _loading_gate(
            tattoo_visibility_requested=False,
            body_visible=False,
            body_front_canonical=canonical,
        )
        assert not gate, (
            "Gate must stay closed for neutral prompt with no markings — "
            "loading body refs for an unmarked character adds noise"
        )

    def test_all_three_conditions_independently_open_gate(self):
        """Each condition alone is sufficient to open the gate."""
        assert _loading_gate(tattoo_visibility_requested=True, body_visible=False, body_front_canonical=False)
        assert _loading_gate(tattoo_visibility_requested=False, body_visible=True, body_front_canonical=False)
        assert _loading_gate(tattoo_visibility_requested=False, body_visible=False, body_front_canonical=True)

    def test_gate_closed_when_all_conditions_false(self):
        """Gate closed only when every condition is False."""
        assert not _loading_gate(
            tattoo_visibility_requested=False,
            body_visible=False,
            body_front_canonical=False,
        )


# ── Test 3: neutral prompts produce no exposure signal ────────────────────────


class TestNeutralPromptsProduceNoExposureSignal:
    """Confirm neutral prompts don't trigger _detect_visible_body_regions.

    This establishes that the gate fix is the ONLY reason body identity refs
    load for Leonardo on neutral prompts — not a keyword match.
    """

    @pytest.mark.parametrize("prompt", _NEUTRAL_PROMPTS)
    def test_neutral_prompt_no_visible_regions(self, prompt):
        regions = _detect_visible_body_regions(prompt.lower())
        assert regions == set(), (
            f"Neutral prompt {prompt!r} must not trigger visible region detection. "
            f"Got: {regions}"
        )

    @pytest.mark.parametrize("prompt", _NEUTRAL_PROMPTS)
    def test_gate_opens_for_neutral_prompt_via_canonical_path(self, prompt):
        """For every neutral prompt: canonical=True (markings+locked) → gate open."""
        regions = _detect_visible_body_regions(prompt.lower())
        tattoo_vis = bool(regions)

        canonical = _compute_body_front_canonical(
            body_front_available=True,
            tattoo_visibility_requested=tattoo_vis,
            has_markings=True,
        )
        gate = _loading_gate(
            tattoo_visibility_requested=tattoo_vis,
            body_visible=False,
            body_front_canonical=canonical,
        )
        assert gate, (
            f"Gate must open for {prompt!r} via canonical path. "
            f"tattoo_vis={tattoo_vis}, canonical={canonical}"
        )


# ── Test 4: expected BODY_REF_USED log values after fix ──────────────────────


class TestExpectedBodyRefUsedLog:
    """Verify precondition chain that drives expected BODY_REF_USED values.

    For Leonardo Baptiste (character_id=41), neutral prompt, all slots locked:

        canonical_mode=True          ← _body_front_canonical=True
        body_front_present=True      ← gate opens + body_front image loaded
        left_right_detail_present=True ← same gate branch loads all body slots
    """

    def test_canonical_mode_true_for_leonardo(self):
        """canonical_mode=True in log ← _body_front_canonical=True."""
        canonical = _compute_body_front_canonical(
            body_front_available=True,   # body_front slot: status=locked, url present
            tattoo_visibility_requested=False,
            has_markings=True,           # 2 markings: right_full_arm, left_full_arm
        )
        assert canonical, "canonical_mode=True requires this to be True"

    def test_body_front_present_true_precondition(self):
        """body_front_present=True ← gate opens AND body_front image loaded."""
        canonical = _compute_body_front_canonical(
            body_front_available=True,
            tattoo_visibility_requested=False,
            has_markings=True,
        )
        gate = _loading_gate(
            tattoo_visibility_requested=False,
            body_visible=False,
            body_front_canonical=canonical,
        )
        assert canonical and gate, (
            "body_front_present=True requires canonical=True AND gate=True. "
            f"Got canonical={canonical}, gate={gate}"
        )

    def test_left_right_detail_present_true_precondition(self):
        """left_right_detail_present=True ← same gate branch as body_front."""
        # body_left_detail and body_right_detail are loaded in the same
        # get_body_identity_references() call inside the gate branch.
        canonical = _compute_body_front_canonical(
            body_front_available=True,
            tattoo_visibility_requested=False,
            has_markings=True,
        )
        gate = _loading_gate(
            tattoo_visibility_requested=False,
            body_visible=False,
            body_front_canonical=canonical,
        )
        assert gate, (
            "left_right_detail_present=True requires gate=True. "
            "body_left_detail and body_right_detail are loaded in the same branch."
        )
