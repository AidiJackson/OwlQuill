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
#
# BODY IDENTITY PACK v2 — canonical slot roles:
#
#   body_front            PRIMARY truth reference — neutral front pose, arms out,
#                         all markings exposed. Required when markings exist.
#   body_left_detail      High-fidelity crop of left side / left arm markings.
#   body_right_detail     High-fidelity crop of right side / right arm markings.
#   body_back             Back view — back tattoos, shoulder, lower-back markings.
#   body_map              Canonical placement sheet — both arms extended, reference-card
#                         style.  Replaces legacy tattoo_layout.
#   final_character_card  Cinematic full-character image. SUPPORT ONLY — never primary
#                         truth.  Must always be last in generation ref ordering.
#
# Legacy slots (kept for backward compatibility — existing characters may have them):
#   body_three_quarter    3/4 angle full-body view.
#   tattoo_layout         Abstract marking layout (precursor to body_map).
#
# All slots persist in identity_anchor_json["body_slots"][<key>]:
#   {"url": "...", "status": "locked"|"generated"|"missing", "prompt": "..."}

BODY_SLOT_KEYS = (
    # v2 canonical roles
    "body_front",
    "body_left_detail",
    "body_right_detail",
    "body_back",
    "body_map",
    "final_character_card",
    # legacy roles — kept for backward compat, not surfaced in wizard
    "body_three_quarter",
    "tattoo_layout",
)

# Slots shown to users in the wizard UI (v2 canonical only).
BODY_SLOT_KEYS_V2 = (
    "body_front",
    "body_left_detail",
    "body_right_detail",
    "body_back",
    "body_map",
    "final_character_card",
)

BODY_SLOT_LABELS: dict[str, str] = {
    "body_front": "Body Front Reference",
    "body_left_detail": "Left Detail Reference",
    "body_right_detail": "Right Detail Reference",
    "body_back": "Body Back Reference",
    "body_map": "Body Map / Marking Layout",
    "final_character_card": "Final Character Card",
    # legacy
    "body_three_quarter": "Body 3/4 Reference",
    "tattoo_layout": "Tattoo / Marking Layout",
}

_SLOT_IMAGE_KIND: dict[str, ImageKindEnum] = {
    "body_front": ImageKindEnum.IDENTITY_BODY_FRONT,
    "body_left_detail": ImageKindEnum.IDENTITY_BODY_LEFT_DETAIL,
    "body_right_detail": ImageKindEnum.IDENTITY_BODY_RIGHT_DETAIL,
    "body_back": ImageKindEnum.IDENTITY_BODY_BACK,
    "body_map": ImageKindEnum.IDENTITY_BODY_MAP,
    "final_character_card": ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD,
    # legacy
    "body_three_quarter": ImageKindEnum.IDENTITY_BODY_THREE_QUARTER,
    "tattoo_layout": ImageKindEnum.IDENTITY_TATTOO_LAYOUT,
}

# ── Body map generation spec (Part 4 contract) ────────────────────────
#
# Generation requirements per slot — consumed by the wizard UI and prompt
# builders.  These are the hard constraints each image MUST satisfy to be
# accepted as a canonical identity reference.
#
# NOT to be changed lightly: these constraints are what allow the system
# to treat the image as visual truth rather than semantic suggestion.

BODY_SLOT_GENERATION_SPEC: dict[str, dict] = {
    "body_front": {
        "pose": "neutral standing, arms relaxed at sides, facing forward",
        "clothing": "sleeveless or shirtless — no long sleeves, no jacket",
        "framing": "full body — head to feet",
        "lighting": "neutral, flat, no dramatic shadows",
        "background": "plain neutral — no clutter, no props",
        "purpose": "PRIMARY body truth — body proportions and all marking placement",
        "required_when_markings": True,
    },
    "body_left_detail": {
        "pose": "left side toward camera, arm slightly extended or relaxed",
        "clothing": "sleeveless — left arm and torso left side fully exposed",
        "framing": "torso + left arm crop — shoulder to hip",
        "lighting": "neutral, even",
        "background": "plain neutral",
        "purpose": "high-fidelity left-side marking reproduction",
        "required_when_markings": False,
    },
    "body_right_detail": {
        "pose": "right side toward camera, arm slightly extended or relaxed",
        "clothing": "sleeveless — right arm and torso right side fully exposed",
        "framing": "torso + right arm crop — shoulder to hip",
        "lighting": "neutral, even",
        "background": "plain neutral",
        "purpose": "high-fidelity right-side marking reproduction",
        "required_when_markings": False,
    },
    "body_back": {
        "pose": "neutral standing, back to camera, arms relaxed",
        "clothing": "sleeveless or shirtless — back fully exposed",
        "framing": "full back — head to feet",
        "lighting": "neutral, even",
        "background": "plain neutral",
        "purpose": "back tattoos, shoulder blades, lower-back markings",
        "required_when_markings": False,
    },
    "body_map": {
        "pose": "neutral stance, both arms extended slightly from sides (T-pose adjacent)",
        "clothing": "no jacket, no long sleeves — all markings exposed",
        "framing": "full body, all limbs visible",
        "lighting": "flat reference lighting",
        "background": "plain neutral — reference card style",
        "purpose": "canonical placement map — spatial relationships between markings",
        "required_when_markings": False,
    },
    "final_character_card": {
        "pose": "cinematic — any aesthetically appropriate pose",
        "clothing": "final costume / canonical outfit",
        "framing": "full character — cinematic framing",
        "lighting": "cinematic",
        "background": "contextual or atmospheric",
        "purpose": "SUPPORT ONLY — presentation reference, never anatomical truth",
        "required_when_markings": False,
        "support_only": True,
    },
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

    # ── v2 canonical slots ─────────────────────────────────────────────

    if slot == "body_left_detail":
        return (
            f"Left-side detail reference of {name_part}{lock_part}{markings_part}"
            "Left side of body toward camera. Left arm slightly extended, relaxed. "
            "Sleeveless — left arm and left torso fully exposed, no clothing blocking. "
            "Torso and left arm crop, shoulder to hip. "
            "Neutral even lighting. Plain background. "
            "High-fidelity marking detail — exact tattoo placement and design on left side."
        )[:800]

    if slot == "body_right_detail":
        return (
            f"Right-side detail reference of {name_part}{lock_part}{markings_part}"
            "Right side of body toward camera. Right arm slightly extended, relaxed. "
            "Sleeveless — right arm and right torso fully exposed, no clothing blocking. "
            "Torso and right arm crop, shoulder to hip. "
            "Neutral even lighting. Plain background. "
            "High-fidelity marking detail — exact tattoo placement and design on right side."
        )[:800]

    if slot == "body_map":
        return (
            f"Canonical body marking placement map for {name_part}{lock_part}{markings_part}"
            "Full-body reference card. Both arms extended slightly from sides. "
            "No jacket, no long sleeves — all tattoos and markings fully exposed. "
            "No crossed arms. No props. Flat reference-card lighting. Plain neutral background. "
            "Every marking precisely placed on correct anatomical side. "
            "Right markings on right side only. Left markings on left side only. "
            "Placement sheet style — used as spatial truth for generation."
        )[:800]

    if slot == "final_character_card":
        return (
            f"Final character card — cinematic full-character reference for {name_part}"
            f"{lock_part}{markings_part}"
            "Full character visible. Canonical costume and appearance. "
            "Cinematic lighting and composition. "
            "Support reference only — NOT used for anatomical truth or marking placement."
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
