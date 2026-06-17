"""Scene-aware reference router — deterministic, keyword-based.

Selects and orders canon reference images based on detected camera
orientation and body-exposure signals in the scene prompt.

No LLM parsing. No probabilistic inference.
All detection uses exact substring matching against frozensets.

Public API:
  route_canon_refs(prompt, canon) → (list[str], SceneMeta)
  SceneMeta                        — structured scene metadata

Rollback: git checkout pre-p10-scene-router
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon

from app.services.canon_service import load_body_canon, load_face_canon

logger = logging.getLogger(__name__)


# ── Camera orientation signals ────────────────────────────────────────
# Detection priority (highest to lowest):
#   portrait_closeup > back > 3q > profile > full_body > front

_PORTRAIT_CLOSEUP_SIGNALS = frozenset({
    "close-up", "closeup", "close up", "close shot",
    "headshot", "head shot", "face only", "tight portrait",
})

_BACK_SIGNALS = frozenset({
    "back to camera", "from behind", "rear view", "seen from behind",
    "back view", "turning away", "walking away", "facing away",
    "showing back", "back turned",
})

_LEFT_3Q_SIGNALS = frozenset({
    "three-quarter left", "three quarter left", "3/4 left",
    "left three-quarter", "left 3/4", "3q left", "left 3q",
})

_RIGHT_3Q_SIGNALS = frozenset({
    "three-quarter right", "three quarter right", "3/4 right",
    "right three-quarter", "right 3/4", "3q right", "right 3q",
})

_LEFT_PROFILE_SIGNALS = frozenset({
    "left profile", "from the left", "profile from left",
    "profile left", "side profile left", "left-facing",
})

_RIGHT_PROFILE_SIGNALS = frozenset({
    "right profile", "from the right", "profile from right",
    "profile right", "side profile right", "right-facing",
})

_FULL_BODY_SIGNALS = frozenset({
    "full body", "full-body", "head to toe", "full length",
})

_FRONT_SIGNALS = frozenset({
    "facing camera", "facing forward", "facing front", "front view",
    "front facing", "front-facing", "looking at camera",
    "face on", "head on", "direct gaze",
})


# ── Exposure signals ──────────────────────────────────────────────────

_SHIRTLESS_EXPOSURE = frozenset({
    "shirtless", "bare-chested", "bare chest", "bare chested", "no shirt",
    "topless", "bare torso",
})

_SLEEVELESS_EXPOSURE = frozenset({
    "sleeveless", "tank top", "tank",
})

_ROLLED_SLEEVE_EXPOSURE = frozenset({
    "rolled sleeve", "rolled sleeves", "rolled-up sleeve", "rolled-up sleeves",
    "rolled up sleeve", "rolled up sleeves", "sleeves rolled", "sleeve rolled",
    "sleeves rolled up", "sleeves pushed up",
})

_SHORT_SLEEVE_EXPOSURE = frozenset({
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
})

_LONG_SLEEVE_EXPOSURE = frozenset({
    "long sleeve", "long-sleeve", "long sleeved", "long-sleeved",
})

_JACKET_EXPOSURE = frozenset({
    "jacket", "leather jacket", "blazer",
})

_COAT_EXPOSURE = frozenset({
    "coat", "overcoat", "trenchcoat", "trench coat",
})

# ── S24AB: tattoo-exposure-hardening cues ─────────────────────────────
# Additional exposure signals the router previously lacked. "tattoos visible"
# et al. are an explicit instruction to reveal tattooed skin — it must DRIVE
# routing (force the marked region exposed) rather than relying on the user's
# literal prose reaching the provider by chance. The others describe scenes
# that bare the arms/torso. These are folded into the per-region _CROP_* sets
# below so the existing _mark_region_exposed gate picks them up unchanged.
_TATTOOS_VISIBLE_EXPOSURE = frozenset({
    "tattoos visible", "tattoo visible", "visible tattoos", "visible tattoo",
    "tattoos showing", "tattoo showing", "tattoos shown", "tattoo shown",
    "show tattoos", "show the tattoos", "showing tattoos", "tattoos exposed",
    "tattoos on display", "ensure tattoos are visible", "make tattoos visible",
})
_UNDERWEAR_EXPOSURE = frozenset({
    "underwear", "in underwear", "in his underwear", "in her underwear",
    "boxers", "briefs",
})
_GYM_EXPOSURE = frozenset({
    "gym", "at the gym", "in the gym", "gym workout", "workout", "working out",
})
_TOWEL_EXPOSURE = frozenset({
    "towel", "in a towel", "wrapped in a towel", "towel wrapped",
    "wearing a towel",
})
_WET_SHIRT_EXPOSURE = frozenset({
    "wet shirt", "wet t-shirt", "wet tshirt", "wet tee", "wet t shirt",
})


# ── Provider reference cap ────────────────────────────────────────────
# Maximum references the provider consumes. The routed slot lists below may
# list one extra "if room" slot (e.g. front's face_expression); anything past
# this cap is dropped after weighting. Mirrors the [:6] cap at the call sites.

MAX_PROVIDER_REFS = 6


# ── P13: exposure-gated cropped-mark reference routing ────────────────
# When a scene exposes the skin region a permanent mark sits on, its high-
# fidelity crop (PermanentBodyMark.detail_crop_url or .reference_image_url) is routed ahead of the
# lower-priority whole-body/face variants. Whole-body cards average tattoo
# detail away; a tight crop preserves geometry. Covered marks are never routed.

# Cap on crops per scene — leaves room for body_front + body_map under the 6-cap.
_MAX_MARK_CROPS = 2

_CROP_FULL_ARM = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso", "sleeveless", "tank top", "tank", "vest",
    "muscle shirt", "muscle tee", "camisole", "racerback",
    "bare arms", "arms bare", "bare arm", "arms out", "arm out",
    "arms visible", "arm visible", "both arms visible", "arms exposed",
    "arm exposed", "exposed arms", "arms uncovered", "arms shown",
    "swimwear", "swimsuit", "swimming", "swimming pool", "poolside",
    "pool party", "at the pool", "in the pool", "beach", "bikini",
}) | _TATTOOS_VISIBLE_EXPOSURE | _UNDERWEAR_EXPOSURE | _GYM_EXPOSURE | _TOWEL_EXPOSURE
_CROP_FOREARM_ONLY = frozenset({
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
    "rolled sleeve", "rolled sleeves", "rolled-up sleeve", "rolled-up sleeves",
    "rolled up sleeve", "rolled up sleeves", "sleeves rolled", "sleeve rolled",
    "sleeves rolled up", "sleeves pushed up", "pushed-up sleeves", "pushed up sleeves",
    "rolled to the elbow", "rolled to the elbows", "rolled past the elbow",
    "rolled above the elbow", "sleeves up", "sleeve up",
    "forearm visible", "forearms visible", "forearm exposed", "forearms exposed",
    "forearms out", "bare forearm", "bare forearms", "forearms bare",
})
_CROP_NECK_EXPOSE = frozenset({
    "open collar", "open shirt", "shirt open", "unbuttoned", "v-neck", "v neck",
    "scoop neck", "low neckline", "deep neckline", "bare neck", "neck visible",
    "shirtless", "bare chest", "tank top", "sleeveless", "swimming",
    "swimming pool", "poolside",
}) | _TATTOOS_VISIBLE_EXPOSURE | _UNDERWEAR_EXPOSURE
_CROP_NECK_COVER = frozenset({
    "turtleneck", "high collar", "scarf", "buttoned-up", "buttoned up",
    "closed collar", "hood up", "balaclava",
})
_CROP_TORSO_EXPOSE = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso", "open shirt", "shirt open", "unbuttoned",
    "swimming", "swimming pool", "poolside", "swimwear", "bikini",
}) | _TATTOOS_VISIBLE_EXPOSURE | _UNDERWEAR_EXPOSURE | _TOWEL_EXPOSURE | _WET_SHIRT_EXPOSURE
_CROP_BACK_EXPOSE = frozenset({
    "shirtless", "bare back", "back visible", "from behind", "back view", "topless",
})


# Union of all skin-exposure signals (P14). Any of these implies the body is in
# frame with skin exposed, even when the prompt carries no camera-orientation
# keyword. Used to promote an otherwise-ambiguous scene to a front body shot so
# body-truth + exposed-mark crop routing engages (e.g. "open shirt, arms out at
# the pool" — a named acceptance scenario). Cover signals are deliberately
# excluded; per-region exposure is still gated by _mark_region_exposed.
_SKIN_EXPOSURE_PROMOTION = (
    _CROP_FULL_ARM | _CROP_FOREARM_ONLY | _CROP_NECK_EXPOSE | _CROP_TORSO_EXPOSE
)


def _is_sleeve_mark(mark: object) -> bool:
    """True if a permanent mark is a full-arm sleeve (forearm portion visible
    even under a t-shirt / rolled sleeves)."""
    region = (getattr(mark, "body_region", "") or "").lower()
    if region in ("left_full_arm", "right_full_arm", "left_arm", "right_arm"):
        return True
    text = (
        (getattr(mark, "label", "") or "") + " "
        + (getattr(mark, "description", "") or "")
    ).lower()
    return "sleeve" in text


def _mark_region_exposed(body_region: str, is_sleeve: bool, prompt_lower: str) -> bool:
    """Return True when the scene exposes the skin region a mark sits on.

    Deterministic substring matching only — no inference. Conservative: when
    there is no positive exposure signal for a region it returns False so the
    crop is NOT routed (the whole-body cards still carry the covered mark).
    """
    region = (body_region or "").lower().strip().replace(" ", "_")
    # Tolerate position-first arm wording ("full_right_arm") → canonical
    # side-first form ("right_full_arm") so free-text region drift still matches.
    if region in ("full_right_arm", "full_left_arm"):
        region = "right_full_arm" if "right" in region else "left_full_arm"
    full_arm = any(s in prompt_lower for s in _CROP_FULL_ARM)
    forearm = any(s in prompt_lower for s in _CROP_FOREARM_ONLY)

    # ── Arms ──
    if "forearm" in region or "lower_arm" in region:
        return bool(full_arm or forearm)
    if "upper_arm" in region:
        # A non-sleeve upper-arm mark is covered by short/rolled sleeves (they
        # leave only the forearm bare). A SLEEVE, however, spans the whole arm,
        # so its forearm portion still shows — honour is_sleeve here so a mark
        # labelled "... sleeve" on the upper arm is not wrongly suppressed when
        # the forearm is exposed.
        if is_sleeve:
            return bool(full_arm or forearm)
        return bool(full_arm)
    if region in ("left_full_arm", "right_full_arm", "left_arm", "right_arm"):
        # Full-arm mark: exposed if the arm is bare, or (sleeve) the forearm shows.
        if full_arm:
            return True
        if forearm:
            return True
        return False
    # ── Neck / throat ──
    if region in ("neck", "throat"):
        if any(s in prompt_lower for s in _CROP_NECK_COVER):
            return False
        return any(s in prompt_lower for s in _CROP_NECK_EXPOSE)
    # ── Torso ──
    if region in ("chest", "sternum", "abdomen", "ribs", "side", "stomach"):
        return any(s in prompt_lower for s in _CROP_TORSO_EXPOSE)
    # ── Back ──
    if "back" in region:
        return any(s in prompt_lower for s in _CROP_BACK_EXPOSE)
    # ── Hands / face are generally visible ──
    if region in (
        "left_hand", "right_hand", "hand", "knuckles", "face",
        "right_cheek", "left_cheek", "jaw", "forehead", "chin",
    ):
        return True
    # Legs / other regions → conservative (not routed without explicit signal).
    return False


# Body-anchor slots: a routed tattoo crop must always be paired with at least
# one of these so the provider grounds the crop on anatomy rather than treating
# it as a free-floating symbol/accessory. Crops are never routed without one.
_BODY_ANCHOR_SLOTS = frozenset({
    "body_front", "body_map", "body_back", "body_left", "body_right",
})

# Face identity slots — used to identify the camera's primary face anchor so it
# leads the routed list (P14 Phase 3: body/crop refs must not overpower face).
_FACE_SLOTS = frozenset({
    "face_front", "face_left_3q", "face_right_3q", "face_expression",
})

# P14 Phase 1/2 — Body-truth dominance ordering.
# When a scene exposes a permanent mark, the *body truth* refs (whole-body
# anatomy + canonical marking placement) must precede the high-fidelity mark
# crop so the provider reads "this person with these tattoos" rather than
# isolating "a tattoo concept". The crop is supporting evidence only and is
# NEVER allowed to lead. body_front + body_map are pulled from the full canon
# (not just the camera route) so they are always present when the body is
# visible, joined by the orientation-matched side for the active camera.
_ORIENTATION_BODY: dict[str, str] = {
    "back": "body_back",
    "left_profile": "body_left",
    "left_3q": "body_left",
    "right_profile": "body_right",
    "right_3q": "body_right",
}


@dataclass
class MarkCropBinding:
    """Body-binding metadata travelling with a routed permanent-mark crop.

    Carries the anatomy the crop must be applied to, so the crop is interpreted
    as 'apply this marking to <region>/<side>' rather than 'include this object'.
    """
    url: str
    body_region: str
    side: str
    label: str
    visibility: str  # "exposed" — only exposed-region crops are ever routed
    # Audit-only provenance (no routing effect): which mark this crop came from
    # and which canon field supplied the URL (detail_crop_url | reference_image_url).
    mark_id: str = ""
    source: str = ""


def _collect_exposed_mark_crops(
    canon: "CharacterIdentityCanon",
    prompt_lower: str,
    camera: str,
) -> list["MarkCropBinding"]:
    """Return body-bound crop records for permanent marks the scene exposes.

    Portrait close-ups never route body crops. The high-fidelity mark-detail
    card is preferred (detail_crop_url) with a fallback to the general reference
    photo (reference_image_url); marks with neither degrade gracefully (skipped).
    Capped at _MAX_MARK_CROPS. Each record preserves body_region / side / label /
    visibility so the crop stays bound to the correct anatomy downstream
    (binding metadata, #1).
    """
    if camera == "portrait_closeup":
        return []
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return []
    crops: list[MarkCropBinding] = []
    for m in marks:
        # Prefer the dedicated close-up detail crop; fall back to a general ref.
        detail = getattr(m, "detail_crop_url", None)
        url = detail or getattr(m, "reference_image_url", None)
        if not url:
            continue  # graceful degrade — no crop available for this mark
        if _mark_region_exposed(getattr(m, "body_region", ""), _is_sleeve_mark(m), prompt_lower):
            crops.append(MarkCropBinding(
                url=url,
                body_region=getattr(m, "body_region", "") or "",
                side=getattr(m, "side", "") or "",
                label=getattr(m, "label", "") or "",
                visibility="exposed",
                mark_id=getattr(m, "id", "") or "",
                source="detail_crop_url" if detail else "reference_image_url",
            ))
        if len(crops) >= _MAX_MARK_CROPS:
            break
    return crops


def _merge_crops(
    camera: str,
    slots_avail: list[str],
    slot_urls: dict[str, str],
    crops: list["MarkCropBinding"],
) -> tuple[list[str], list[str]]:
    """Order refs so BODY TRUTH dominates and mark crops are supporting only.

    P14 Phase 1/2 — body-truth dominance. The provider must see "this person
    with these exact tattoos", not "a tattoo concept". The routed order is:

        1. primary face anchor   — face identity leads (Phase 3); never buried
        2. body truth block      — body_front, body_map, orientation side,
                                    final card (in that dominance order)
        3. mark crops            — SUPPORTING evidence only, never primary
        4. remaining face geometry

    body_front + body_map are pulled from the full canon (slot_urls), not just
    the camera route, so they are always present when the body is visible and a
    crop is about to be routed (Phase 2: "never allow exposed-mark routing
    without body truth present").

    Routing guarantee (#3): a tattoo crop is NEVER routed alone or ahead of the
    leading body anchors. If no real body anchor is available the crops are
    dropped and plain slot routing is returned, so the provider always has
    anatomy to bind onto.

    P15b — OpenAI rolled-sleeve forearm fidelity. The leading anchors
    (body_front, body_map, orientation side) stay first to dominate and prevent
    floating, but the exposed-mark crops are spliced in BEFORE the holistic
    final_character_card. OpenAI's images.edit is position-weighted and
    first-image-dominant; behind the holistic card the crop was too weak and the
    forearm tattoo under-rendered. Promoting the crop ahead of the holistic card
    (still behind the two grounding anchors) restores OpenAI forearm fidelity
    without weakening body-truth dominance, reopening over-forcing, or affecting
    Google (which weights all refs evenly).

    Returns (slot_tokens, urls); crop entries use the token 'mark_crop'. Crops
    stay contiguous and in input order, so the caller's crops[:crop_count]
    binding slice remains correct after the provider cap.
    """
    plain_slots = slots_avail[:MAX_PROVIDER_REFS]
    plain_urls = [slot_urls[s] for s in plain_slots]

    # Leading body anchors in dominance priority (Phase 1): front body truth
    # first, canonical marking-placement map second, orientation-matched side
    # third. These stay AHEAD of the crops as the anti-float grounding anchors.
    seen: set[str] = set()
    body_anchors: list[str] = []
    for s in ("body_front", "body_map", _ORIENTATION_BODY.get(camera)):
        if s and s in slot_urls and s not in seen:
            body_anchors.append(s)
            seen.add(s)

    # Holistic identity card — support only; demoted to AFTER the crops (P15b).
    holistic = [s for s in ("final_character_card",)
                if s in slot_urls and s not in seen]
    for s in holistic:
        seen.add(s)

    # Guarantee (#3): never route a crop without a real body anchor (the holistic
    # card alone is not anatomy to bind onto). Drop crops → plain routing.
    if not any(s in _BODY_ANCHOR_SLOTS for s in body_anchors):
        return plain_slots, plain_urls

    # Face dominance (Phase 3): lead with the camera's primary face anchor so the
    # body-truth block and crops never overpower facial identity.
    primary_face = [s for s in slots_avail if s in _FACE_SLOTS][:1]
    for s in primary_face:
        seen.add(s)
    rest_face = [s for s in slots_avail if s in _FACE_SLOTS and s not in seen]

    ordered = (
        primary_face                    # 1. face identity anchor
        + body_anchors                  # 2. leading body anchors (anti-float)
        + ["mark_crop"] * len(crops)    # 3. exposed crops — ahead of holistic card
        + holistic                      # 4. holistic identity card — support only
        + rest_face                     # 5. remaining face geometry
    )

    crop_iter = iter(crops)
    out_slots: list[str] = []
    out_urls: list[str] = []
    for s in ordered:
        out_urls.append(next(crop_iter).url if s == "mark_crop" else slot_urls[s])
        out_slots.append(s)
        if len(out_urls) >= MAX_PROVIDER_REFS:
            break
    return out_slots, out_urls


# ── P11 orientation-aware weighting: camera → priority-ordered slots ───
# Slots are listed in descending reference priority for each camera. P10
# detection chooses the camera; this layer chooses the order in which that
# camera's slots reach the provider. Missing canon slots are skipped
# silently; the surviving list is capped at MAX_PROVIDER_REFS.
#
# Weighting intent per camera:
#   front/full_body — body truth first, exact face reinforced, identity
#                     compression card early, tattoo placement retained,
#                     support geometry last (face_expression only "if room")
#   back            — back anatomy dominates; body truth preserved; face
#                     retained as a lower-priority identity anchor
#   left/right      — that side's anatomy + matching 3q face dominate
#   portrait        — facial identity dominates (face-only stack)

_ROUTES: dict[str, list[str]] = {
    "front": [
        "body_front", "face_front", "final_character_card",
        "body_map", "face_left_3q", "face_right_3q", "face_expression",
    ],
    "full_body": [
        "body_front", "face_front", "final_character_card",
        "body_map", "face_left_3q", "face_right_3q", "face_expression",
    ],
    "back": [
        "body_back", "final_character_card", "body_map",
        "face_front", "face_left_3q", "face_right_3q",
    ],
    "left_profile": [
        "body_left", "face_left_3q", "final_character_card",
        "body_map", "face_front", "face_right_3q",
    ],
    "right_profile": [
        "body_right", "face_right_3q", "final_character_card",
        "body_map", "face_front", "face_left_3q",
    ],
    "left_3q": [
        "body_left", "face_left_3q", "final_character_card",
        "body_map", "face_front", "face_right_3q",
    ],
    "right_3q": [
        "body_right", "face_right_3q", "final_character_card",
        "body_map", "face_front", "face_left_3q",
    ],
    # P14 Phase 3 — face dominance hardening. A close-up is pure facial identity:
    # lead with face_front, reinforce with both 3/4 geometry refs (matching face),
    # then the optional expression card, then the holistic card. No body routing.
    "portrait_closeup": [
        "face_front", "face_left_3q", "face_right_3q",
        "face_expression", "final_character_card",
    ],
}


# ── Scene metadata ────────────────────────────────────────────────────

@dataclass
class SceneMeta:
    """Structured metadata describing the detected scene."""
    camera: str                                       # detected orientation or "unknown"
    exposure: list[str] = field(default_factory=list) # active exposure signal names
    routed: bool = False                              # True = routing applied; False = fallback
    route_slots: list[str] = field(default_factory=list)  # slot names in returned order
    mark_crops: int = 0                               # exposed permanent-mark crops routed
    # Body-binding metadata for the crops actually routed (#1): each carries the
    # body_region/side/label the crop must be applied to, so the preserved
    # binding survives routing and is auditable downstream.
    mark_crop_bindings: list["MarkCropBinding"] = field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────

def _get_canon_slot_urls(canon: "CharacterIdentityCanon") -> dict[str, str]:
    """Build a slot_name → url mapping for all populated canon image slots."""
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    slots: dict[str, str] = {}

    if face:
        for slot, attr in (
            ("face_front",      "face_front_image_url"),
            ("face_left_3q",    "face_left_3q_image_url"),
            ("face_right_3q",   "face_right_3q_image_url"),
            ("face_expression", "face_expression_image_url"),
        ):
            url = getattr(face, attr, None)
            if url:
                slots[slot] = url

    if body:
        for slot, attr in (
            ("body_front",           "body_front_image_url"),
            ("body_left",            "body_left_image_url"),
            ("body_right",           "body_right_image_url"),
            ("body_back",            "body_back_image_url"),
            ("body_map",             "body_map_image_url"),
            ("final_character_card", "final_character_card_image_url"),
        ):
            url = getattr(body, attr, None)
            if url:
                slots[slot] = url

    return slots


def _detect_camera(prompt_lower: str) -> str | None:
    """Detect camera orientation from a lowercased prompt.

    Returns an orientation string, or None when the prompt is ambiguous
    (no detectable orientation signal).

    Priority: portrait_closeup > back > 3q > profile > full_body > front.
    """
    if any(s in prompt_lower for s in _PORTRAIT_CLOSEUP_SIGNALS):
        return "portrait_closeup"
    if any(s in prompt_lower for s in _BACK_SIGNALS):
        return "back"
    if any(s in prompt_lower for s in _LEFT_3Q_SIGNALS):
        return "left_3q"
    if any(s in prompt_lower for s in _RIGHT_3Q_SIGNALS):
        return "right_3q"
    if any(s in prompt_lower for s in _LEFT_PROFILE_SIGNALS):
        return "left_profile"
    if any(s in prompt_lower for s in _RIGHT_PROFILE_SIGNALS):
        return "right_profile"
    if any(s in prompt_lower for s in _FULL_BODY_SIGNALS):
        return "full_body"
    if any(s in prompt_lower for s in _FRONT_SIGNALS):
        return "front"
    return None  # ambiguous → fallback


def _detect_exposure(prompt_lower: str) -> list[str]:
    """Return list of active body-exposure signal names."""
    active: list[str] = []
    checks = (
        ("shirtless",     _SHIRTLESS_EXPOSURE),
        ("sleeveless",    _SLEEVELESS_EXPOSURE),
        ("rolled_sleeves", _ROLLED_SLEEVE_EXPOSURE),
        ("short_sleeves", _SHORT_SLEEVE_EXPOSURE),
        ("long_sleeves",  _LONG_SLEEVE_EXPOSURE),
        ("jacket",        _JACKET_EXPOSURE),
        ("coat",          _COAT_EXPOSURE),
        ("tattoos_visible", _TATTOOS_VISIBLE_EXPOSURE),
        ("underwear",     _UNDERWEAR_EXPOSURE),
        ("gym",           _GYM_EXPOSURE),
        ("towel",         _TOWEL_EXPOSURE),
        ("wet_shirt",     _WET_SHIRT_EXPOSURE),
    )
    for name, signals in checks:
        if any(s in prompt_lower for s in signals):
            active.append(name)
    return active


def _resolve_route(camera: str, slot_urls: dict[str, str]) -> tuple[list[str], list[str]]:
    """Resolve a camera route to (urls, slot_names) for available canon slots.

    Slots are taken in the camera's weighted priority order; absent canon
    slots are skipped, and the surviving list is capped at MAX_PROVIDER_REFS.
    """
    route_slots = _ROUTES.get(camera, _ROUTES["front"])
    slots_hit = [s for s in route_slots if s in slot_urls][:MAX_PROVIDER_REFS]
    urls = [slot_urls[s] for s in slots_hit]
    return urls, slots_hit


# ── S24AB: exposed/hidden mark partition (audit logging) ──────────────

def _mark_ref_label(mark: object) -> str:
    """Compact human label for a permanent mark in audit logs."""
    label = (getattr(mark, "label", "") or "").strip()
    region = (getattr(mark, "body_region", "") or "").strip()
    side = (getattr(mark, "side", "") or "").strip()
    base = label or str(getattr(mark, "id", "") or "") or "mark"
    return f"{base}@{region}" + (f"/{side}" if side else "")


def _partition_marks(
    canon: "CharacterIdentityCanon", prompt_lower: str, camera: str,
) -> tuple[list, list]:
    """Split permanent marks into (exposed, hidden) for THIS scene.

    Uses the identical per-mark gate the router/compiler apply to crop routing
    (single source of truth). Portrait close-ups carry no body region → every
    mark is treated as hidden (not in frame).
    """
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return [], []
    if camera == "portrait_closeup":
        return [], list(marks)
    exposed: list = []
    hidden: list = []
    for m in marks:
        if _mark_region_exposed(
            getattr(m, "body_region", ""), _is_sleeve_mark(m), prompt_lower
        ):
            exposed.append(m)
        else:
            hidden.append(m)
    return exposed, hidden


# ── Public API ────────────────────────────────────────────────────────

def route_canon_refs(
    prompt: str,
    canon: "CharacterIdentityCanon",
) -> tuple[list[str], SceneMeta]:
    """Select and order canon reference images for a scene prompt.

    Returns (urls, meta):
      urls — prioritised list of reference image URLs to send to the provider.
      meta — SceneMeta with camera orientation, exposure signals, and audit data.

    Routing is deterministic: keyword detection maps the prompt to a camera
    orientation, which selects a fixed slot priority list. Only canon slots
    that have URLs set are included; missing slots are silently skipped.

    Fallback: when the prompt has no detectable camera orientation the
    function returns the P8 reordered canonical sequence from
    collect_canon_reference_urls (meta.routed=False, meta.camera="unknown").
    """
    from app.services.canon_compiler import collect_canon_reference_urls

    prompt_lower = prompt.lower()
    slot_urls = _get_canon_slot_urls(canon)
    camera = _detect_camera(prompt_lower)
    exposure = _detect_exposure(prompt_lower)
    char_id = getattr(canon, "character_id", "?")

    # A clothing- or skin-described scene without an explicit orientation keyword
    # is treated as a front-facing body shot so exposure-gated crop routing can
    # engage. A garment description ("button-up shirt, sleeves rolled to the
    # forearms") OR a skin-exposure cue ("open shirt, arms out at the pool")
    # implies the body is in view even when no camera signal is present. Truly
    # ambiguous prompts (no exposure or skin cue) still fall back.
    if camera is None and (
        exposure or any(s in prompt_lower for s in _SKIN_EXPOSURE_PROMOTION)
    ):
        camera = "front"

    # S24AB: partition marks by this scene's exposure for required-anchor audit.
    exposed_marks, hidden_marks = _partition_marks(canon, prompt_lower, camera or "")
    exposed_regions = [getattr(m, "body_region", "") or "" for m in exposed_marks]
    required_mark_refs = [_mark_ref_label(m) for m in exposed_marks]
    hidden_mark_refs = [_mark_ref_label(m) for m in hidden_marks]

    if camera is None:
        fallback_urls = collect_canon_reference_urls(canon)
        meta = SceneMeta(
            camera="unknown",
            exposure=exposure,
            routed=False,
            route_slots=[],
        )
        logger.info(
            "SCENE_ROUTER char=%s camera=unknown fallback=true exposure=%s refs=%d",
            char_id, exposure, len(fallback_urls),
        )
        logger.info(
            "CANON_EXPOSURE char=%s camera=unknown exposed_regions=%s "
            "required_mark_refs=%s hidden_mark_refs=%s final_anchor_order=%s",
            char_id, exposed_regions, required_mark_refs, hidden_mark_refs, [],
        )
        return fallback_urls, meta

    # P13: exposure-gated cropped-mark routing. When the scene exposes a mark's
    # region, splice its high-fidelity crop ahead of lower-priority refs while
    # guaranteeing body_front + body_map survive. No exposed marks → unchanged.
    crops = _collect_exposed_mark_crops(canon, prompt_lower, camera)
    if crops:
        route_slots = _ROUTES.get(camera, _ROUTES["front"])
        slots_avail = [s for s in route_slots if s in slot_urls]
        slots_hit, urls = _merge_crops(camera, slots_avail, slot_urls, crops)
        crop_count = slots_hit.count("mark_crop")
        # Crops are spliced contiguously right after the lead ref, so the first
        # crop_count bindings are exactly the ones that survived the cap (#1/#3).
        routed_bindings = crops[:crop_count]
    else:
        urls, slots_hit = _resolve_route(camera, slot_urls)
        crop_count = 0
        routed_bindings = []

    meta = SceneMeta(
        camera=camera,
        exposure=exposure,
        routed=True,
        route_slots=slots_hit,
        mark_crops=crop_count,
        mark_crop_bindings=routed_bindings,
    )
    logger.info(
        "SCENE_ROUTER char=%s camera=%s routed=true exposure=%s slots=%s refs=%d crops=%d",
        char_id, camera, exposure, slots_hit, len(urls), crop_count,
    )
    logger.info(
        "CANON_EXPOSURE char=%s camera=%s exposed_regions=%s required_mark_refs=%s "
        "hidden_mark_refs=%s final_anchor_order=%s",
        char_id, camera, exposed_regions, required_mark_refs, hidden_mark_refs, slots_hit,
    )
    return urls, meta
