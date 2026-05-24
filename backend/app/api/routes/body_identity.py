"""Body Identity Pack endpoints — body morphology and tattoo layout reference slots.

GET  /{character_id}/identity/body-slots                             List all body slot entries.
POST /{character_id}/identity/body-slots/{slot}/generate             Generate/regenerate a slot image.
POST /{character_id}/identity/body-slots/{slot}/lock                 Lock a generated slot for use.
POST /{character_id}/identity/body-slots/{slot}/replace              Replace (regenerate + reset to generated).
POST /{character_id}/identity/body-slots/{slot}/use-existing         Assign an existing gallery image to a slot.
POST /{character_id}/identity/canon-import                           Admin-only: upload body_front or tattoo_layout.

Body slots stored in identity_anchor_json["body_slots"]:
  {
    "body_front":          {"url": "...", "status": "locked",    "prompt": "..."},
    "body_three_quarter":  {"url": "...", "status": "generated", "prompt": "..."},
    "body_back":           {"url": "...", "status": "locked",    "prompt": "..."},
    "tattoo_layout":       {"url": "...", "status": "locked",    "prompt": "..."},
  }
"""
import json as _json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import load_image_bytes, save_image
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum
from app.models.user import User
from app.services.body_canon import build_body_canon_lock_string, load_markings
from app.services.identity_evolution import write_pack_stages
from app.services.image_provider import get_provider_for_option
from app.services.pack_version import get_pack_version

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Slot configuration ────────────────────────────────────────────────

BODY_SLOT_KEYS = ("body_front", "body_three_quarter", "body_back", "tattoo_layout")

BODY_SLOT_LABELS: dict[str, str] = {
    "body_front": "Body Front Reference",
    "body_three_quarter": "Body 3/4 Reference",
    "body_back": "Body Back Reference",
    "tattoo_layout": "Tattoo / Marking Layout",
}

_SLOT_IMAGE_KIND: dict[str, ImageKindEnum] = {
    "body_front": ImageKindEnum.IDENTITY_BODY_FRONT,
    "body_three_quarter": ImageKindEnum.IDENTITY_BODY_THREE_QUARTER,
    "body_back": ImageKindEnum.IDENTITY_BODY_BACK,
    "tattoo_layout": ImageKindEnum.IDENTITY_TATTOO_LAYOUT,
}


# ── Prompt builders ───────────────────────────────────────────────────

def build_body_slot_prompt(
    slot: str,
    character_name: str,
    identity_lock_string: str = "",
    body_canon_str: str = "",
) -> str:
    """Build a generation prompt for a body identity slot.

    Each slot prompt is written to produce a clean anatomical reference
    image that anchors body morphology and marking placement.
    """
    name_part = f"{character_name}. " if character_name else ""
    lock_part = f"{identity_lock_string}. " if identity_lock_string else ""
    markings_part = f"{body_canon_str}. " if body_canon_str else ""

    if slot == "body_front":
        return (
            f"Full-body front reference of {name_part}{lock_part}{markings_part}"
            "Neutral standing pose, arms relaxed at sides, facing forward. "
            "Full torso and arms visible. Fitted plain clothing or underlayer. "
            "No dramatic pose, no props, no background clutter. "
            "Clean neutral lighting. Preserve exact body type and proportions. "
            "Anatomical reference card."
        )[:800]

    if slot == "body_three_quarter":
        return (
            f"Three-quarter full-body reference of {name_part}{lock_part}{markings_part}"
            "Neutral 3/4 angle, standing pose, arms relaxed. "
            "Full torso and arms visible. Fitted plain clothing or underlayer. "
            "No dramatic pose, no props. Clean neutral lighting. "
            "Body depth and proportion reference."
        )[:800]

    if slot == "body_back":
        return (
            f"Full-body back-view reference of {name_part}{lock_part}{markings_part}"
            "Neutral standing pose from behind, arms relaxed at sides. "
            "Full back and both arms visible. Fitted plain clothing or underlayer. "
            "No dramatic pose, no props. Clean neutral lighting. "
            "Back anatomy and proportion reference."
        )[:800]

    if slot == "tattoo_layout":
        return (
            f"Full-body tattoo and marking layout reference for {name_part}"
            f"{lock_part}{markings_part}"
            "Both arms extended slightly from sides, neutral stance. "
            "No jacket, no long sleeves, nothing obstructing arms or torso. "
            "No crossed arms. No props. "
            "All tattoos and body markings clearly visible and precisely placed. "
            "Correct anatomical side for each marking — right tattoo on right arm only, "
            "left tattoo on left arm only. "
            "Reference sheet style, clean neutral background."
        )[:800]

    return f"Body reference image of {name_part}Neutral pose, full body visible."[:800]


