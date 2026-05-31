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

_LONG_SLEEVE_EXPOSURE = frozenset({
    "long sleeve", "long-sleeve", "long sleeved", "long-sleeved",
})

_JACKET_EXPOSURE = frozenset({
    "jacket", "leather jacket", "blazer",
})

_COAT_EXPOSURE = frozenset({
    "coat", "overcoat", "trenchcoat", "trench coat",
})


# ── Provider reference cap ────────────────────────────────────────────
# Maximum references the provider consumes. The routed slot lists below may
# list one extra "if room" slot (e.g. front's face_expression); anything past
# this cap is dropped after weighting. Mirrors the [:6] cap at the call sites.

MAX_PROVIDER_REFS = 6


# ── P13: exposure-gated cropped-mark reference routing ────────────────
# When a scene exposes the skin region a permanent mark sits on, its high-
# fidelity crop (PermanentBodyMark.reference_image_url) is routed ahead of the
# lower-priority whole-body/face variants. Whole-body cards average tattoo
# detail away; a tight crop preserves geometry. Covered marks are never routed.

# Cap on crops per scene — leaves room for body_front + body_map under the 6-cap.
_MAX_MARK_CROPS = 2

_CROP_FULL_ARM = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso", "sleeveless", "tank top", "tank", "vest",
    "bare arms", "arms bare", "arms out", "arms visible", "both arms visible",
    "swimwear", "swimsuit", "swimming", "swimming pool", "poolside",
    "pool party", "at the pool", "in the pool", "beach", "bikini",
})
_CROP_FOREARM_ONLY = frozenset({
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
    "rolled sleeve", "rolled sleeves", "rolled-up sleeve", "rolled-up sleeves",
    "rolled up sleeve", "rolled up sleeves", "sleeves rolled", "sleeve rolled",
    "sleeves rolled up", "sleeves pushed up", "pushed-up sleeves",
})
_CROP_NECK_EXPOSE = frozenset({
    "open collar", "open shirt", "shirt open", "unbuttoned", "v-neck", "v neck",
    "scoop neck", "low neckline", "deep neckline", "bare neck", "neck visible",
    "shirtless", "bare chest", "tank top", "sleeveless", "swimming",
    "swimming pool", "poolside",
})
_CROP_NECK_COVER = frozenset({
    "turtleneck", "high collar", "scarf", "buttoned-up", "buttoned up",
    "closed collar", "hood up", "balaclava",
})
_CROP_TORSO_EXPOSE = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso", "open shirt", "shirt open", "unbuttoned",
    "swimming", "swimming pool", "poolside", "swimwear", "bikini",
})
_CROP_BACK_EXPOSE = frozenset({
    "shirtless", "bare back", "back visible", "from behind", "back view", "topless",
})


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
    full_arm = any(s in prompt_lower for s in _CROP_FULL_ARM)
    forearm = any(s in prompt_lower for s in _CROP_FOREARM_ONLY)

    # ── Arms ──
    if "forearm" in region or "lower_arm" in region:
        return bool(full_arm or forearm)
    if "upper_arm" in region:
        # forearm-only / rolled sleeves leave the upper arm covered.
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


def _collect_exposed_mark_crops(
    canon: "CharacterIdentityCanon",
    prompt_lower: str,
    camera: str,
) -> list[str]:
    """Return reference-image-crop URLs for permanent marks the scene exposes.

    Portrait close-ups never route body crops. Marks without a
    reference_image_url degrade gracefully (skipped). Capped at _MAX_MARK_CROPS.
    """
    if camera == "portrait_closeup":
        return []
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return []
    crops: list[str] = []
    for m in marks:
        url = getattr(m, "reference_image_url", None)
        if not url:
            continue  # graceful degrade — no crop available for this mark
        if _mark_region_exposed(getattr(m, "body_region", ""), _is_sleeve_mark(m), prompt_lower):
            crops.append(url)
        if len(crops) >= _MAX_MARK_CROPS:
            break
    return crops


def _merge_crops(
    slots_avail: list[str],
    slot_urls: dict[str, str],
    crops: list[str],
) -> tuple[list[str], list[str]]:
    """Splice mark crops in after the lead body ref, guaranteeing body_front +
    body_map survive, then cap at MAX_PROVIDER_REFS.

    Returns (slot_tokens, urls); crop entries use the token 'mark_crop'.
    """
    if not slots_avail:
        crops = crops[:MAX_PROVIDER_REFS]
        return (["mark_crop"] * len(crops), list(crops))

    lead = slots_avail[0]
    rest = slots_avail[1:]
    # body_map + final_character_card must survive (C: card survival).
    must = [s for s in ("body_map", "final_character_card") if s in rest]
    others = [s for s in rest if s not in must]
    ordered = [lead] + ["mark_crop"] * len(crops) + must + others

    crop_iter = iter(crops)
    out_slots: list[str] = []
    out_urls: list[str] = []
    for s in ordered:
        out_urls.append(next(crop_iter) if s == "mark_crop" else slot_urls[s])
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
    "portrait_closeup": [
        "face_front", "face_expression", "final_character_card",
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
        ("long_sleeves",  _LONG_SLEEVE_EXPOSURE),
        ("jacket",        _JACKET_EXPOSURE),
        ("coat",          _COAT_EXPOSURE),
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
        return fallback_urls, meta

    # P13: exposure-gated cropped-mark routing. When the scene exposes a mark's
    # region, splice its high-fidelity crop ahead of lower-priority refs while
    # guaranteeing body_front + body_map survive. No exposed marks → unchanged.
    crops = _collect_exposed_mark_crops(canon, prompt_lower, camera)
    if crops:
        route_slots = _ROUTES.get(camera, _ROUTES["front"])
        slots_avail = [s for s in route_slots if s in slot_urls]
        slots_hit, urls = _merge_crops(slots_avail, slot_urls, crops)
        crop_count = slots_hit.count("mark_crop")
    else:
        urls, slots_hit = _resolve_route(camera, slot_urls)
        crop_count = 0

    meta = SceneMeta(
        camera=camera,
        exposure=exposure,
        routed=True,
        route_slots=slots_hit,
        mark_crops=crop_count,
    )
    logger.info(
        "SCENE_ROUTER char=%s camera=%s routed=true exposure=%s slots=%s refs=%d crops=%d",
        char_id, camera, exposure, slots_hit, len(urls), crop_count,
    )
    return urls, meta
