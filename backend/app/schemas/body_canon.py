"""Schemas for body canon — persistent anatomical markings on a character.

Identity OS Beta (2026-05-30): Added layered canon architecture types.
  FaceCanon          — face identity lock with reference images
  BodyCanon          — anatomy + permanent markings + body reference images
  BodyMarkingCanonItem — explicit permanent-marking type (alias for BodyMarking)
  RemovableAccessoryCanonItem — removable item (mask, chain, jewellery, etc.)
  CharacterCanonState — top-level container for the full canon layering
"""
from __future__ import annotations

import enum
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field


class MarkingType(str, enum.Enum):
    TATTOO = "tattoo"
    SCAR = "scar"
    BURN = "burn"
    BIRTHMARK = "birthmark"


class MarkingPlacement(str, enum.Enum):
    # Arms
    LEFT_UPPER_ARM = "left_upper_arm"
    LEFT_FOREARM = "left_forearm"
    LEFT_FULL_ARM = "left_full_arm"
    RIGHT_UPPER_ARM = "right_upper_arm"
    RIGHT_FOREARM = "right_forearm"
    RIGHT_FULL_ARM = "right_full_arm"
    # Torso
    CHEST = "chest"
    UPPER_BACK = "upper_back"
    LOWER_BACK = "lower_back"
    FULL_BACK = "full_back"
    SIDE = "side"
    RIBS = "ribs"
    ABDOMEN = "abdomen"
    # Neck / face
    NECK = "neck"
    THROAT = "throat"
    RIGHT_CHEEK = "right_cheek"
    LEFT_CHEEK = "left_cheek"
    FOREHEAD = "forehead"
    CHIN = "chin"
    JAW = "jaw"
    # Hands / legs
    LEFT_HAND = "left_hand"
    RIGHT_HAND = "right_hand"
    KNUCKLES = "knuckles"
    LEFT_THIGH = "left_thigh"
    RIGHT_THIGH = "right_thigh"
    LEFT_CALF = "left_calf"
    RIGHT_CALF = "right_calf"


