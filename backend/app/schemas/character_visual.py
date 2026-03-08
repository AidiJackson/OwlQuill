"""Schemas for character visual endpoints (identity pack + moment generation)."""
import enum
import re as _re
from typing import Literal, Optional
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.schemas.character_dna import CharacterDNARead
from app.schemas.character_image import CharacterImageRead

# Accepted style values — unknown values silently coerce to "realistic".
_VALID_STYLES = {"realistic", "anime", "cartoon", "illustration", "comic", "pixel", "cinematic", "3d_animated"}

# Canonical gender values (lowercase).
_VALID_GENDERS = {"male", "female", "other"}

# Aliases → canonical.  Accepts old display labels, locale variants, and
# the previous "Woman"/"Man"/"Non-binary" enum for backward-compatibility.
_GENDER_NORMALISE: dict[str, str] = {
    # canonical
    "male": "male",
    "female": "female",
    "other": "other",
    # common aliases
    "man": "male",
    "m": "male",
    "boy": "male",
    "woman": "female",
    "f": "female",
    "girl": "female",
    # old display labels (backward-compat)
    "non-binary": "other",
    "nonbinary": "other",
    "non_binary": "other",
    "nb": "other",
    "enby": "other",
}

# Accepted age band values.
_VALID_AGE_BANDS = {"18-25", "26-35", "36-50", "50+"}

# Valid characters in species tells (letters, digits, spaces, underscore, hyphen).
_TELL_RE = _re.compile(r'^[a-zA-Z0-9 _\-]{1,32}$')

# ── Facial geometry enum sets (B14) ──────────────────────────────────

_VALID_FACE_SHAPES = {"oval", "square", "angular", "round", "long"}
_VALID_JAW_TYPES = {"sharp", "square", "soft", "narrow"}
_VALID_CHEEKBONE_TYPES = {"high", "subtle", "wide"}
_VALID_EYE_SHAPES = {"almond", "round", "narrow", "deep_set"}
_VALID_EYE_SPACINGS = {"close_set", "average", "wide_set"}
_VALID_BROW_TYPES = {"straight", "arched", "thick", "sharp"}
_VALID_NOSE_TYPES = {"straight", "narrow", "broad", "hooked", "roman", "upturned"}
_VALID_LIP_TYPES = {"thin", "balanced", "full", "cupid_bow"}
_VALID_HAIRLINE_TYPES = {"straight", "receding", "widows_peak", "messy"}
_VALID_FACIAL_HAIR_TYPES = {
    "none", "stubble", "short_beard", "full_beard",
    "long_beard", "mustache", "goatee",
}

# ── B15 new fields ────────────────────────────────────────────────────
_VALID_HAIR_TEXTURES = {"straight", "wavy", "curly", "coily", "messy"}
_VALID_HAIR_STYLES = {"loose", "layered", "tied_back", "side_parted", "slicked_back", "short_cut"}
_VALID_EYEBROW_SHAPES = {"soft", "arched", "straight", "sharp", "thick", "thin"}

_FACIAL_GEOMETRY_FIELD_MAP: dict[str, set[str]] = {
    "face_shape": _VALID_FACE_SHAPES,
    "jaw_type": _VALID_JAW_TYPES,
    "cheekbone_type": _VALID_CHEEKBONE_TYPES,
    "eye_shape": _VALID_EYE_SHAPES,
    "eye_spacing": _VALID_EYE_SPACINGS,
    "brow_type": _VALID_BROW_TYPES,
    "nose_type": _VALID_NOSE_TYPES,
    "lip_type": _VALID_LIP_TYPES,
    "hairline_type": _VALID_HAIRLINE_TYPES,
    "facial_hair_type": _VALID_FACIAL_HAIR_TYPES,
    # B15
    "hair_texture": _VALID_HAIR_TEXTURES,
    "hair_style": _VALID_HAIR_STYLES,
    "eyebrow_shape": _VALID_EYEBROW_SHAPES,
}


class SpeciesEnum(str, enum.Enum):
    """Canonical species values for CharacterIdentitySpec."""
    HUMAN = "human"
    VAMPIRE = "vampire"
    WEREWOLF = "werewolf"
    WITCH = "witch"
    DEMON = "demon"
    ANGEL = "angel"
    FAE = "fae"
    OTHER = "other"


# ── Structured Character Identity Spec ───────────────────────────────

class IdentityCore(BaseModel):
    """Core facial/physical identity features."""
    hair_color: Optional[str] = None
    hair_length: Optional[str] = None
    eye_color: Optional[str] = None
    skin_tone: Optional[str] = None
    face_features: Optional[list[str]] = Field(default=None, max_length=2)

