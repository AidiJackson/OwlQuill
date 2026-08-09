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

from pydantic import BaseModel, Field, model_validator


# ── Card skin-coverage vocabulary ─────────────────────────────────────
#
# One region vocabulary shared by three layers (single source of truth):
#   * per-card coverage metadata (CardCoverage below)
#   * scene coverage detection  (services/card_coverage.py)
#   * PermanentBodyMark.body_region mapping (card_coverage.mark_region_groups)
#
# The tokens are region GROUPS, coarser than PermanentBodyMark.body_region
# ("left_forearm" → "forearms"): a card photographed at canon distance cannot
# meaningfully distinguish left from right coverage, and the router's scene
# exposure sets are already group-level (torso / arm / back / neck).
#
# "face" and "hands" are accepted in metadata for completeness but are treated
# as always visible — they never create a coverage conflict.
COVERAGE_REGIONS = frozenset({
    "torso", "back", "upper_arms", "forearms", "neck", "legs", "face", "hands",
})
ALWAYS_VISIBLE_REGIONS = frozenset({"face", "hands"})

# Creator-facing presets → internal visible_skin_regions. Low-friction UX: a
# creator picks one word; the deterministic expansion below is what routing
# consumes. "custom" requires explicit regions.
COVERAGE_PRESETS: dict[str, tuple[str, ...]] = {
    "fully_clothed": (),
    "short_sleeves": ("forearms",),
    "sleeveless":    ("upper_arms", "forearms"),
    "bare_torso":    ("torso", "upper_arms", "forearms", "neck"),
    "shorts":        ("legs",),
    "swimwear":      ("torso", "upper_arms", "forearms", "neck", "legs"),
}

# Body-bearing canon slots that may carry coverage metadata. Face slots are
# deliberately excluded — face identity references are never coverage-filtered.
CARD_COVERAGE_SLOTS = frozenset({
    "body_front", "body_left", "body_right", "body_back", "body_map",
    "final_character_card", "torso_front", "torso_side",
    "standing_relaxed", "seated_relaxed",
})


class CardCoverage(BaseModel):
    """Skin coverage DEPICTED by one canon reference card.

    Answers deterministically: which skin regions are visibly exposed in this
    reference image? Creator-declared (or slot-derived for body_map) — never
    probabilistic inference. Absent metadata means legacy/unknown, which must
    NOT be interpreted as fully clothed.
    """
    coverage_type: str = Field(..., min_length=1, max_length=40)
    visible_skin_regions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _expand_and_validate(self) -> "CardCoverage":
        if self.coverage_type in COVERAGE_PRESETS and not self.visible_skin_regions:
            self.visible_skin_regions = list(COVERAGE_PRESETS[self.coverage_type])
        elif self.coverage_type == "custom" and not self.visible_skin_regions:
            raise ValueError("coverage_type 'custom' requires visible_skin_regions")
        elif self.coverage_type not in COVERAGE_PRESETS and self.coverage_type != "custom":
            raise ValueError(
                f"Unknown coverage_type {self.coverage_type!r}. "
                f"Valid: {sorted(COVERAGE_PRESETS)} or 'custom'"
            )
        bad = [r for r in self.visible_skin_regions if r not in COVERAGE_REGIONS]
        if bad:
            raise ValueError(
                f"Unknown skin region(s) {bad!r}. Valid: {sorted(COVERAGE_REGIONS)}"
            )
        return self

    model_config = {"from_attributes": True}


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
    # v2 (S24AK): dedicated side-profile face card. Optional — older canons that
    # never set it deserialize fine and lock unchanged (front face only required).
    face_profile_image_url: Optional[str] = None
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
    # v2 (S24AK): stronger body-truth cards. Optional and additive — existing
    # canons leave these None and lock unchanged (body_front only required).
    torso_front_image_url: Optional[str] = None
    torso_side_image_url: Optional[str] = None
    standing_relaxed_image_url: Optional[str] = None
    seated_relaxed_image_url: Optional[str] = None

    height: Optional[str] = None            # short | medium | tall
    build: Optional[str] = None             # slim | athletic | muscular | stocky | heavy
    proportions: Optional[str] = Field(default=None, max_length=200)
    skin_tone: Optional[str] = None
    body_description: Optional[str] = Field(
        default=None, max_length=500,
        description="Full body description for prompt injection",
    )

    permanent_body_marks: list[PermanentBodyMark] = Field(default_factory=list)

    # Per-card depicted skin coverage, keyed by canon slot name (see
    # CARD_COVERAGE_SLOTS). Additive and optional: canon JSON written before
    # this field existed deserializes to an empty dict, and a slot absent from
    # the dict is legacy/unknown — NOT fully clothed. No Alembic migration:
    # this lives inside body_canon_json.
    card_coverage: dict[str, CardCoverage] = Field(default_factory=dict)

    locked: bool = False

    @model_validator(mode="after")
    def _validate_coverage_slots(self) -> "BodyCanonData":
        bad = [s for s in self.card_coverage if s not in CARD_COVERAGE_SLOTS]
        if bad:
            raise ValueError(
                f"card_coverage has unknown slot(s) {bad!r}. "
                f"Valid: {sorted(CARD_COVERAGE_SLOTS)}"
            )
        return self

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
    face_profile_image_url: Optional[str] = None
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
    torso_front_image_url: Optional[str] = None
    torso_side_image_url: Optional[str] = None
    standing_relaxed_image_url: Optional[str] = None
    seated_relaxed_image_url: Optional[str] = None
    height: Optional[str] = None
    build: Optional[str] = None
    proportions: Optional[str] = Field(default=None, max_length=200)
    skin_tone: Optional[str] = None
    body_description: Optional[str] = Field(default=None, max_length=500)
    # Optional coverage declarations; when provided the dict REPLACES the stored
    # one (whole-dict semantics keep the PATCH deterministic).
    card_coverage: Optional[dict[str, CardCoverage]] = None

    @model_validator(mode="after")
    def _validate_coverage_slots(self) -> "BodyCanonUpdate":
        # Validated HERE (not only on reload) because update_body_canon merges
        # via model_copy, which bypasses BodyCanonData validation — a bad slot
        # key would otherwise persist and poison every later load.
        bad = [s for s in (self.card_coverage or {}) if s not in CARD_COVERAGE_SLOTS]
        if bad:
            raise ValueError(
                f"card_coverage has unknown slot(s) {bad!r}. "
                f"Valid: {sorted(CARD_COVERAGE_SLOTS)}"
            )
        return self


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
    "face_profile",          # v2 (S24AK)
    "face_expression",
    # Body canon
    "body_front",
    "body_left",
    "body_right",
    "body_back",
    "body_map",
    "final_character_card",
    "torso_front",           # v2 (S24AK)
    "torso_side",            # v2 (S24AK)
    "standing_relaxed",      # v2 (S24AK)
    "seated_relaxed",        # v2 (S24AK)
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
    "face_profile":           ("face", "face_profile_image_url"),
    "face_expression":        ("face", "face_expression_image_url"),
    "body_front":             ("body", "body_front_image_url"),
    "body_left":              ("body", "body_left_image_url"),
    "body_right":             ("body", "body_right_image_url"),
    "body_back":              ("body", "body_back_image_url"),
    "body_map":               ("body", "body_map_image_url"),
    "final_character_card":   ("body", "final_character_card_image_url"),
    "torso_front":            ("body", "torso_front_image_url"),
    "torso_side":             ("body", "torso_side_image_url"),
    "standing_relaxed":       ("body", "standing_relaxed_image_url"),
    "seated_relaxed":         ("body", "seated_relaxed_image_url"),
}
