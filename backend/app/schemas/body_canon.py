"""Schemas for body canon — persistent anatomical markings on a character."""
from __future__ import annotations

import enum
import uuid
from typing import Optional

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


class BodyMarkingCreate(BaseModel):
    """Request body for adding a body marking."""
    type: MarkingType
    placement: MarkingPlacement
    style: str = Field(..., min_length=1, max_length=200,
                       description="Visual style/design, e.g. 'black ink serpent sleeve'")
    size: MarkingSize
    description: str = Field(..., min_length=1, max_length=400,
                              description="Full visual description for identity lock string")


class BodyMarking(BodyMarkingCreate):
    """A single persisted body marking."""
    id: str = Field(default_factory=lambda: f"bm_{uuid.uuid4().hex[:8]}")

    model_config = {"from_attributes": True}


class BodyMarkingRead(BodyMarking):
    """Body marking as returned from the API — includes computed compact_token."""
    compact_token: str


class BodyCanonRead(BaseModel):
    """Full body canon response."""
    character_id: int
    markings: list[BodyMarkingRead]
