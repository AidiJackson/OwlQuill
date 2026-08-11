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
# NOTE: the arm-covering vocabulary lives in scene_router as
# ``_COVER_ARM_SIGNALS``, beside the arm-EXPOSURE vocabulary it is weighed
# against. Arm states come from ``scene_router.arm_exposure_states`` below;
# this module no longer reads either set directly.
_COVER_LEG_SIGNALS = frozenset({
    "trousers", "pants", "jeans", "slacks", "suit", "tuxedo", "gown",
    "long skirt", "long dress",
})
_EXPOSE_LEG_SIGNALS = frozenset({
    "shorts", "swim trunks", "swimming trunks", "swimsuit", "bathing suit",
    "swimwear", "bikini", "bare legs", "miniskirt", "mini skirt", "mini-skirt",
})

# Hands and face are visible in essentially every scene — that is why they are
# in ALWAYS_VISIBLE_REGIONS and never create a card-coverage conflict. They
# still need a scene STATE, because "visible" is exactly the precondition for
# asserting that a canonical hand/face mark should be rendered. Without a state
# the positive half of mark truth could never fire for them (a declared hand
# tattoo could only ever be denied, never asserted). Only an explicit covering
# garment takes them out of "exposed".
_COVER_HAND_SIGNALS = frozenset({
    "gloves", "gloved", "glove", "mittens", "boxing gloves", "gauntlets",
    "hands in pockets", "hands pocketed",
})
_COVER_FACE_SIGNALS = frozenset({
    "mask", "masked", "balaclava", "helmet", "visor", "veil", "face covering",
    "face covered", "respirator",
})


# ── Scene region states ───────────────────────────────────────────────

def scene_region_states(prompt_lower: str) -> dict[str, str]:
    """Map each tracked region to its state for this scene.

    States: ``"exposed"`` | ``"covered_explicit"`` | ``"covered_default"`` |
    ``"ambiguous"`` (see the vocabulary block in scene_router).

    Precedence for the regions decided here: exposed > covered_explicit >
    covered_default. The ARMS are not decided here at all — they come from
    ``scene_router.arm_exposure_states``, which is the only place allowed to
    weigh arm exposure against arm coverage, and the only place that can return
    ``ambiguous`` when a scene says both.

    Reuses the router's existing frozensets (imported lazily to avoid a module
    cycle: scene_router imports this module at top level) so scene exposure has
    exactly ONE vocabulary — no second exposure engine.
    """
    from app.services.scene_router import (
        _CROP_BACK_EXPOSE,
        _CROP_NECK_COVER,
        _CROP_NECK_EXPOSE,
        _CROP_TORSO_EXPOSE,
        arm_exposure_states,
    )

    def _state(exposed: bool, covered: bool) -> str:
        if exposed:
            return "exposed"
        return "covered_explicit" if covered else "covered_default"

    upper_arm_state, forearm_state = arm_exposure_states(prompt_lower)
    torso_cover = any(s in prompt_lower for s in _COVER_TORSO_SIGNALS)
    neck_covered = any(s in prompt_lower for s in _CROP_NECK_COVER)

    hands_covered = any(s in prompt_lower for s in _COVER_HAND_SIGNALS)
    face_covered = any(s in prompt_lower for s in _COVER_FACE_SIGNALS)

    return {
        "torso": _state(any(s in prompt_lower for s in _CROP_TORSO_EXPOSE), torso_cover),
        # Garments that cover the torso cover the back with it.
        "back": _state(any(s in prompt_lower for s in _CROP_BACK_EXPOSE), torso_cover),
        "upper_arms": upper_arm_state,
        "forearms": forearm_state,
        "neck": _state(
            (not neck_covered) and any(s in prompt_lower for s in _CROP_NECK_EXPOSE),
            neck_covered,
        ),
        "legs": _state(
            any(s in prompt_lower for s in _EXPOSE_LEG_SIGNALS),
            any(s in prompt_lower for s in _COVER_LEG_SIGNALS),
        ),
        # Default-exposed, unlike every region above: bare hands and an
        # uncovered face are the norm, so the absence of a signal means
        # VISIBLE rather than the conservative covered_default. These keys are
        # deliberately NOT in _TRACKED, so card-coverage conflict/suppression
        # is completely unaffected — they exist for mark truth only.
        "hands": _state(not hands_covered, hands_covered),
        "face": _state(not face_covered, face_covered),
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


# ── Permanent-mark location authority ─────────────────────────────────
# SKIN VISIBILITY and PERMANENT-MARK LOCATION AUTHORITY are different
# concepts. Visibility (above) decides which cards conflict with a scene's
# clothing. Authority decides where marks are allowed to EXIST at all — the
# Davies neck/knuckle failure was the provider extrapolating tattooed skin
# from reference pixels onto regions that are merely VISIBLE (neck above a
# collar, hands) without any canon saying those regions are clean.

def _authority_region_groups(body_region: str) -> frozenset[str]:
    """Region groups for AUTHORITY purposes — extends mark_region_groups.

    Coverage refinement deliberately ignores face/hand regions (they never
    conflict with clothing), but authority must know about them: a registered
    cheek tattoo grants "face" authority, otherwise the clean-skin clause
    would contradict the mark. Returns the empty set for regions it cannot
    map — the caller treats that as a veto on authority.
    """
    groups = mark_region_groups(body_region)
    if groups:
        return groups
    r = (body_region or "").lower().strip().replace(" ", "_")
    if any(t in r for t in ("hand", "knuckle", "finger", "wrist")):
        return frozenset({"hands"})
    if any(t in r for t in ("face", "cheek", "jaw", "forehead", "chin",
                            "temple", "brow", "eye", "nose", "lip", "ear",
                            "head", "scalp")):
        return frozenset({"face"})
    return frozenset()


def mark_location_authority(body: "BodyCanonData | None") -> frozenset[str] | None:
    """Return the region groups where this character's permanent marks live.

    ``None`` means the canon carries NO usable authority data — no clean-skin
    claims may be made. A frozenset (possibly empty) is authoritative: marks
    exist ONLY in these regions; every other region is clean skin.

    Sources, merged by union so an under-declaration can never suppress a
    registered mark:
      * ``marked_regions``       — creator's explicit declaration ([] = the
                                   character is explicitly unmarked)
      * ``permanent_body_marks`` — structured marks; the canon schema defines
                                   these as locked anatomical truth, so a
                                   non-empty set is treated as complete.

    Conservative veto: if ANY structured mark's region cannot be mapped onto
    the group vocabulary, authority is ``None`` — a clean-skin claim that
    might contradict a registered mark is worse than making no claim.
    """
    if body is None:
        return None
    declared = getattr(body, "marked_regions", None)
    marks = getattr(body, "permanent_body_marks", None) or []
    from_marks: set[str] = set()
    for m in marks:
        groups = _authority_region_groups(getattr(m, "body_region", ""))
        if not groups:
            return None  # unmappable mark region → no clean-skin claims
        from_marks |= groups
    if declared is None and not marks:
        return None
    return frozenset(set(declared or []) | from_marks)


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
