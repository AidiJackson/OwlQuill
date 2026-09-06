"""Service helpers for CharacterDNA and CharacterImage persistence."""
from typing import Optional
from sqlalchemy.orm import Session

from app.models.character_dna import CharacterDNA
from app.models.character_image import CharacterImage
from app.schemas.character_dna import CharacterDNACreate, CharacterDNAUpdate


# ── CharacterDNA helpers ──────────────────────────────────────────────

def upsert_character_dna(
    db: Session,
    character_id: int,
    data: CharacterDNACreate | CharacterDNAUpdate,
) -> CharacterDNA:
    """Create CharacterDNA if it doesn't exist, otherwise update it."""
    existing = (
        db.query(CharacterDNA)
        .filter(CharacterDNA.character_id == character_id)
        .first()
    )

    if existing is None:
        dna = CharacterDNA(
            character_id=character_id,
            **data.model_dump(exclude_unset=True),
        )
        db.add(dna)
    else:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(existing, field, value)
        dna = existing

    db.commit()
    db.refresh(dna)
    return dna


def get_character_dna(db: Session, character_id: int) -> Optional[CharacterDNA]:
    """Return the CharacterDNA row for a character, or None."""
    return (
        db.query(CharacterDNA)
        .filter(CharacterDNA.character_id == character_id)
        .first()
    )


# ── CharacterImage helpers ────────────────────────────────────────────

# ``create_character_image`` was REMOVED in Phase 4D2.
#
# It was the other way to create a ``CharacterImage`` row, and two valid
# persistence mechanisms is one too many: it took bytes that were ALREADY
# stored, so it could not own the storage/database ordering or compensate a
# failed write — the split that produced every orphan object on DEV — and it
# committed its own transaction, so a route that failed after calling it left
# the row behind. Its two callers (``api/routes/images.py``,
# ``api/routes/adult_studio_admin.py``) now go through
# ``asset_persistence.persist_image_asset`` and commit at their own boundary.
#
# Nothing replaced it here on purpose. A helper that accepts an already-stored
# path and inserts a row afterwards is the shape of the problem, not a smaller
# version of it, so the seam is gone rather than renamed.
#
# ``tests/test_legacy_save_image_inventory.py`` asserts no such helper comes
# back.


def list_character_images(
    db: Session,
    character_id: int,
    *,
    kind: Optional[str] = None,
    status: Optional[str] = None,
) -> list[CharacterImage]:
    """List images for a character with optional filters."""
    query = db.query(CharacterImage).filter(
        CharacterImage.character_id == character_id
    )
    if kind is not None:
        query = query.filter(CharacterImage.kind == kind)
    if status is not None:
        query = query.filter(CharacterImage.status == status)
    return query.order_by(CharacterImage.created_at.desc()).all()
