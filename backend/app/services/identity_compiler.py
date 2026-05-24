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

# ── B34: Hair + stature fidelity constants ────────────────────────────

# Curl textures that are prone to softening drift under model resampling
_CURL_TEXTURES = frozenset({"curly", "coily"})

# Hair length keywords that signal long hair needing explicit length lock
_LONG_HAIR_KEYWORDS = frozenset({
    "long", "waist", "hip", "hips", "mid-back", "mid back", "waist-length",
})

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
    # Named sections: list[tuple[name, content]] — name is used by _trim_to_cap
    # to remove lower-priority sections without index coupling.
    sections: list[tuple[str, str]] = []

    # 1. Style token
    style_token = _STYLE_TOKENS.get(spec.style, _STYLE_TOKENS["realistic"])
    sections.append(("style", style_token))

    # 2. Identity consistency anchor — canonical singular appearance lock
    # B34: conditionally extend with hair texture/length locks to prevent drift
    _anchor = (
        "Same person across all shots. Identical face, hair, skin, and overall appearance. "
        "No variation in hair length, facial hair, or facial structure between angles."
    )
    _htex = getattr(spec, "hair_texture", None)
    if _htex in _CURL_TEXTURES:
        _anchor += " Curl pattern locked — do not soften into waves, do not alter curl definition."
    if spec.identity and spec.identity.hair_length:
        _hl = spec.identity.hair_length.lower()
        if any(kw in _hl for kw in _LONG_HAIR_KEYWORDS):
            _anchor += f" Hair length is {_hl} — do not shorten."
    sections.append(("anchor", _anchor))

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
            # B34: curl enforcement clause — repeated in identity section as anchor
            if spec.hair_texture in _CURL_TEXTURES:
                identity_parts.append("maintain curl definition")
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

    sections.append(("identity", ", ".join(identity_parts)))

    # 3b. Species descriptor (only injected for non-human species)
    species_desc = _species_prompt(spec)
    if species_desc:
        sections.append(("species", species_desc))

    # 4. Neutral studio outfit (fixed; wardrobe field is accepted but ignored)
    sections.append(("outfit", NEUTRAL_STUDIO_OUTFIT))
    sections.append(("outfit_lock", "Keep this exact outfit unchanged across all 4 shots."))

    # 5. Role shot requirement
    shot_desc = ROLE_SHOT_DESCRIPTION.get(role, "")
    if shot_desc:
        sections.append(("shot", shot_desc))

    # 6. Body morphology (B16 / B34) + legacy build + marks/accessories
    build_parts: list[str] = []
    _body_height = getattr(spec, "body_height", None)
    _body_build = getattr(spec, "body_build", None)
    # B34: petite detection — short + slim together map to a unified petite descriptor
    # with explicit anti-drift to prevent model defaulting to average proportions
    if _body_height == "short" and _body_build == "slim":
        build_parts.append(
            "petite frame, short stature, small frame, narrow shoulders, lighter proportions"
        )
        build_parts.append("do not render as average height or medium build")
    else:
        # B16: structured height/build take priority over legacy free-text fields
        if _body_height and _body_height in _HEIGHT_MORPHOLOGY:
            _h_desc = _HEIGHT_MORPHOLOGY[_body_height]
            # B34: short stature anti-drift — models default to average height
            if _body_height == "short":
                _h_desc += ", do not render as average height"
            build_parts.append(_h_desc)
        elif spec.build and spec.build.height_band:
            build_parts.append(spec.build.height_band)
        if _body_build and _body_build in _BUILD_MORPHOLOGY:
            build_parts.append(_BUILD_MORPHOLOGY[_body_build])
        elif spec.build and spec.build.body_type:
            build_parts.append(f"{spec.build.body_type} build")
    if spec.marks_accessories and spec.marks_accessories.items:
        build_parts.extend(spec.marks_accessories.items)
    if build_parts:
        sections.append(("build", ", ".join(build_parts)))

    # 7. Vibe traits + lighting (extra_notes)
    if spec.extra_notes:
        sections.append(("extra_notes", spec.extra_notes))

    # Assemble with safety prefix
    prompt = f"{_SAFETY_PREFIX}, " + ", ".join(v for _, v in sections)

    # Hard cap at 800 — trim by section name, never by index
    if len(prompt) > _PROMPT_CAP:
        prompt = _trim_to_cap(prompt, sections, failsafe)

    return prompt



# Sections removed first when over cap, in this order (lowest priority first).
# "build" (morphology), "species", "identity", "anchor", "outfit", "style" are never removed.
_TRIM_ORDER = ("extra_notes", "outfit_lock", "shot")


def _trim_to_cap(
    prompt: str,
    sections: list[tuple[str, str]],
    failsafe: bool,
) -> str:
    """Trim prompt to _PROMPT_CAP by removing sections in _TRIM_ORDER.

    Trimming is name-based — immune to index shifts caused by conditional sections
    (species, build, shot).  Protected sections (identity, species, build, outfit)
    are never removed regardless of prompt length.  Last resort: hard truncate.
    """
    working = list(sections)
    for name in _TRIM_ORDER:
        working = [(n, v) for n, v in working if n != name]
        prompt = f"{_SAFETY_PREFIX}, " + ", ".join(v for _, v in working)
        if len(prompt) <= _PROMPT_CAP:
            return prompt
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
            # B34: include texture in lock string so scene prompts carry curl identity
            _lock_hair: list[str] = []
            if id_.hair_length:
                _lock_hair.append(id_.hair_length)
            _ltex = getattr(spec, "hair_texture", None)
            if _ltex:
                _lock_hair.append(_ltex)
            _lock_hair.append(id_.hair_color)
            parts.append(" ".join(_lock_hair) + " hair")
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

    # B16 / B34: body morphology — include in lock string so scene prompts stay consistent
    _body_height = getattr(spec, "body_height", None)
    _body_build = getattr(spec, "body_build", None)
    if _body_height == "short" and _body_build == "slim":
        # B34: petite unified descriptor in lock string
        parts.append("petite frame, short stature")
    else:
        if _body_height and _body_height in _HEIGHT_MORPHOLOGY:
            parts.append(_HEIGHT_MORPHOLOGY[_body_height])
        if _body_build and _body_build in _BUILD_MORPHOLOGY:
            parts.append(_BUILD_MORPHOLOGY[_body_build])

    return ", ".join(parts)


def identity_prompt_hash(spec: CharacterIdentitySpec) -> str:
    """Deterministic hash of the identity spec for drift detection."""
    lock_str = compile_identity_lock_string(spec)
    return hashlib.sha256(lock_str.encode()).hexdigest()[:16]