class IdentityBuild(BaseModel):
    """Body type and height band (no numeric height)."""
    body_type: Optional[str] = None
    height_band: Optional[str] = None  # e.g. "short", "average", "tall"

class IdentityMarksAccessories(BaseModel):
    """Distinguishing marks and identity accessories."""
    items: Optional[list[str]] = None  # e.g. ["glasses", "scar on left cheek", "sleeve tattoo"]

class WardrobeSpec(BaseModel):
    """Wardrobe preset for stable outfit generation."""
    outfit_type: Optional[str] = None    # e.g. "dress", "suit", "armor", "casual", "uniform"
    primary_color: Optional[str] = None  # e.g. "black", "red", "navy"
    secondary_color: Optional[str] = None
    footwear: Optional[str] = None       # e.g. "heels", "boots", "sneakers", "barefoot"
    accessory: Optional[str] = None      # e.g. "necklace", "watch", "belt"
    notes: Optional[str] = Field(default=None, max_length=80)

class CharacterIdentitySpec(BaseModel):
    """Structured identity specification for stable character generation.

    Replaces the free-text 'visual vibe' with typed fields that the prompt
    compiler can assemble in a deterministic order, ensuring identity
    features are never dropped or reordered.

    gender and age_band are required — generation is rejected without them.
    gender normalises to lowercase canonical: male | female | other.
    Aliases accepted: man→male, woman→female, non-binary→other, etc.
    wardrobe is accepted for backward-compatibility but ignored; the backend
    always enforces a neutral studio outfit during identity generation.
    """
    style: str = "realistic"
    gender: str = Field(..., description="Character gender: male, female, or other (aliases: man/woman/non-binary)")
    age_band: str = Field(..., description="Age range: 18-25, 26-35, 36-50, or 50+")
    species: SpeciesEnum = SpeciesEnum.HUMAN
    species_tells: list[str] = Field(default_factory=list, description="Up to 3 subtle visual tells for non-human species (e.g. subtle_fangs, golden_eyes)")
    identity: Optional[IdentityCore] = None
    build: Optional[IdentityBuild] = None
    marks_accessories: Optional[IdentityMarksAccessories] = None
    wardrobe: Optional[WardrobeSpec] = None  # accepted but ignored — neutral outfit enforced
    extra_notes: Optional[str] = Field(default=None, max_length=120)

    # ── Facial geometry (B14) — all optional, backward-compatible ────
    face_shape: Optional[str] = None        # oval | square | angular | round | long
    jaw_type: Optional[str] = None          # sharp | square | soft | narrow
    cheekbone_type: Optional[str] = None    # high | subtle | wide
    eye_shape: Optional[str] = None         # almond | round | narrow | deep_set
    eye_spacing: Optional[str] = None       # close_set | average | wide_set
    brow_type: Optional[str] = None         # straight | arched | thick | sharp
    nose_type: Optional[str] = None         # straight | narrow | broad | hooked | roman | upturned
    lip_type: Optional[str] = None          # thin | balanced | full | cupid_bow
    hairline_type: Optional[str] = None     # straight | receding | widows_peak | messy
    facial_hair_type: Optional[str] = None  # none | stubble | short_beard | full_beard | long_beard | mustache | goatee

    # ── B15 — all optional, backward-compatible ───────────────────────
    hair_texture: Optional[str] = None   # straight | wavy | curly | coily | messy
    hair_style: Optional[str] = None     # loose | layered | tied_back | side_parted | slicked_back | short_cut
    eyebrow_shape: Optional[str] = None  # soft | arched | straight | sharp | thick | thin

    @field_validator("style", mode="before")
    @classmethod
    def _coerce_style(cls, v) -> str:
        if not isinstance(v, str) or not v.strip():
            return "realistic"
        normed = v.strip().lower()
        return normed if normed in _VALID_STYLES else "realistic"

    @field_validator("gender", mode="before")
    @classmethod
    def _validate_gender(cls, v) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("gender is required: male, female, or other")
        normed = _GENDER_NORMALISE.get(v.strip().lower())
        if normed is None:
            raise ValueError(
                f"gender must be one of: {', '.join(sorted(_VALID_GENDERS))} "
                f"(also accepts: man, woman, non-binary)"
            )
        return normed

    @field_validator("age_band", mode="before")
    @classmethod
    def _validate_age_band(cls, v) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("age_band is required (18-25, 26-35, 36-50, or 50+)")
        stripped = v.strip()
        if stripped not in _VALID_AGE_BANDS:
            raise ValueError(f"age_band must be one of: {', '.join(sorted(_VALID_AGE_BANDS))}")
        return stripped

    @field_validator("species_tells", mode="before")
    @classmethod
    def _validate_species_tells(cls, v) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("species_tells must be a list")
        if len(v) > 3:
            raise ValueError("species_tells may contain at most 3 items")
        for tell in v:
            if not isinstance(tell, str):
                raise ValueError("each species tell must be a string")
            if not _TELL_RE.match(tell):
                raise ValueError(
                    f"species tell {tell!r} is invalid — use letters, digits, spaces, "
                    "underscores, or hyphens only (max 32 chars)"
                )
        return v

    @field_validator(
        "face_shape", "jaw_type", "cheekbone_type",
        "eye_shape", "eye_spacing", "brow_type",
        "nose_type", "lip_type", "hairline_type", "facial_hair_type",
        "hair_texture", "hair_style", "eyebrow_shape",
        mode="before",
    )
    @classmethod
    def _validate_facial_geometry(cls, v: object, info: ValidationInfo) -> Optional[str]:
        """Accept None/empty string (optional); otherwise enforce strict enum."""
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise ValueError(f"{info.field_name} must be a string or null")
        normed = v.strip().lower()
        valid_set = _FACIAL_GEOMETRY_FIELD_MAP.get(info.field_name, set())
        if valid_set and normed not in valid_set:
            raise ValueError(
                f"{info.field_name} must be one of: {', '.join(sorted(valid_set))}"
            )
        return normed


