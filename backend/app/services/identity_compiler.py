"""Prompt compiler for structured CharacterIdentitySpec.

Compiles a CharacterIdentitySpec into a deterministic image prompt with
strict ordering that ensures identity features are never dropped or reordered.

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

_PROMPT_CAP = 800

# Neutral studio outfit enforced for ALL identity pack generation.
# Keeps the focus on facial/physical identity; outfits come after identity lock.
NEUTRAL_STUDIO_OUTFIT = "plain fitted neutral studio outfit designed to show body proportions clearly"

# ── Style tokens ─────────────────────────────────────────────────────

_GENDER_NOUN: dict[str, str] = {
    "male": "man",
    "female": "woman",
    "other": "person",
}

_STYLE_TOKENS: dict[str, str] = {
    "realistic": "cinematic portrait, realistic",
    "anime": "anime character illustration",
    "cartoon": "stylized cartoon character",
    "illustration": "digital illustration",
    "comic": "comic book style",
    "pixel": "pixel art",
    "cinematic": "cinematic portrait, film photography",
    "3d_animated": "3D animated character, stylized render",
}

# ── Role shot descriptions ───────────────────────────────────────────

ROLE_SHOT_DESCRIPTION: dict[str, str] = {
    "anchor_front": (
        "Passport-style headshot. NO sitting, NO crouching, NO full-body, NO hands. "
        "Head-and-shoulders only, straight-on camera, cropped mid-chest. "
        "Neutral expression, plain neutral background, even lighting. "
        "NO crossed arms, NO props, NO dramatic pose."
    ),
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
      3. Identity anchor (gender + style + age_band) + identity core (hair, eyes, skin, face)
      4. Neutral studio outfit (fixed — wardrobe field is ignored)
      5. Role shot requirement
      6. Build + marks/accessories
      7. Vibe traits (extra_notes) + lighting

    Hard cap: 800 characters. Trimming works backwards from section 6,
    preserving identity anchor and outfit.
    """
    sections: list[str] = []

    # 1. Style token
    style_token = _STYLE_TOKENS.get(spec.style, _STYLE_TOKENS["realistic"])
    sections.append(style_token)

    # 2. Identity consistency anchor — canonical singular appearance lock
    sections.append(
        "Same person across all shots. Identical face, hair, skin, and overall appearance. "
        "No variation in hair length, facial hair, or facial structure between angles."
    )

    # 3. Identity anchor: gender + style + age band + identity core
    gender_noun = _GENDER_NOUN.get(spec.gender, spec.gender)
    identity_parts: list[str] = [
        f"adult {gender_noun}",
        f"{spec.style} style",
        f"age range {spec.age_band}",
    ]

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

    # 4. Neutral studio outfit (fixed; wardrobe field is accepted but ignored)
    sections.append(NEUTRAL_STUDIO_OUTFIT)
    sections.append("Keep this exact outfit unchanged across all 4 shots.")

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



def _trim_to_cap(
    prompt: str,
    sections: list[str],
    failsafe: bool,
) -> str:
    """Trim prompt to _PROMPT_CAP, removing lower-priority sections first.

    Priority (highest first): style, identity anchor, outfit, shot, build, extra_notes
    Removes from the back (extra_notes first, then build) to stay under cap.
    Outfit (neutral studio) is never removed.
    """
    # Rebuild without extra_notes
    trimmed_sections = sections[:-1] if len(sections) > 6 else sections
    prompt = f"{_SAFETY_PREFIX}, " + ", ".join(trimmed_sections)

    if len(prompt) > _PROMPT_CAP:
        # Drop build/marks section (index 6, after shot_desc at index 5)
        if len(trimmed_sections) > 6:
            trimmed_sections = trimmed_sections[:6] + trimmed_sections[7:]
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
