"""Rebuild missing IDENTITY_FACE_REF crops for locked characters.

Run from backend/ directory:
    python scripts/rebuild_face_ref.py
    python scripts/rebuild_face_ref.py --character-id 42
    python scripts/rebuild_face_ref.py --name Leonardo

Safe to run on live data: read-only except for inserting/replacing the
IDENTITY_FACE_REF record.  Never touches anchor images or identity_anchor_json.
"""
import argparse
import logging
import sys
from pathlib import Path

# Allow running from backend/ without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.core.storage import load_image_bytes, save_image
from app.models.character import Character as CharacterModel
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.api.routes.character_visual import _crop_face_reference

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def rebuild_for_character(db, character: CharacterModel, *, dry_run: bool = False) -> str:
    """Rebuild face_ref for one locked character. Returns outcome string."""
    char_id = character.id
    name = character.name

    if not character.identity_anchor_json:
        return f"SKIP  {name} (id={char_id}) — not locked"

    # Check for existing face_ref
    existing = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == char_id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .order_by(CharacterImage.created_at.desc())
        .first()
    )
    if existing:
        return f"OK    {name} (id={char_id}) — face_ref already exists ({existing.file_path[:60]})"

    # Find anchor_front image
    front_img = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == char_id,
            CharacterImage.kind == ImageKindEnum.ANCHOR_FRONT,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .order_by(CharacterImage.created_at.desc())
        .first()
    )
    if front_img is None:
        return f"ERROR {name} (id={char_id}) — no ANCHOR_FRONT image found"

    logger.info("Loading anchor_front for %s (id=%d): %s", name, char_id, front_img.file_path[:80])

    try:
        raw_bytes = load_image_bytes(front_img.file_path)
    except Exception as exc:
        return f"ERROR {name} (id={char_id}) — failed to load anchor_front: {exc}"

    try:
        face_ref_bytes = _crop_face_reference(raw_bytes)
    except Exception as exc:
        return f"ERROR {name} (id={char_id}) — crop failed: {exc}"

    # Phase 4B2: ``user_id`` is NOT NULL and means "the account that owns this
    # asset". A rebuilt face_ref belongs to whoever owns the character it was
    # cropped from — never to whoever happens to be running this script, which
    # is an operator with no claim on the image. Resolved before any bytes are
    # written so an unattributable character costs nothing.
    owner_id = character.owner_id
    if not owner_id:
        logger.error(
            "%s (id=%d) has no owner_id; refusing to create an ownerless face_ref",
            name, char_id,
        )
        return f"ERROR {name} (id={char_id}) — character has no owner; refusing to write an ownerless image"

    if dry_run:
        return f"DRY   {name} (id={char_id}) — would create face_ref from {front_img.file_path[:60]} owned by user {owner_id}"

    try:
        face_ref_path = save_image(face_ref_bytes)
        face_ref_img = CharacterImage(
            character_id=char_id,
            user_id=owner_id,
            kind=ImageKindEnum.IDENTITY_FACE_REF,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            provider=front_img.provider,
            prompt_summary="face reference crop (rebuilt)",
            metadata_json={
                "is_temp": False,
                "source": "rebuild_face_ref_script",
            },
            file_path=face_ref_path,
        )
        db.add(face_ref_img)
        db.commit()
        return f"BUILT {name} (id={char_id}) — face_ref saved to {face_ref_path[:60]}"
    except Exception as exc:
        db.rollback()
        return f"ERROR {name} (id={char_id}) — DB write failed: {exc}"


def main():
    parser = argparse.ArgumentParser(description="Rebuild missing IDENTITY_FACE_REF crops")
    parser.add_argument("--character-id", type=int, help="Rebuild only this character ID")
    parser.add_argument("--name", help="Rebuild only character matching this name (case-insensitive)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(CharacterModel)
        if args.character_id:
            q = q.filter(CharacterModel.id == args.character_id)
        elif args.name:
            q = q.filter(CharacterModel.name.ilike(f"%{args.name}%"))
        else:
            # All locked characters
            q = q.filter(CharacterModel.identity_anchor_json.isnot(None))

        characters = q.order_by(CharacterModel.id).all()
        if not characters:
            logger.info("No matching characters found.")
            return

        logger.info("Processing %d character(s)...", len(characters))
        for character in characters:
            result = rebuild_for_character(db, character, dry_run=args.dry_run)
            print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
