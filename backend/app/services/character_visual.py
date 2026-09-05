"""Service helpers for CharacterDNA and CharacterImage persistence."""
from typing import Optional
from sqlalchemy.orm import Session

from app.models.character_dna import CharacterDNA
from app.models.character_image import CharacterImage
from app.schemas.character_dna import CharacterDNACreate, CharacterDNAUpdate
from app.schemas.character_image import CharacterImageCreate


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

def create_character_image(
    db: Session,
    character_id: int,
    data: CharacterImageCreate,
    *,
    owner_id: int,
) -> CharacterImage:
    """Insert a single CharacterImage record owned by *owner_id*.

    ``owner_id`` is required and keyword-only (Phase 4B2). ``user_id`` is NOT
    NULL, so an owner has to be supplied at INSERT time — both callers used to
    let this function commit an ownerless row and then assign ``user_id``
    afterwards, which is now a constraint violation rather than a brief window.

    It is deliberately NOT derived from the character inside this function.
    Ownership is the caller's statement about the asset, and a helper that
    quietly looked it up would make every future caller's ownership decision
    invisible at the call site — which is exactly how the column drifted into
    meaning "generator" the first time.
    """
    image = CharacterImage(
        character_id=character_id,
        user_id=owner_id,
        **data.model_dump(),
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


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