# ── Identity Pack Generate ───────────────────────────────────────────

class IdentityPackTweaks(BaseModel):
    """Optional tweaks applied when generating an identity pack preview."""
    age_band: Optional[str] = None
    facial_structure: Optional[str] = None
    skin_texture: Optional[str] = None
    hair: Optional[str] = None
    expression: Optional[str] = None
    signature_feature: Optional[str] = None


class IdentityPackGenerateRequest(BaseModel):
    """Request body for POST /identity-pack/generate."""
    tweaks: Optional[IdentityPackTweaks] = None
    prompt_vibe: Optional[str] = Field(None, max_length=250)
    identity_spec: Optional[CharacterIdentitySpec] = None
    style: str = "realistic"

    @field_validator("style", mode="before")
    @classmethod
    def _coerce_style(cls, v) -> str:
        if not isinstance(v, str) or not v.strip():
            return "realistic"
        normed = v.strip().lower()
        return normed if normed in _VALID_STYLES else "realistic"


class IdentityPackGenerateResponse(BaseModel):
    """Response from generating an identity pack preview."""
    pack_id: str
    images: list[CharacterImageRead]
    tier_used: Literal["A", "B", "C", "stub"] = "stub"
    rewrite_applied: bool = False
    blocked_roles: list[str] = Field(default_factory=list)


# ── Identity Pack Accept ─────────────────────────────────────────────

class IdentityPackAcceptRequest(BaseModel):
    """Request body for POST /identity-pack/accept."""
    pack_id: str


class IdentityPackAcceptResponse(BaseModel):
    """Response from accepting an identity pack."""
    anchors: list[CharacterImageRead]
    dna: Optional[CharacterDNARead] = None


# ── Moment (Post-Lock) Image Generation ──────────────────────────────

class MomentGenerateRequest(BaseModel):
    """Request body for POST /images/generate (post-lock moments)."""
    outfit: Optional[str] = None
    mood: Optional[str] = None
    environment: Optional[str] = None
    hair: Optional[str] = None
    facial_hair: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)


# ── Identity Sketch Anchor ────────────────────────────────────────────

_VALID_SKETCH_STYLES = {"pencil", "charcoal", "dossier"}


class IdentitySketchGenerateRequest(BaseModel):
    """Request body for POST /characters/{id}/identity-sketch/generate."""
    style: str = "pencil"

    @field_validator("style", mode="before")
    @classmethod
    def _coerce_style(cls, v) -> str:
        if not isinstance(v, str) or not v.strip():
            return "pencil"
        normed = v.strip().lower()
        return normed if normed in _VALID_SKETCH_STYLES else "pencil"


class IdentitySketchGenerateResponse(BaseModel):
    """Response from POST /characters/{id}/identity-sketch/generate."""
    image_url: str
    image_id: int
    style: str
    prompt_preview: str
    provider_used: str
