"""Card/scene skin-coverage engine — the Davies fix (CANON SKIN/CLOTHING).

Distinguishes, deterministically and WITHOUT structured mark data:

  1. body/anatomy truth            — the body-bearing canon cards themselves
  2. permanent skin-mark truth     — PermanentBodyMark + body_map (refines, never gates)
  3. clothed body / silhouette     — cards whose declared coverage matches a clothed scene
  4. scene-specific skin exposure  — the router's existing exposure vocabulary
  5. coverage DEPICTED by each card — CardCoverage metadata (schemas/canon.py)

Why this module exists: production Davies (character 38) was generated in an
opaque white shirt / three-piece suit with his chest tattoos rendered on the
fabric. His body canon cards are shirtless and tattoo-heavy, but
``permanent_body_marks`` is EMPTY — every existing occlusion mechanism
(S24I body_map suppression, the clothing-truth directive, crop gating) is
mark-driven and was therefore inert. The router knew the scene covered the
chest; it had no way to know its own reference cards contradicted that.

Design rules honoured here:
  * Card coverage compatibility NEVER depends on registered permanent marks.
  * Absent card metadata = legacy/unknown — never assumed fully clothed, and
    legacy cards keep today's routing exactly (no forced canon rebuild).
  * Conflicts require the scene to be EXPLICITLY covered (positive clothing
    vocabulary). The conservative covered-by-default state is preserved for
    mark/crop gating but does not suppress legacy-shaped canons — camera-only
    prompts ("front view") route byte-identically to before.
  * body_map gets slot-derived default semantics (bare) — see
    BODY_MAP_DEFAULT_REGIONS. No other slot gets a default.
  * Deterministic substring matching only. No probabilistic inference.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.schemas.canon import (
    ALWAYS_VISIBLE_REGIONS,
    CARD_COVERAGE_SLOTS,
)

if TYPE_CHECKING:
    from app.schemas.canon import BodyCanonData

logger = logging.getLogger(__name__)


# ── body_map slot-default semantics ───────────────────────────────────
# The Body Map is the canonical "ALL TATTOOS & MARKINGS" sheet: its contract is
# to show the skin regions the mark system tracks — torso, back and both arm
# segments — bare. It remains AUTHORITATIVE for exposed scenes; the default
# exists so covered scenes can recognise it as bare evidence even when the
# creator declared nothing (Davies). Legs are deliberately NOT assumed bare:
# the current Body Map contract does not guarantee leg exposure (sheets are
# commonly rendered in jeans), and inventing anatomy beyond the contract is
# worse than under-claiming. A creator may override via card_coverage["body_map"].
BODY_MAP_DEFAULT_REGIONS = frozenset({"torso", "back", "upper_arms", "forearms"})

# Regions that participate in conflict decisions (always-visible face/hands
# never conflict; they are accepted in metadata and ignored here).
_TRACKED = frozenset({"torso", "back", "upper_arms", "forearms", "neck", "legs"})


# ── Positive covered-clothing vocabulary (scene side) ─────────────────
# These distinguish EXPLICITLY covered from unknown/unspecified. The
# conservative default (no signal → covered_default) is unchanged; these sets
# only upgrade the state so routing and diagnostics can tell the difference.
# Exposure signals always take precedence: "shirtless" wins over "shirt",
# "open shirt" wins over "shirt", "swimsuit" is exposure before "suit" is
# cover (see the additions to the router's torso-exposure set).
_COVER_TORSO_SIGNALS = frozenset({
    "suit", "three-piece suit", "three piece suit", "suit vest", "waistcoat",
    "tuxedo", "dress shirt", "shirt", "blouse", "buttoned", "button-up",
    "button up", "turtleneck", "sweater", "jumper", "hoodie", "blazer",
    "jacket", "coat", "dress", "gown", "formal wear", "formalwear", "uniform",
})
_COVER_ARM_SIGNALS = frozenset({
    "long sleeve", "long-sleeve", "long sleeved", "long-sleeved",
    "suit", "tuxedo", "blazer", "jacket", "coat", "sweater", "jumper",
    "hoodie", "turtleneck", "dress shirt", "gown",
})
_COVER_LEG_SIGNALS = frozenset({
    "trousers", "pants", "jeans", "slacks", "suit", "tuxedo", "gown",
    "long skirt", "long dress",
})
_EXPOSE_LEG_SIGNALS = frozenset({
    "shorts", "swim trunks", "swimming trunks", "swimsuit", "bathing suit",
    "swimwear", "bikini", "bare legs", "miniskirt", "mini skirt", "mini-skirt",
})


# ── Scene region states ───────────────────────────────────────────────

def scene_region_states(prompt_lower: str) -> dict[str, str]:
    """Map each tracked region to its state for this scene.

    States: ``"exposed"`` | ``"covered_explicit"`` | ``"covered_default"``.
    Precedence per region: exposed > covered_explicit > covered_default —
    "jacket over a tank top" keeps the arms exposed.

    Reuses the router's existing exposure frozensets (imported lazily to avoid
    a module cycle: scene_router imports this module at top level) so scene
    exposure has exactly ONE vocabulary — no second exposure engine.
    """
    from app.services.scene_router import (
        _CROP_BACK_EXPOSE,
        _CROP_FOREARM_ONLY,
        _CROP_FULL_ARM,
        _CROP_NECK_COVER,
        _CROP_NECK_EXPOSE,
        _CROP_TORSO_EXPOSE,
    )

    def _state(exposed: bool, covered: bool) -> str:
        if exposed:
            return "exposed"
        return "covered_explicit" if covered else "covered_default"

    full_arm = any(s in prompt_lower for s in _CROP_FULL_ARM)
    forearm = full_arm or any(s in prompt_lower for s in _CROP_FOREARM_ONLY)
    arm_cover = any(s in prompt_lower for s in _COVER_ARM_SIGNALS)
    torso_cover = any(s in prompt_lower for s in _COVER_TORSO_SIGNALS)
    neck_covered = any(s in prompt_lower for s in _CROP_NECK_COVER)

    return {
        "torso": _state(any(s in prompt_lower for s in _CROP_TORSO_EXPOSE), torso_cover),
        # Garments that cover the torso cover the back with it.
        "back": _state(any(s in prompt_lower for s in _CROP_BACK_EXPOSE), torso_cover),
        "upper_arms": _state(full_arm, arm_cover),
        "forearms": _state(forearm, arm_cover),
        "neck": _state(
            (not neck_covered) and any(s in prompt_lower for s in _CROP_NECK_EXPOSE),
            neck_covered,
        ),
        "legs": _state(
            any(s in prompt_lower for s in _EXPOSE_LEG_SIGNALS),
            any(s in prompt_lower for s in _COVER_LEG_SIGNALS),
        ),
    }


# ── PermanentBodyMark region → region group ───────────────────────────

def mark_region_groups(body_region: str) -> frozenset[str]:
    """Map a PermanentBodyMark.body_region value onto the group vocabulary.

    Same parsing conventions as the router's ``_mark_region_exposed`` (the
    existing anatomical vocabulary is reused, not duplicated): side prefixes
    are collapsed, full-arm marks span both arm groups. Unknown regions map to
    the empty set — refinement data must never invent coverage.
    """
    r = (body_region or "").lower().strip().replace(" ", "_")
    if r in ("full_right_arm", "full_left_arm"):
        r = "right_full_arm" if "right" in r else "left_full_arm"
    if "forearm" in r or "lower_arm" in r:
        return frozenset({"forearms"})
    if "upper_arm" in r or "shoulder" in r:
        return frozenset({"upper_arms"})
    if r in ("left_full_arm", "right_full_arm", "left_arm", "right_arm"):
        return frozenset({"upper_arms", "forearms"})
    if r in ("chest", "sternum", "abdomen", "ribs", "side", "stomach"):
        return frozenset({"torso"})
    if "back" in r:
        return frozenset({"back"})
    if r in ("neck", "throat"):
        return frozenset({"neck"})
    if "leg" in r or "thigh" in r or "calf" in r or "shin" in r:
        return frozenset({"legs"})
    return frozenset()


# ── Card classification ───────────────────────────────────────────────

@dataclass(frozen=True)
class CardCoverageView:
    """One body-bearing card's coverage as routing sees it."""
    slot: str
    visible_regions: frozenset[str]   # empty for unknown
    source: str                       # "declared" | "slot_default" | "unknown"
    classification: str               # "compatible" | "partial" | "conflicting" | "unknown"
    conflict_regions: frozenset[str]  # regions shown bare where scene is covered_explicit