class MarkingSize(str, enum.Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    FULL_SLEEVE = "full_sleeve"
    FULL_BACK = "full_back"


class MarkingCoverage(str, enum.Enum):
    """How much of the body area the marking covers.

    Distinct from MarkingSize so sleeve semantics can be expressed explicitly
    even on markings that use a non-sleeve MarkingSize value.
    """
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    SLEEVE = "sleeve"
    FULL_SLEEVE = "full_sleeve"


class BodyMarkingCreate(BaseModel):
    """Request body for adding a body marking."""
    type: MarkingType
    placement: MarkingPlacement
    style: str = Field(..., min_length=1, max_length=200,
                       description="Visual style/design, e.g. 'black ink serpent sleeve'")
    size: MarkingSize
    description: str = Field(..., min_length=1, max_length=400,
                              description="Full visual description for identity lock string")
    coverage: Optional[MarkingCoverage] = Field(
        default=None,
        description="Coverage level — inferred from size/style when None. "
                    "sleeve/full_sleeve marks this as hard anatomical identity when the arm is exposed.",
    )


AnchorStatus = Literal["missing", "generated", "locked"]


class BodyMarking(BodyMarkingCreate):
    """A single persisted body marking."""
    id: str = Field(default_factory=lambda: f"bm_{uuid.uuid4().hex[:8]}")
    anchor_image_url: Optional[str] = None
    anchor_status: AnchorStatus = "missing"
    anchor_prompt: Optional[str] = None

    model_config = {"from_attributes": True}


class BodyMarkingRead(BodyMarking):
    """Body marking as returned from the API — includes computed compact_token."""
    compact_token: str


class BodyCanonRead(BaseModel):
    """Full body canon response."""
    character_id: int
    markings: list[BodyMarkingRead]


# ── Identity OS Beta: Layered Canon Architecture ──────────────────────

# Explicit type alias — permanent markings ARE body canon, not accessories.
BodyMarkingCanonItem = BodyMarking


class BodyCanonRefImages(BaseModel):
    """Reference image URLs for the body canon.

    All slots are optional — generation proceeds without them.
    body_front is the primary body truth; others supplement it.
    """
    body_front: Optional[str] = None
    body_left: Optional[str] = None
    body_right: Optional[str] = None
    body_back: Optional[str] = None
    body_map: Optional[str] = None
    final_character_card: Optional[str] = None


class BodyCanon(BaseModel):
    """Complete body canon — anatomy + permanent markings + reference images.

    Permanent tattoos, scars, birthmarks, and moles are body truth.
    They are injected into generation prompts as locked anatomical fact,
    not as accessories or styling layers.
    """
    height: Optional[str] = None           # short | medium | tall
    build: Optional[str] = None            # slim | athletic | muscular | stocky | heavy
    proportions: Optional[str] = None      # free-text body proportion notes
    skin_tone: Optional[str] = None        # e.g. "olive", "deep brown", "fair"
    posture: Optional[str] = None          # e.g. "upright", "slightly hunched"
    body_shape: Optional[str] = None       # free-text body shape notes
    permanent_markings: list[BodyMarkingCanonItem] = Field(default_factory=list)
    ref_images: BodyCanonRefImages = Field(default_factory=BodyCanonRefImages)


class FaceCanonRefImages(BaseModel):
    """Reference image URLs for the face canon."""
    face_front: Optional[str] = None
    face_three_quarter_left: Optional[str] = None
    face_three_quarter_right: Optional[str] = None


class FaceCanon(BaseModel):
    """Face identity lock — all facial geometry and reference images.

    Controls face identity only. Does not include body, accessories, or scene data.
    """
    gender: Optional[str] = None
    age_band: Optional[str] = None
    hair_color: Optional[str] = None
    hair_length: Optional[str] = None
    hair_texture: Optional[str] = None
    eye_color: Optional[str] = None
    skin_tone: Optional[str] = None
    face_shape: Optional[str] = None
    jaw_type: Optional[str] = None
    nose_type: Optional[str] = None
    lip_type: Optional[str] = None
    face_features: list[str] = Field(default_factory=list)
    ref_images: FaceCanonRefImages = Field(default_factory=FaceCanonRefImages)


class RemovableAccessoryCanonItem(BaseModel):
    """A removable accessory — only injected into prompts when explicitly requested.

    Removable accessories (mask, chain, jewellery, weapons, glasses, clothing)
    are separate from body canon. They do NOT appear in generation unless the
    scene prompt requests them.
    """
    id: str = Field(default_factory=lambda: f"acc_{uuid.uuid4().hex[:8]}")
    label: str = Field(..., min_length=1, max_length=100,
                       description="Display name, e.g. 'Venetian mask', 'gold chain necklace'")
    prompt_token: str = Field(..., min_length=1, max_length=200,
                              description="Token injected into prompt when accessory is requested")
    trigger_keywords: list[str] = Field(
        default_factory=list,
        description="Scene prompt keywords that trigger this accessory (e.g. ['mask', 'masked'])",
    )
    fit_image_url: Optional[str] = None
    design_image_url: Optional[str] = None


class CharacterCanonState(BaseModel):
    """Top-level canon state for a character — the ground truth for all generation.

    Layer order (strict):
      1. face_canon      — face identity; always first in prompts
      2. body_canon      — anatomy + permanent markings; always second
      3. accessories     — removable only; injected only when requested
      4. scene prompt    — user intent; lowest priority; cannot override canon

    Hard rule: scene images must NEVER automatically update canon.
    Promotion is always explicit via promote_to_canon flow.
    """
    character_id: int
    face_canon: Optional[FaceCanon] = None
    body_canon: Optional[BodyCanon] = None
    accessories: list[RemovableAccessoryCanonItem] = Field(default_factory=list)

    # Hard-wired prompt enforcement clause injected at the end of all identity prompts.
    LOCKED_CANON_CLAUSE: str = (
        "The character's face, body, proportions, scars, tattoos, birthmarks, "
        "and permanent body markings are locked canon. "
        "Do not redesign, relocate, resize, mirror, reinterpret, remove, or replace them. "
        "Scene, pose, wardrobe, and lighting may change only if they do not conflict with locked canon."
    )

    model_config = {"from_attributes": True}
