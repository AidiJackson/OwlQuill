"""P15 — scene-aware permanent-marking clause.

Clothing truth > tattoo visibility. The compiled prompt text must match the
routing layer's visibility decisions: a tattoo the scene COVERS is never named
and never given a "reproduce its exact geometry" instruction (which previously
pushed the provider to split/cut garments open to expose hidden marks). Only
genuinely exposed marks get the skin-bound + exact-geometry block.

These regressions pin the fix end to end via compile_canon_prompt.
"""
from app.services.canon_compiler import compile_canon_prompt

from tests.consistency_eval import build_characters

# Prompt-clause fingerprints (lowercased).
_GEOMETRY = "reproduce each marking's exact shape"
_PERMANENCE = "do not redesign, relocate, mirror"
_SKIN_BOUND = "permanent markings are immutable skin-bound anatomy"
_CLOTHING = "permanent markings obey scene clothing"
_HIDDEN = "hidden markings remain hidden"

# Leo carries an asymmetric pair: left_full_arm gothic script sleeve +
# right_upper_arm "howling wolf head, fine linework".
LEO = build_characters()[0]


def _prompt(scene: str) -> str:
    return compile_canon_prompt(LEO.canon, scene).lower()


# ── Covered scenes: no tattoo forcing ─────────────────────────────────


class TestCoveredScenesDoNotForceTattoos:
    """Formal suit / long sleeve fully cover the arms → no mark naming, no
    geometry, no permanence reproduction clause. Only clothing truth remains."""

    def test_formal_suit_does_not_name_wolf(self):
        p = _prompt("wearing a formal suit and tie at a gala dinner")
        assert "wolf" not in p
        assert "gothic" not in p          # left sleeve also covered
        assert _SKIN_BOUND not in p
        assert _GEOMETRY not in p
        assert _PERMANENCE not in p
        # Clothing truth is asserted instead, keeping the marks hidden.
        assert _CLOTHING in p
        assert _HIDDEN in p

    def test_long_sleeve_does_not_force_geometry(self):
        p = _prompt("wearing a long-sleeve sweater indoors")
        assert "wolf" not in p
        assert _GEOMETRY not in p
        assert _PERMANENCE not in p
        assert _CLOTHING in p

    def test_buttoned_shirt_no_rolled_sleeves_hides_both_arms(self):
        p = _prompt("wearing a buttoned-up dress shirt at the office")
        assert "wolf" not in p
        assert _SKIN_BOUND not in p
        assert _GEOMETRY not in p


# ── Exposed scenes: full fidelity preserved ───────────────────────────


class TestExposedScenesKeepFidelity:
    """Sleeveless / pool expose the arms → wolf is named, framed as skin-bound,
    with the exact-geometry instruction intact."""

    def test_sleeveless_names_wolf_with_geometry(self):
        p = _prompt("facing camera in a sleeveless tank top, arms visible")
        assert "wolf" in p
        assert _SKIN_BOUND in p
        assert _GEOMETRY in p
        assert _PERMANENCE in p
        assert "this specific design" in p  # exact-design instruction

    def test_pool_open_shirt_names_wolf(self):
        p = _prompt("at the swimming pool, open shirt, arms out")
        assert "wolf" in p
        assert _GEOMETRY in p


# ── Portrait: no marking block at all ─────────────────────────────────


class TestPortraitHasNoTattooBlock:
    def test_portrait_emits_no_marking_block(self):
        p = _prompt("close-up portrait, soft smile, head and shoulders")
        assert "wolf" not in p
        assert _SKIN_BOUND not in p
        assert _GEOMETRY not in p
        assert _PERMANENCE not in p
        assert _CLOTHING not in p  # no forcing block of any kind for portraits


# ── Rolled sleeves: asymmetric per-mark visibility ────────────────────


class TestRolledSleevesAsymmetry:
    """Kitchen button-up with sleeves rolled to the forearms: the forearm
    portion of the left sleeve is exposed; the right upper-arm wolf stays
    covered. Text must reflect exactly that split."""

    _KITCHEN = (
        "standing in a modern kitchen wearing a fitted button-up shirt "
        "with sleeves rolled to the forearms, cinematic realism"
    )

    def test_forearm_sleeve_named_upper_arm_wolf_hidden(self):
        p = _prompt(self._KITCHEN)
        # Exposed forearm sleeve → named + skin-bound block present.
        assert "gothic" in p or "sleeve" in p
        assert _SKIN_BOUND in p
        assert _GEOMETRY in p
        # Covered upper-arm wolf → never named.
        assert "wolf" not in p
        # Clothing truth keeps the wolf hidden.
        assert _CLOTHING in p
        assert _HIDDEN in p

    def test_kitchen_prompt_stays_compact(self):
        p = _prompt(self._KITCHEN)
        assert "for visual balance or composition" not in p  # no pre-P12 prose
        assert len(p) < 1200