# ── JSON helpers ──────────────────────────────────────────────────────

def _load_body_slots(character: CharacterModel) -> dict:
    """Return the body_slots dict from identity_anchor_json, or {}."""
    if not character.identity_anchor_json:
        return {}
    try:
        data = _json.loads(character.identity_anchor_json)
        return data.get("body_slots") or {}
    except (ValueError, TypeError):
        return {}


def _save_body_slot(
    character: CharacterModel,
    slot: str,
    entry: dict,
) -> None:
    """Merge a single slot entry into identity_anchor_json["body_slots"]."""
    if character.identity_anchor_json:
        try:
            data = _json.loads(character.identity_anchor_json)
        except (ValueError, TypeError):
            data = {}
    else:
        data = {}

    if "body_slots" not in data or not isinstance(data["body_slots"], dict):
        data["body_slots"] = {}
    data["body_slots"][slot] = entry
    character.identity_anchor_json = _json.dumps(data)


# ── Auth helper ───────────────────────────────────────────────────────

def _get_owned_character(character_id: int, current_user: User, db: Session) -> CharacterModel:
    char = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not char:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if char.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You don't have permission to modify this character.")
    return char


# ── Schemas ───────────────────────────────────────────────────────────

class BodySlotEntry(BaseModel):
    key: str
    label: str
    url: str | None = None
    status: str = "missing"  # "missing" | "generated" | "locked"
    prompt: str | None = None


class BodySlotsResponse(BaseModel):
    character_id: int
    slots: list[BodySlotEntry]


class UseExistingSlotBody(BaseModel):
    image_id: int


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get(
    "/{character_id}/identity/body-slots",
    response_model=BodySlotsResponse,
    summary="List all body identity slot entries for a character",
)
def list_body_slots(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodySlotsResponse:
    char = _get_owned_character(character_id, current_user, db)
    stored = _load_body_slots(char)
    slots = []
    for key in BODY_SLOT_KEYS:
        entry = stored.get(key) or {}
        slots.append(BodySlotEntry(
            key=key,
            label=BODY_SLOT_LABELS[key],
            url=entry.get("url"),
            status=entry.get("status", "missing"),
            prompt=entry.get("prompt"),
        ))
    return BodySlotsResponse(character_id=character_id, slots=slots)


def _do_generate_body_slot(
    character: CharacterModel,
    slot: str,
    db: Session,
) -> BodySlotEntry:
    """Core generation logic shared by generate and replace endpoints."""
    if slot not in BODY_SLOT_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown body slot '{slot}'. Valid: {list(BODY_SLOT_KEYS)}",
        )

    # Build prompt from identity lock + body canon
    try:
        anchor_data = _json.loads(character.identity_anchor_json) if character.identity_anchor_json else {}
    except (ValueError, TypeError):
        anchor_data = {}

    identity_lock_string = anchor_data.get("identity_lock_string") or ""
    body_canon_str = build_body_canon_lock_string(load_markings(character))
    prompt = build_body_slot_prompt(
        slot,
        character_name=character.name or "",
        identity_lock_string=identity_lock_string,
        body_canon_str=body_canon_str,
    )

    try:
        provider = get_provider_for_option("option1")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image provider unavailable. Please try again later.",
        ) from exc

    # If include_character=True and identity anchors exist, pass them as references
    # so the body reference preserves face/hair.
    anchors = anchor_data.get("anchors") or {}
    ref_images: list[bytes] = []
    for key in ("front", "three_quarter"):
        entry = anchors.get(key)
        if entry and entry.get("url"):
            try:
                ref_images.append(load_image_bytes(entry["url"]))
            except Exception:
                pass

    try:
        if ref_images and getattr(provider, "supports_multi_image_input", False):
            png_bytes = provider.generate_with_anchors(
                prompt=prompt,
                anchor_images=ref_images,
            )
        else:
            png_bytes = provider.generate_image(prompt=prompt)
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "body_identity_slot_generation_failed character_id=%s slot=%s error=%r",
            character.id, slot, str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Body slot image generation failed for '{slot}'. Please try again.",
        ) from exc

    image_url = save_image(png_bytes)

    # Archive any existing CharacterImage of this kind
    kind = _SLOT_IMAGE_KIND[slot]
    db.query(CharacterImage).filter(
        CharacterImage.character_id == character.id,
        CharacterImage.kind == kind,
    ).update({"status": ImageStatusEnum.ARCHIVED})

    # Store new CharacterImage
    ci = CharacterImage(
        character_id=character.id,
        kind=kind,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=getattr(provider, "provider_name", "stub"),
        prompt_summary=prompt[:200],
        file_path=image_url,
    )
    db.add(ci)
    db.flush()

    # Update identity_anchor_json body_slots — stamp current pack_version so
    # health checks can detect when this image predates a later mutation.
    _slot_pack_version = get_pack_version(character)
    _save_body_slot(character, slot, {
        "url": image_url,
        "status": "generated",
        "prompt": prompt,
        "pack_version": _slot_pack_version,
    })
    db.commit()

    logger.info(
        "body_identity_slot_generated character_id=%s slot=%s url=%s",
        character.id, slot, image_url,
    )
    return BodySlotEntry(key=slot, label=BODY_SLOT_LABELS[slot],
                         url=image_url, status="generated", prompt=prompt)


