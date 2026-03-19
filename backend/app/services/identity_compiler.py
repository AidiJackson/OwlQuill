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

# ── B16: Body morphology mappings ────────────────────────────────────

_HEIGHT_MORPHOLOGY: dict[str, str] = {
    "short": "short stature",
    "medium": "average height",
    "tall": "tall stature",
}

_BUILD_MORPHOLOGY: dict[str, str] = {
    "slim": "slim build, narrow shoulders, lean frame",
    "athletic": "athletic build, defined shoulders, balanced physique",
    "muscular": "muscular build, broad shoulders, powerful chest and arms",
    "stocky": "stocky muscular build, broad shoulders, thick neck, compact powerful frame",
    "heavy": "large heavy build, broad torso, thick powerful frame",
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


# ── Species helper ───────────────────────────────────────────────────

def _species_prompt(spec: CharacterIdentitySpec) -> str:
    """Return a species descriptor for non-human characters.

    Human (default) returns an empty string so existing prompts are unaffected.
    For other species, returns a short phrase like
    "vampire character, subtle supernatural tells: subtle fangs, predatory gaze".

    Tells are taken verbatim from spec.species_tells (already validated to be
    PG-13 safe alphanumeric tokens). Underscores are replaced with spaces for
    readability in the generated prompt.
    """
    species_val = getattr(spec, "species", "human")
    # Handle both enum instances and plain strings (e.g. loaded from old JSON)
    species_str = species_val.value if hasattr(species_val, "value") else str(species_val)
    if not species_str or species_str == "human":
        return ""
    tells = getattr(spec, "species_tells", None) or []
    parts = [f"{species_str} character"]
    if tells:
        readable = [t.replace("_", " ") for t in tells]
        parts.append("subtle supernatural tells: " + ", ".join(readable))
    return ". ".join(parts)


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
        # B15: natural hair description — length + style + texture + colour + "hair"
        _hair_parts: list[str] = []
        if id_.hair_length:
            _hair_parts.append(id_.hair_length.lower())
        if spec.hair_style:
            _hair_parts.append(spec.hair_style.replace("_", " "))
        if spec.hair_texture:
            _hair_parts.append(spec.hair_texture)
        if id_.hair_color:
            _hair_parts.append(id_.hair_color)
        if _hair_parts:
            _hair_parts.append("hair")
            identity_parts.append(" ".join(_hair_parts))
        elif id_.hair_color:
            identity_parts.append(f"{id_.hair_color} hair")

        if id_.eye_color:
            identity_parts.append(f"{id_.eye_color} eyes")
        # B15: eye spacing and eyebrow shape
        if spec.eye_spacing and spec.eye_spacing != "average":
            identity_parts.append(f"{spec.eye_spacing.replace('_', ' ')} eyes")
        if spec.eyebrow_shape:
            identity_parts.append(f"{spec.eyebrow_shape} eyebrows")

        if id_.skin_tone:
            identity_parts.append(f"{id_.skin_tone} skin")

        if id_.face_features:
            identity_parts.extend(id_.face_features[:2])

    # B21: facial geometry — inject structural face traits for generic-face hardening.
    # These are B14 fields on the spec; they are independent of spec.identity being set.
    # Face shape, jaw, nose, and lips are the primary drift axes for generic characters.
    if spec.face_shape:
        identity_parts.append(f"{spec.face_shape.replace('_', ' ')} face shape")
    if spec.jaw_type:
        identity_parts.append(f"{spec.jaw_type.replace('_', ' ')} jaw")
    if spec.cheekbone_type:
        identity_parts.append(f"{spec.cheekbone_type.replace('_', ' ')} cheekbones")
    if spec.eye_shape:
        identity_parts.append(f"{spec.eye_shape.replace('_', ' ')} eye shape")
    if spec.nose_type:
        identity_parts.append(f"{spec.nose_type.replace('_', ' ')} nose")
    if spec.lip_type:
        identity_parts.append(f"{spec.lip_type.replace('_', ' ')} lips")
    if spec.hairline_type:
        identity_parts.append(f"{spec.hairline_type.replace('_', ' ')} hairline")
    if spec.facial_hair_type and spec.facial_hair_type != "none":
        identity_parts.append(spec.facial_hair_type.replace('_', ' '))

    sections.append(", ".join(identity_parts))

    # 3b. Species descriptor (only injected for non-human species)
    species_desc = _species_prompt(spec)
    if species_desc:
        sections.append(species_desc)

    # 4. Neutral studio outfit (fixed; wardrobe field is accepted but ignored)
    sections.append(NEUTRAL_STUDIO_OUTFIT)
    sections.append("Keep this exact outfit unchanged across all 4 shots.")

    # 5. Role shot requirement
    shot_desc = ROLE_SHOT_DESCRIPTION.get(role, "")
    if shot_desc:
        sections.append(shot_desc)

    # 6. Body morphology (B16) + legacy build + marks/accessories
    build_parts: list[str] = []
    # B16: structured height/build take priority over legacy free-text fields
    _body_height = getattr(spec, "body_height", None)
    _body_build = getattr(spec, "body_build", None)
    if _body_height and _body_height in _HEIGHT_MORPHOLOGY:
        build_parts.append(_HEIGHT_MORPHOLOGY[_body_height])
    elif spec.build and spec.build.height_band:
        build_parts.append(spec.build.height_band)
    if _body_build and _body_build in _BUILD_MORPHOLOGY:
        build_parts.append(_BUILD_MORPHOLOGY[_body_build])
    elif spec.build and spec.build.body_type:
        build_parts.append(f"{spec.build.body_type} build")
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

    # B21: core face geometry in lock string so scene/moment prompts stay consistent.
    # Kept to the highest-signal structural traits (shape, jaw, nose, lips) to avoid
    # inflating the lock string; eye_shape and hairline are in the full identity prompt.
    if spec.face_shape:
        parts.append(f"{spec.face_shape.replace('_', ' ')} face")
    if spec.jaw_type:
        parts.append(f"{spec.jaw_type.replace('_', ' ')} jaw")
    if spec.nose_type:
        parts.append(f"{spec.nose_type.replace('_', ' ')} nose")
    if spec.lip_type:
        parts.append(f"{spec.lip_type.replace('_', ' ')} lips")

    # B16: body morphology — include in lock string so scene prompts stay consistent
    _body_height = getattr(spec, "body_height", None)
    _body_build = getattr(spec, "body_build", None)
    if _body_height and _body_height in _HEIGHT_MORPHOLOGY:
        parts.append(_HEIGHT_MORPHOLOGY[_body_height])
    if _body_build and _body_build in _BUILD_MORPHOLOGY:
        parts.append(_BUILD_MORPHOLOGY[_body_build])

    return ", ".join(parts)


def identity_prompt_hash(spec: CharacterIdentitySpec) -> str:
    """Deterministic hash of the identity spec for drift detection."""
    lock_str = compile_identity_lock_string(spec)
    return hashlib.sha256(lock_str.encode()).hexdigest()[:16]
