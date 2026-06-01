"""Clean canonical identity schemas — single source of truth.

Four concepts only:
  FaceCanonData          — face identity lock (images + description)
  BodyCanonData          — anatomy + permanent marks (images + description)
  RemovableAccessory     — removable item (mask, chain, glasses, etc.)
  PermanentBodyMark      — locked anatomical truth (tattoo, scar, birthmark, etc.)

SceneImage is output-only and is represented by CharacterImage with kind=SCENE_ONLY.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Permanent body marks ──────────────────────────────────────────────

class PermanentBodyMark(BaseModel):
    """A single permanent body marking — anatomical truth, not an accessory.

    Tattoos, scars, birthmarks, and moles are all PermanentBodyMarks.
    They are part of BodyCanon. They are never accessories.
    They are never removed from prompts unless the body region is covered.
    """
    id: str = Field(default_factory=lambda: f"pbm_{uuid.uuid4().hex[:8]}")
    label: str = Field(..., min_length=1, max_length=100,
                       description="Short display label, e.g. 'Left arm gothic script sleeve'")
    type: Literal["tattoo", "scar", "birthmark", "mole", "body_marking", "other"]
    body_region: str = Field(..., min_length=1, max_length=80,
                             description="Body area, e.g. 'left_full_arm', 'right_cheek'")
    side: Literal["left", "right", "centre", "bilateral"]
    description: str = Field(..., min_length=1, max_length=500,
                              description="Full visual description for prompt injection")
    # Visual fidelity aids for this specific mark. A general reference photo and a
    # tight close-up "detail crop" that captures the exact tattoo geometry /
    # lettering texture. The router prefers detail_crop_url, falling back to
    # reference_image_url, and only routes one when the mark's region is exposed.
    reference_image_url: Optional[str] = None
    detail_crop_url: Optional[str] = None
    locked: bool = False

    model_config = {"from_attributes": True}


# ── Face canon ────────────────────────────────────────────────────────

class FaceCanonData(BaseModel):
    """Face identity lock — controls face across all generation.

    Images are source of truth for the provider.
    face_description supplements image refs in text form.
    Once locked, scene generation cannot alter face identity.
    """
    face_front_image_url: Optional[str] = None
    face_left_3q_image_url: Optional[str] = None
    face_right_3q_image_url: Optional[str] = None
    face_expression_image_url: Optional[str] = None
    face_description: Optional[str] = Field(
        default=None, max_length=500,
        description="Text description of face identity for prompt injection",
    )
    locked: bool = False

    model_config = {"from_attributes": True}


# ── Body canon ────────────────────────────────────────────────────────

class BodyCanonData(BaseModel):
    """Body canon — anatomy, proportions, and permanent markings.

    Permanent marks (tattoos, scars, birthmarks) are PermanentBodyMarks inside
    this object. They are injected into every prompt as locked anatomical fact.
    They are NEVER accessories. They are NEVER removable from the prompt.
    """
    body_front_image_url: Optional[str] = None
    body_left_image_url: Optional[str] = None
    body_right_image_url: Optional[str] = None
    body_back_image_url: Optional[str] = None
    body_map_image_url: Optional[str] = None
    final_character_card_image_url: Optional[str] = None

    height: Optional[str] = None            # short | medium | tall
    build: Optional[str] = None             # slim | athletic | muscular | stocky | heavy
    proportions: Optional[str] = Field(default=None, max_length=200)
    skin_tone: Optional[str] = None
    body_description: Optional[str] = Field(
        default=None, max_length=500,
        description="Full body description for prompt injection",
    )

    permanent_body_marks: list[PermanentBodyMark] = Field(default_factory=list)
    locked: bool = False

    model_config = {"from_attributes": True}


# ── Removable accessory ───────────────────────────────────────────────

class RemovableAccessory(BaseModel):
    """A removable accessory — only injected when explicitly requested.

    Examples: mask, chain necklace, jewellery, glasses, weapon, clothing.
    NOT tattoos. NOT scars. NOT birthmarks.
    Injected into prompts only when the scene prompt contains a trigger keyword.
    """
    id: str = Field(default_factory=lambda: f"acc_{uuid.uuid4().hex[:8]}")
    label: str = Field(..., min_length=1, max_length=100)
    type: Literal["mask", "jewellery", "weapon", "glasses", "clothing", "other"]
    description: str = Field(..., min_length=1, max_length=300,
                              description="Prompt token injected when accessory is requested")
    design_anchor_image_url: Optional[str] = None
    fit_anchor_image_url: Optional[str] = None
    trigger_keywords: list[str] = Field(
        default_factory=list,
        description="Scene prompt keywords that trigger this accessory (e.g. ['mask', 'masked'])",
    )
    locked: bool = False

    model_config = {"from_attributes": True}


# ── Top-level read/write schemas ──────────────────────────────────────

class CharacterCanonRead(BaseModel):
    """Full canon state for a character — returned from GET /identity-canon."""
    id: int
    character_id: int
    status: str  # draft | locked
    face_canon: Optional[FaceCanonData] = None
    body_canon: Optional[BodyCanonData] = None
    accessories: list[RemovableAccessory] = Field(default_factory=list)
    face_locked: bool
    body_locked: bool
    created_at: datetime
    updated_at: datetime
    locked_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class FaceCanonUpdate(BaseModel):
    """PATCH body for updating face canon fields."""
    face_front_image_url: Optional[str] = None
    face_left_3q_image_url: Optional[str] = None
    face_right_3q_image_url: Optional[str] = None
    face_expression_image_url: Optional[str] = None
    face_description: Optional[str] = Field(default=None, max_length=500)


class BodyCanonUpdate(BaseModel):
    """PATCH body for updating body canon anatomy fields (not marks — use separate endpoint)."""
    body_front_image_url: Optional[str] = None
    body_left_image_url: Optional[str] = None
    body_right_image_url: Optional[str] = None
    body_back_image_url: Optional[str] = None
    body_map_image_url: Optional[str] = None
    final_character_card_image_url: Optional[str] = None
    height: Optional[str] = None
    build: Optional[str] = None
    proportions: Optional[str] = Field(default=None, max_length=200)
    skin_tone: Optional[str] = None
    body_description: Optional[str] = Field(default=None, max_length=500)


class AddPermanentMarkRequest(BaseModel):
    """Request body for adding a permanent body mark to body canon."""
    label: str = Field(..., min_length=1, max_length=100)
    type: Literal["tattoo", "scar", "birthmark", "mole", "body_marking", "other"]
    body_region: str = Field(..., min_length=1, max_length=80)
    side: Literal["left", "right", "centre", "bilateral"]
    description: str = Field(..., min_length=1, max_length=500)
    reference_image_url: Optional[str] = None
    detail_crop_url: Optional[str] = None


class AddAccessoryRequest(BaseModel):
    """Request body for adding a removable accessory."""
    label: str = Field(..., min_length=1, max_length=100)
    type: Literal["mask", "jewellery", "weapon", "glasses", "clothing", "other"]
    description: str = Field(..., min_length=1, max_length=300)
    trigger_keywords: list[str] = Field(default_factory=list)
    design_anchor_image_url: Optional[str] = None
    fit_anchor_image_url: Optional[str] = None


# ── Admin upload slot mapping ─────────────────────────────────────────

CANON_UPLOAD_SLOTS = frozenset({
    # Face canon
    "face_front",
    "face_left_3q",
    "face_right_3q",
    "face_expression",
    # Body canon
    "body_front",
    "body_left",
    "body_right",
    "body_back",
    "body_map",
    "final_character_card",
    # Per-mark reference (uses mark_id param separately)
    "mark_reference",
    # Accessory
    "accessory_design",
    "accessory_fit",
})

# Slot → (canon section, field name on FaceCanonData or BodyCanonData)
SLOT_FIELD_MAP: dict[str, tuple[str, str]] = {
    "face_front":             ("face", "face_front_image_url"),
    "face_left_3q":           ("face", "face_left_3q_image_url"),
    "face_right_3q":          ("face", "face_right_3q_image_url"),
    "face_expression":        ("face", "face_expression_image_url"),
    "body_front":             ("body", "body_front_image_url"),
    "body_left":              ("body", "body_left_image_url"),
    "body_right":             ("body", "body_right_image_url"),
    "body_back":              ("body", "body_back_image_url"),
    "body_map":               ("body", "body_map_image_url"),
    "final_character_card":   ("body", "final_character_card_image_url"),
}
