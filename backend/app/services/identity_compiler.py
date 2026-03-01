"""Prompt compiler for structured CharacterIdentitySpec.

Compiles a CharacterIdentitySpec into a deterministic image prompt with
strict ordering that ensures wardrobe and identity features are never
dropped or reordered.

Public API:
- ``compile_identity_prompt(spec, role)``  → full generation prompt (≤ 800 chars)
- ``compile_identity_lock_string(spec)``   → short stable identity lock line
"""

import hashlib
import logging
from typing import Optional

from app.schemas.character_visual import CharacterIdentitySpec

logger = logging.getLogger(__name__)

# ── Safety constants ─────────────────────────────────────────────────

_SAFETY_PREFIX = "adult, fully clothed, non-explicit, fashion portrait, tasteful"
_ADULT_ANCHOR = "adult, mid-20s"

_PROMPT_CAP = 800

# ── Style tokens ─────────────────────────────────────────────────────

_STYLE_TOKENS: dict[str, str] = {
    "realistic": "cinematic portrait, realistic",
    "anime": "anime character illustration",
    "cartoon": "stylized cartoon character",
    "illustration": "digital illustration",
    "comic": "comic book style",
    "pixel": "pixel art",
}

# ── Role shot descriptions ───────────────────────────────────────────

ROLE_SHOT_DESCRIPTION: dict[str, str] = {
    "anchor_front": "close-up headshot portrait, straight-on, shoulders visible, face centered",
    "anchor_three_quarter": "three-quarter view, head turned about 45 degrees, angled shoulders",
    "anchor_torso": "mid-torso framing, chest and shoulders visible, face smaller in frame",
    "anchor_full_body": "full-body shot, head-to-toe, standing, natural stance, full outfit visible",
}


# ── Core compiler ────────────────────────────────────────────────────

def compile_identity_prompt(
    spec: CharacterIdentitySpec,
    role: str,
    *,
    char_traits: Optional[list[str]] = None,
    failsafe: bool = False,
) -> str:
    """Compile a structured identity spec into an image generation prompt.

    Strict ordering (each section appended in this order):
      1. Style token
      2. Identity consistency anchor
      3. Adult anchor + identity core (hair, eyes, skin, face)
      4. Wardrobe lock (outfit type + colors) — must be early
      5. Role shot requirement
      6. Build + marks/accessories
      7. Vibe traits (extra_notes) + lighting

    In failsafe mode, wardrobe color/type may be softened (only type kept,
    colors dropped) to avoid moderation blocks.

    Hard cap: 800 characters. Trimming works backwards from section 6,
    preserving wardrobe and identity core.
    """
    sections: list[str] = []

    # 1. Style token
    style_token = _STYLE_TOKENS.get(spec.style, _STYLE_TOKENS["realistic"])
    sections.append(style_token)

    # 2. Identity consistency anchor — canonical singular appearance lock
    sections.append(
        "All images in this identity pack must depict the exact same person with identical hairstyle, hair length,"
        " hair position, facial hair, facial structure, and overall appearance. Choose one definitive version of"
        " the described hairstyle and keep it consistent across all angles. Do not vary hair position, hair length,"
        " or facial hair between shots."
    )

    # 3. Adult anchor + identity core
    identity_parts: list[str] = [_ADULT_ANCHOR]

    # Character name/species/gender from char_traits
    if char_traits:
        identity_parts.extend(t for t in char_traits if t)

    if spec.identity:
        id_ = spec.identity
        if id_.hair_color and id_.hair_length:
            identity_parts.append(f"{id_.hair_length} {id_.hair_color} hair")
        elif id_.hair_color:
            identity_parts.append(f"{id_.hair_color} hair")
        elif id_.hair_length:
            identity_parts.append(f"{id_.hair_length} hair")

        if id_.eye_color:
            identity_parts.append(f"{id_.eye_color} eyes")

        if id_.skin_tone:
            identity_parts.append(f"{id_.skin_tone} skin")

        if id_.face_features:
            identity_parts.extend(id_.face_features[:2])

    sections.append(", ".join(identity_parts))

    # 4. Wardrobe lock — must appear early for stable generation
    wardrobe_str = _build_wardrobe_string(spec, failsafe=failsafe)
    if wardrobe_str:
        sections.append(wardrobe_str)

    # 4b. Canonical outfit enforcement lock
    if wardrobe_str:
        sections.append(
            "The outfit described above is canonical for this identity pack. "
            "Do not substitute, add, remove, or alter any clothing items between shots. "
            "Keep the exact same outfit across front, 3/4, torso, and full-body images."
        )

    # 5. Role shot requirement
    shot_desc = ROLE_SHOT_DESCRIPTION.get(role, "")
    if shot_desc:
        sections.append(shot_desc)

    # 6. Build + marks/accessories
    build_parts: list[str] = []
    if spec.build:
        if spec.build.body_type:
            build_parts.append(f"{spec.build.body_type} build")
        if spec.build.height_band:
            build_parts.append(spec.build.height_band)
    if spec.marks_accessories and spec.marks_accessories.items:
        build_parts.extend(spec.marks_accessories.items)
    if build_parts:
        sections.append(", ".join(build_parts))

    # 7. Vibe traits + lighting (extra_notes)
    if spec.extra_notes:
        sections.append(spec.extra_notes)

    # Assemble with safety prefix
    prompt = f"{_SAFETY_PREFIX}, " + ", ".join(sections)

    # Hard cap at 800 — trim from the end (sections 6, 5 first)
    if len(prompt) > _PROMPT_CAP:
        prompt = _trim_to_cap(prompt, sections, failsafe)

    return prompt