def card_visible_regions(
    body: "BodyCanonData | None", slot: str
) -> tuple[frozenset[str] | None, str]:
    """Return (visible skin regions, source) for one body-bearing slot.

    Declared metadata wins; body_map falls back to its slot-default contract;
    everything else without metadata is unknown (None) — never fully clothed.
    """
    declared = (getattr(body, "card_coverage", None) or {}).get(slot) if body else None
    if declared is not None:
        return frozenset(declared.visible_skin_regions) - ALWAYS_VISIBLE_REGIONS, "declared"
    if slot == "body_map":
        return BODY_MAP_DEFAULT_REGIONS, "slot_default"
    return None, "unknown"


def classify_cards(
    body: "BodyCanonData | None",
    slots: list[str],
    scene_states: dict[str, str],
) -> dict[str, CardCoverageView]:
    """Classify each body-bearing slot against the scene's region states.

    * ``conflicting`` — the card shows bare skin ONLY in regions the scene
      explicitly covers (no overlap with any exposed region). Routing it hands
      the provider visual evidence that contradicts the requested clothing —
      the Davies bleed-through.
    * ``partial`` — bare in some covered region but ALSO bare in an exposed
      one: scene-useful evidence, kept (rolled sleeves, open shirt).
    * ``compatible`` — declared, and shows no skin where the scene is covered.
    * ``unknown`` — no metadata: legacy card, routed exactly as today.

    Conflicts require ``covered_explicit``: the conservative covered-by-default
    state never suppresses anything, so camera-only prompts and legacy canons
    keep their existing routing. Structured marks play no role here — this is
    the mark-independence Davies proved necessary.
    """
    exposed = {r for r, s in scene_states.items() if s == "exposed"}
    explicit = {r for r, s in scene_states.items() if s == "covered_explicit"}

    out: dict[str, CardCoverageView] = {}
    for slot in slots:
        if slot not in CARD_COVERAGE_SLOTS:
            continue
        regions, source = card_visible_regions(body, slot)
        if regions is None:
            out[slot] = CardCoverageView(slot, frozenset(), "unknown", "unknown", frozenset())
            continue
        tracked = regions & _TRACKED
        conflicts = tracked & explicit
        useful = tracked & exposed
        if conflicts and not useful:
            cls = "conflicting"
        elif conflicts:
            cls = "partial"
        else:
            cls = "compatible"
        out[slot] = CardCoverageView(slot, tracked, source, cls, conflicts)
    return out


# Preference rank when a covered scene must order surviving body evidence:
# compatible clothed/silhouette evidence first, scene-useful partials next,
# legacy unknowns last (their content is unverifiable). Applied ONLY when at
# least one declared card exists, so purely-legacy canons keep today's order.
_RANK = {"compatible": 0, "partial": 1, "unknown": 2}


def coverage_rank(view: CardCoverageView) -> int:
    return _RANK.get(view.classification, 3)
