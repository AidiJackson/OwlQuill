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


# ── Routing rules: camera → ordered slot names ────────────────────────
# Slots listed in priority order. Missing canon slots are skipped silently.
# front and full_body use the same set (6 slots = exact provider cap).

_ROUTES: dict[str, list[str]] = {
    "front": [
        "face_front", "face_left_3q", "face_right_3q",
        "body_front", "body_map", "final_character_card",
    ],
    "full_body": [
        "face_front", "face_left_3q", "face_right_3q",
        "body_front", "body_map", "final_character_card",
    ],
    "back": [
        "body_back", "body_map", "final_character_card",
    ],
    "left_profile": [
        "face_left_3q", "body_left", "body_map", "final_character_card",
    ],
    "right_profile": [
        "face_right_3q", "body_right", "body_map", "final_character_card",
    ],
    "left_3q": [
        "face_left_3q", "body_left", "body_map", "final_character_card",
    ],
    "right_3q": [
        "face_right_3q", "body_right", "body_map", "final_character_card",
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
    """Resolve a camera route to (urls, slot_names) for available canon slots."""
    route_slots = _ROUTES.get(camera, _ROUTES["front"])
    urls = [slot_urls[s] for s in route_slots if s in slot_urls]
    slots_hit = [s for s in route_slots if s in slot_urls]
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

    urls, slots_hit = _resolve_route(camera, slot_urls)
    meta = SceneMeta(
        camera=camera,
        exposure=exposure,
        routed=True,
        route_slots=slots_hit,
    )
    logger.info(
        "SCENE_ROUTER char=%s camera=%s routed=true exposure=%s slots=%s refs=%d",
        char_id, camera, exposure, slots_hit, len(urls),
    )
    return urls, meta
