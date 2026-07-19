"""
Identity Evolution Service — Phase 1 Foundations.

Defines the canon contract for character identity: which fields are immutable
(face geometry, morphology, species) and which are mutable (hairstyle,
accessories, cosmetic presentation). Provides snapshot, validation, and
rollback primitives used by future evolution flows.

See docs/IDENTITY_EVOLUTION_ARCHITECTURE.md for full design rationale.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.identity_snapshot import IdentitySnapshot

logger = logging.getLogger(__name__)


# ── Canon field classification ────────────────────────────────────────────────

# These fields define the core physical identity of a character.
# A refresh that alters ANY of these is rejected before generation begins.
IMMUTABLE_CANON_FIELDS: list[str] = [
    # Taxonomy
    "gender",
    "age_band",
    "species",
    "species_tells",
    # Body morphology
    "body_height",
    "body_build",
    # Facial geometry (B14 landmark set)
    "face_shape",
    "jaw_type",
    "cheekbone_type",
    "eye_shape",
    "eye_spacing",
    "eye_color",
    "brow_type",
    "nose_type",
    "lip_type",
    "skin_tone",
]

# These fields may change between identity versions.
# The system validates that proposed changes are within acceptable range
# (e.g., hair can change colour, but species cannot change at all).
MUTABLE_CANON_FIELDS: list[str] = [
    # Hair — natural evolution, styling, aging
    "hair_style",
    "hair_color",
    "hair_length",
    "hair_texture",
    "hairline_type",
    "eyebrow_shape",
    "facial_hair_type",
    # Cosmetic / presentation notes (scars, tattoos, cosmetics)
    "extra_notes",
    # Artistic style may shift across story arcs
    "style",
    # Signature accessories are managed separately via the accessory system
]


@dataclass
class EvolutionValidationResult:
    ok: bool
    immutable_violations: list[str] = field(default_factory=list)
    mutable_changes: list[str] = field(default_factory=list)
    message: str = ""


# ── Snapshot primitives ───────────────────────────────────────────────────────

def take_snapshot(
    db: Session,
    character: Character,
    reason: str = "manual_backup",
) -> IdentitySnapshot:
    """
    Store the current identity state before any mutation.
    Non-destructive — safe to call at any time.
    """
    anchor_version = 1
    if character.dna:
        anchor_version = character.dna.anchor_version

    snapshot = IdentitySnapshot(
        character_id=character.id,
        snapshot_version=character.identity_spec_version or 0,
        anchor_version=anchor_version,
        identity_anchor_json=character.identity_anchor_json,
        identity_spec_json=character.identity_spec_json,
        body_canon_json=character.body_canon_json,
        reason=reason,
        created_at=datetime.utcnow(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def rollback_to_snapshot(
    db: Session,
    character: Character,
    snapshot: IdentitySnapshot,
) -> None:
    """
    Restore identity_anchor_json and identity_spec_json from a snapshot.
    Does NOT touch visual_locked — caller is responsible for gate logic.
    Does NOT revert CharacterImage records; image history is preserved.
    """
    character.identity_anchor_json = snapshot.identity_anchor_json
    character.identity_spec_json = snapshot.identity_spec_json
    if snapshot.body_canon_json is not None:
        character.body_canon_json = snapshot.body_canon_json
    character.updated_at = datetime.utcnow()
    # Recompute pack_stages from restored state so the UI never reads stale
    # locked/missing values baked into the snapshot's identity_anchor_json.
    write_pack_stages(character)
    db.add(character)
    db.commit()


# ── Validation planning hooks ─────────────────────────────────────────────────

def validate_evolution_spec(
    current_spec_json: Optional[str],
    proposed_spec: dict,
) -> EvolutionValidationResult:
    """
    Compare a proposed evolution spec against the locked canon spec.
    Returns ok=True only if no immutable fields would be altered.

    Phase 1: pure comparison logic — no generation triggered.
    Phase 2 will chain this into the refresh generation pipeline.
    """
    if not current_spec_json:
        return EvolutionValidationResult(
            ok=False,
            message="No locked identity spec to compare against.",
        )

    try:
        current = json.loads(current_spec_json)
    except (json.JSONDecodeError, TypeError):
        return EvolutionValidationResult(
            ok=False,
            message="Corrupt identity spec — cannot validate.",
        )

    violations: list[str] = []
    changes: list[str] = []

    for field_name in IMMUTABLE_CANON_FIELDS:
        current_val = _resolve_field(current, field_name)
        proposed_val = _resolve_field(proposed_spec, field_name)
        if proposed_val is not None and proposed_val != current_val:
            violations.append(field_name)

    for field_name in MUTABLE_CANON_FIELDS:
        current_val = _resolve_field(current, field_name)
        proposed_val = _resolve_field(proposed_spec, field_name)
        if proposed_val is not None and proposed_val != current_val:
            changes.append(field_name)

    if violations:
        return EvolutionValidationResult(
            ok=False,
            immutable_violations=violations,
            mutable_changes=changes,
            message=(
                f"Evolution rejected: would alter {len(violations)} immutable "
                f"field(s): {', '.join(violations)}."
            ),
        )

    return EvolutionValidationResult(
        ok=True,
        mutable_changes=changes,
        message=(
            f"Evolution approved: {len(changes)} mutable field(s) will change."
            if changes else "No fields would change."
        ),
    )


# ── Pack stages ───────────────────────────────────────────────────────────────

def compute_pack_stages(character: Character) -> dict:
    """Derive current pack stage values from character state.

    Returns dict with keys: face, body, marks.
    Values: "missing" | "partial" | "locked"

    Face:  locked  = visual_locked is True
           missing = otherwise

    Body:  locked  = body_front slot is "locked"
           partial = body_front slot exists but not locked
           missing = no body_front slot

    Marks: locked  = tattoo_layout slot is "locked"
           partial = markings exist in body_canon_json but tattoo_layout not locked
           missing = no markings at all
    """
    # Face stage
    face_stage = "locked" if character.visual_locked else "missing"

    # Body stage — keyed on body_front slot status
    body_stage = "missing"
    if character.identity_anchor_json:
        try:
            anchor_data = json.loads(character.identity_anchor_json)
            body_slots = anchor_data.get("body_slots") or {}
            bf = body_slots.get("body_front") or {}
            if bf.get("status") == "locked":
                body_stage = "locked"
            elif bf.get("url"):
                body_stage = "partial"
        except (ValueError, TypeError):
            pass

    # Marks stage — keyed on body_canon_json + tattoo_layout slot
    marks_stage = "missing"
    has_markings = False
    if character.body_canon_json:
        try:
            bc = json.loads(character.body_canon_json)
            has_markings = bool(bc.get("markings"))
        except (ValueError, TypeError):
            pass

    if has_markings:
        marks_stage = "partial"
        if character.identity_anchor_json:
            try:
                anchor_data = json.loads(character.identity_anchor_json)
                body_slots = anchor_data.get("body_slots") or {}
                tl = body_slots.get("tattoo_layout") or {}
                if tl.get("status") == "locked":
                    marks_stage = "locked"
            except (ValueError, TypeError):
                pass

    return {"face": face_stage, "body": body_stage, "marks": marks_stage}


def write_pack_stages(character: Character) -> dict:
    """Compute and persist pack_stages into identity_anchor_json. Returns the stages dict."""
    stages = compute_pack_stages(character)
    if character.identity_anchor_json:
        try:
            data = json.loads(character.identity_anchor_json)
        except (ValueError, TypeError):
            data = {}
    else:
        data = {}
    data["pack_stages"] = stages
    character.identity_anchor_json = json.dumps(data)
    logger.info(
        "PACK-STAGES character_id=%s face=%s body=%s marks=%s",
        character.id,
        stages["face"],
        stages["body"],
        stages["marks"],
    )
    return stages


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_field(spec: dict, key: str):
    """
    Resolve a field from a flat or nested spec dict.
    Checks top-level first, then inside the 'identity' sub-dict (IdentityCore).
    """
    if key in spec:
        return spec[key]
    identity = spec.get("identity", {})
    if isinstance(identity, dict) and key in identity:
        return identity[key]
    return None