@router.post(
    "/{character_id}/identity/body-slots/{slot}/generate",
    response_model=BodySlotsResponse,
    summary="Generate a body identity slot image",
)
def generate_body_slot(
    character_id: int,
    slot: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodySlotsResponse:
    char = _get_owned_character(character_id, current_user, db)
    _do_generate_body_slot(char, slot, db)
    return _full_response(character_id, char)


@router.post(
    "/{character_id}/identity/body-slots/{slot}/lock",
    response_model=BodySlotsResponse,
    summary="Lock a generated body identity slot for use in image generation",
)
def lock_body_slot(
    character_id: int,
    slot: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodySlotsResponse:
    char = _get_owned_character(character_id, current_user, db)
    if slot not in BODY_SLOT_KEYS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Unknown body slot '{slot}'.")
    stored = _load_body_slots(char)
    entry = stored.get(slot) or {}
    if not entry.get("url"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"No image generated for slot '{slot}' yet. Call generate first.")
    _save_body_slot(char, slot, {**entry, "status": "locked"})
    write_pack_stages(char)
    db.commit()
    logger.info("body_identity_slot_locked character_id=%s slot=%s", character_id, slot)
    return _full_response(character_id, char)


@router.post(
    "/{character_id}/identity/body-slots/{slot}/replace",
    response_model=BodySlotsResponse,
    summary="Replace (regenerate) a body identity slot image",
)
def replace_body_slot(
    character_id: int,
    slot: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodySlotsResponse:
    char = _get_owned_character(character_id, current_user, db)
    _do_generate_body_slot(char, slot, db)
    return _full_response(character_id, char)


@router.post(
    "/{character_id}/identity/body-slots/{slot}/use-existing",
    response_model=BodySlotsResponse,
    summary="Assign an existing gallery image to a body identity slot",
)
def use_existing_body_slot(
    character_id: int,
    slot: str,
    body: UseExistingSlotBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BodySlotsResponse:
    """Promote an existing CharacterImage into a body identity slot, bypassing generation."""
    char = _get_owned_character(character_id, current_user, db)
    if slot not in BODY_SLOT_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown body slot '{slot}'. Valid: {list(BODY_SLOT_KEYS)}",
        )
    image = db.query(CharacterImage).filter(
        CharacterImage.id == body.image_id,
        CharacterImage.character_id == character_id,
    ).first()
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found or does not belong to this character.",
        )
    _save_body_slot(char, slot, {
        "url": image.file_path,
        "status": "locked",
        "prompt": None,
        "pack_version": get_pack_version(char),
    })
    write_pack_stages(char)
    db.commit()
    logger.info(
        "body_identity_slot_use_existing character_id=%s slot=%s image_id=%s url=%s",
        character_id, slot, body.image_id, image.file_path,
    )
    return _full_response(character_id, char)


def _full_response(character_id: int, char: CharacterModel) -> BodySlotsResponse:
    stored = _load_body_slots(char)
    slots = []
    for key in BODY_SLOT_KEYS:
        entry = stored.get(key) or {}
        slots.append(BodySlotEntry(
            key=key,
            label=BODY_SLOT_LABELS[key],
            url=entry.get("url"),
            status=entry.get("status", "missing"),
            prompt=entry.get("prompt"),
        ))
    return BodySlotsResponse(character_id=character_id, slots=slots)


# ── Admin-only canon import ────────────────────────────────────────────

_CANON_IMPORT_SLOTS = ("body_front", "tattoo_layout")
_CANON_IMPORT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _require_admin(current_user: User) -> None:
    is_admin = bool(current_user.is_admin) or current_user.email.lower() in settings.get_admin_emails()
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Admin access required."},
        )


class CanonImportResponse(BaseModel):
    character_id: int
    target_slot: str
    url: str
    image_id: int
    pack_stages: dict


@router.post(
    "/{character_id}/identity/canon-import",
    response_model=CanonImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin only] Upload a canon body reference image for body_front or tattoo_layout",
)
async def admin_canon_import(
    character_id: int,
    file: UploadFile = File(..., description="PNG or JPEG image file"),
    target_slot: str = Form(..., description="'body_front' or 'tattoo_layout'"),
    source_note: Optional[str] = Form(default=None, description="Optional provenance note"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanonImportResponse:
    """Upload a pre-produced canonical reference image as body_front or tattoo_layout.

    Admin-only. Not visible to normal users. Designed for character setup by the
    content team — e.g. importing a high-quality artist-rendered body reference or
    tattoo layout chart. Does NOT delete or reset any existing body canon markings.
    """
    _require_admin(current_user)

    if target_slot not in _CANON_IMPORT_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"target_slot must be one of {list(_CANON_IMPORT_SLOTS)}.",
        )

    content_type = file.content_type or ""
    if content_type not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only PNG, JPEG, or WebP images are accepted.",
        )

    char = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not char:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")

    raw = await file.read()
    if len(raw) > _CANON_IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds 10 MB limit.",
        )

    image_url = save_image(raw)

    # Archive any existing active CharacterImage for this kind
    kind = _SLOT_IMAGE_KIND[target_slot]
    db.query(CharacterImage).filter(
        CharacterImage.character_id == character_id,
        CharacterImage.kind == kind,
    ).update({"status": ImageStatusEnum.ARCHIVED})

    _import_pack_version = get_pack_version(char)
    meta: dict = {
        "source": "admin_canon_import",
        "admin_email": current_user.email,
        "pack_version": _import_pack_version,
    }
    if source_note:
        meta["source_note"] = source_note

    ci = CharacterImage(
        character_id=character_id,
        kind=kind,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="admin_upload",
        prompt_summary=f"admin canon import: {target_slot}",
        metadata_json=meta,
        file_path=image_url,
    )
    db.add(ci)
    db.flush()

    _save_body_slot(char, target_slot, {
        "url": image_url,
        "status": "locked",
        "prompt": None,
        "source": "admin_canon_import",
        "pack_version": _import_pack_version,
    })
    stages = write_pack_stages(char)
    db.commit()

    logger.info(
        "ADMIN-CANON-IMPORT character_id=%s target_slot=%s image_id=%s url=%s admin=%s",
        character_id, target_slot, ci.id, image_url, current_user.email,
    )
    return CanonImportResponse(
        character_id=character_id,
        target_slot=target_slot,
        url=image_url,
        image_id=ci.id,
        pack_stages=stages,
    )
