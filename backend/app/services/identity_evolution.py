"""
Identity Evolution Service — Phase 1 Foundations.

Defines the canon contract for character identity: which fields are immutable
(face geometry, morphology, species) and which are mutable (hairstyle,
accessories, cosmetic presentation). Provides snapshot, validation, and
rollback primitives used by future evolution flows.

See docs/IDENTITY_EVOLUTION_ARCHITECTURE.md for full design rationale.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.identity_snapshot import IdentitySnapshot


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
    character.updated_at = datetime.utcnow()
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


def compute_immutable_fingerprint(spec_json: Optional[str]) -> Optional[str]:
    """
    Build a stable string from immutable fields only.
    Used alongside identity_prompt_hash for drift detection in Phase 2.
    Returns None if spec is absent or unparseable.
    """
    if not spec_json:
        return None
    try:
        spec = json.loads(spec_json)
    except (json.JSONDecodeError, TypeError):
        return None

    parts = []
    for field_name in sorted(IMMUTABLE_CANON_FIELDS):
        val = _resolve_field(spec, field_name)
        if val is not None:
            parts.append(f"{field_name}:{val}")
    return "|".join(parts) or None


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