def _build_wardrobe_string(
    spec: CharacterIdentitySpec,
    *,
    failsafe: bool = False,
) -> str:
    """Build the wardrobe portion of the prompt.

    In failsafe mode, drops colors and keeps only the outfit type
    to reduce moderation risk.
    """
    if not spec.wardrobe:
        return ""

    w = spec.wardrobe
    parts: list[str] = []

    if failsafe:
        # Tier C: soften — only outfit type, no colors
        if w.outfit_type:
            parts.append(f"simple {w.outfit_type}")
    else:
        # Full wardrobe spec
        if w.outfit_type and w.primary_color:
            color_str = w.primary_color
            if w.secondary_color:
                color_str = f"{w.primary_color} and {w.secondary_color}"
            parts.append(f"{color_str} {w.outfit_type}")
        elif w.outfit_type:
            parts.append(w.outfit_type)
        elif w.primary_color:
            parts.append(f"{w.primary_color} outfit")

    if not failsafe:
        if w.footwear:
            parts.append(w.footwear)
        if w.accessory:
            parts.append(w.accessory)
        if w.notes:
            parts.append(w.notes)

    return ", ".join(parts) if parts else ""


def _trim_to_cap(
    prompt: str,
    sections: list[str],
    failsafe: bool,
) -> str:
    """Trim prompt to _PROMPT_CAP, removing lower-priority sections first.

    Priority (highest first): style, identity, wardrobe, shot, build, extra_notes
    Removes from the back (extra_notes first, then build) to stay under cap.
    Wardrobe is never removed.
    """
    # Rebuild without extra_notes
    trimmed_sections = sections[:-1] if len(sections) > 6 else sections
    prompt = f"{_SAFETY_PREFIX}, " + ", ".join(trimmed_sections)

    if len(prompt) > _PROMPT_CAP:
        # Also drop build/marks section (index 5 if present, after shot)
        if len(trimmed_sections) > 5:
            trimmed_sections = trimmed_sections[:5] + trimmed_sections[6:]
            prompt = f"{_SAFETY_PREFIX}, " + ", ".join(trimmed_sections)

    # Last resort: hard truncate (but wardrobe is in sections 0-2, safe)
    return prompt[:_PROMPT_CAP]


# ── Identity lock string ─────────────────────────────────────────────

def compile_identity_lock_string(spec: CharacterIdentitySpec) -> str:
    """Produce a short, stable identity lock line for scene generation.

    This is a compact representation of the character's visual identity
    that can be prepended to scene/moment prompts to maintain consistency.
    """
    parts: list[str] = []

    if spec.identity:
        id_ = spec.identity
        if id_.hair_color:
            hair = id_.hair_color
            if id_.hair_length:
                hair = f"{id_.hair_length} {hair}"
            parts.append(f"{hair} hair")
        if id_.eye_color:
            parts.append(f"{id_.eye_color} eyes")
        if id_.skin_tone:
            parts.append(f"{id_.skin_tone} skin")

    if spec.wardrobe:
        w = spec.wardrobe
        if w.primary_color and w.outfit_type:
            parts.append(f"{w.primary_color} {w.outfit_type}")
        elif w.outfit_type:
            parts.append(w.outfit_type)

    if spec.marks_accessories and spec.marks_accessories.items:
        parts.extend(spec.marks_accessories.items[:2])

    return ", ".join(parts)


def identity_prompt_hash(spec: CharacterIdentitySpec) -> str:
    """Deterministic hash of the identity spec for drift detection."""
    lock_str = compile_identity_lock_string(spec)
    return hashlib.sha256(lock_str.encode()).hexdigest()[:16]
