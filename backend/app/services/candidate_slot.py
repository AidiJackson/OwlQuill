"""
Candidate slot replacement service — Identity Evolution Phase 2.

Provides create / validate / promote / reject operations for proposed
slot image replacements. Promotion always takes a snapshot first, then
writes the new url into identity_anchor_json["anchors"][slot] while
preserving accessories and all other anchor slots.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.candidate_slot import CandidateSlot, VALID_SLOTS
from app.models.character import Character
from app.services.identity_evolution import (
    IMMUTABLE_CANON_FIELDS,
    take_snapshot,
)


# ── Create ────────────────────────────────────────────────────────────────────

def create_candidate(
    db: Session,
    character: Character,
    slot: str,
    image_url: str,
) -> CandidateSlot:
    candidate = CandidateSlot(
        character_id=character.id,
        slot=slot,
        image_url=image_url,
        status="candidate",
        validation_status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


# ── Validate ──────────────────────────────────────────────────────────────────

@dataclass
class CandidateValidationResult:
    ok: bool
    validation_status: str  # "valid" | "warning" | "invalid"
    notes: list[str] = field(default_factory=list)

    @property
    def notes_text(self) -> str:
        return "; ".join(self.notes) if self.notes else ""


def validate_candidate(
    db: Session,
    character: Character,
    candidate: CandidateSlot,
) -> CandidateSlot:
    """
    Run v1 validation checks against the candidate.

    Checks:
    1. Character must be locked (guard enforced upstream, but double-checked).
    2. Candidate must have an image_url.
    3. Slot name must be valid.
    4. Compare immutable text/spec fields if identity_spec_json is present.
    5. Placeholder hook for face embedding similarity (Phase 3).
    6. Warn if candidate slot has no matching anchor in existing identity_anchor_json.

    Sets validation_status and validation_notes on the candidate, then commits.
    """
    notes: list[str] = []
    ok = True

    # 1. Character lock (upstream guard guarantees this, but belt-and-suspenders)
    if not character.visual_locked:
        candidate.validation_status = "invalid"
        candidate.validation_notes = "Character is not locked."
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
        return candidate

    # 2. Image URL present
    if not candidate.image_url:
        notes.append("No candidate image URL provided.")
        ok = False

    # 3. Slot validity
    if candidate.slot not in VALID_SLOTS:
        notes.append(f"Unknown slot '{candidate.slot}'. Must be one of {sorted(VALID_SLOTS)}.")
        ok = False

    # 4. Spec immutable field check — warn if spec available and a mutable field changed
    if character.identity_spec_json:
        try:
            spec = json.loads(character.identity_spec_json)
            immutable_present = [
                f for f in IMMUTABLE_CANON_FIELDS
                if _resolve_field(spec, f) is not None
            ]
            if immutable_present:
                notes.append(
                    f"Immutable spec fields present ({len(immutable_present)} fields). "
                    "Promotion will not alter them — only the slot image URL is replaced."
                )
        except (json.JSONDecodeError, TypeError):
            notes.append("identity_spec_json is present but could not be parsed.")

    # 5. Face embedding similarity placeholder
    notes.append(
        "Face embedding similarity check: not yet implemented (Phase 3). "
        "Manual review recommended."
    )

    # 6. Slot presence in existing anchor
    existing_slot_url = _get_existing_slot_url(character.identity_anchor_json, candidate.slot)
    if existing_slot_url is None:
        notes.append(
            f"Slot '{candidate.slot}' has no existing anchor image. "
            "Promotion will create it for the first time."
        )

    # Determine final validation_status
    if not ok:
        validation_status = "invalid"
    elif any("not yet implemented" in n or "recommended" in n for n in notes):
        validation_status = "warning"
    else:
        validation_status = "valid"

    candidate.validation_status = validation_status
    candidate.validation_notes = "; ".join(notes) if notes else None
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


# ── Promote ───────────────────────────────────────────────────────────────────

def promote_candidate(
    db: Session,
    character: Character,
    candidate: CandidateSlot,
):
    """
    Promote a candidate slot replacement into the character's live identity_anchor_json.

    Steps:
    1. Reject if candidate is not in 'candidate' status.
    2. Reject if validation_status is 'invalid'.
    3. Take a snapshot (reason="pre_evolution").
    4. Parse identity_anchor_json.
    5. Replace only anchors[slot].url — preserve accessories and all other slots.
    6. Persist updated identity_anchor_json.
    7. Set candidate status="promoted".

    Returns (snapshot, updated_candidate).
    """
    if candidate.status != "candidate":
        raise ValueError(f"Candidate is already {candidate.status}.")
    if candidate.validation_status == "invalid":
        raise ValueError("Cannot promote an invalid candidate. Run validation first.")

    # Snapshot before any mutation
    snapshot = take_snapshot(db, character, reason="pre_evolution")

    # Parse and mutate anchor JSON
    anchor_data = _parse_anchor_json(character.identity_anchor_json)
    anchors = anchor_data.setdefault("anchors", {})
    existing = anchors.get(candidate.slot) or {}
    existing["url"] = candidate.image_url
    anchors[candidate.slot] = existing
    anchor_data["anchors"] = anchors

    character.identity_anchor_json = json.dumps(anchor_data)
    character.updated_at = datetime.utcnow()
    db.add(character)

    candidate.status = "promoted"
    db.add(candidate)

    db.commit()
    db.refresh(candidate)
    return snapshot, candidate


# ── Reject ────────────────────────────────────────────────────────────────────

def reject_candidate(
    db: Session,
    candidate: CandidateSlot,
) -> CandidateSlot:
    if candidate.status != "candidate":
        raise ValueError(f"Candidate is already {candidate.status}.")
    candidate.status = "rejected"
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_anchor_json(identity_anchor_json) -> dict:
    if identity_anchor_json:
        try:
            return json.loads(identity_anchor_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _get_existing_slot_url(identity_anchor_json, slot: str):
    data = _parse_anchor_json(identity_anchor_json)
    anchors = data.get("anchors") or {}
    entry = anchors.get(slot)
    if entry and entry.get("url"):
        return entry["url"]
    return None


def _resolve_field(spec: dict, key: str):
    if key in spec:
        return spec[key]
    identity = spec.get("identity", {})
    if isinstance(identity, dict) and key in identity:
        return identity[key]
    return None
