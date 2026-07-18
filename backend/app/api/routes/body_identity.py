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
from app.services.provider_capabilities import Capability, provider_supports
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
    # Face canon
    "face_front": ImageKindEnum.ANCHOR_FRONT,
    "face_three_quarter_left": ImageKindEnum.ANCHOR_THREE_QUARTER,
    "face_three_quarter_right": ImageKindEnum.ANCHOR_THREE_QUARTER,
    # Body canon
    "body_front": ImageKindEnum.IDENTITY_BODY_FRONT,
    "body_left": ImageKindEnum.IDENTITY_BODY_LEFT_DETAIL,
    "body_right": ImageKindEnum.IDENTITY_BODY_RIGHT_DETAIL,
    "body_back": ImageKindEnum.IDENTITY_BODY_BACK,
    "body_map": ImageKindEnum.IDENTITY_BODY_MAP,
    "final_character_card": ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD,
    # Accessory canon
    "accessory_design": ImageKindEnum.ACCESSORY_DESIGN,
    "accessory_fit": ImageKindEnum.ACCESSORY_FIT,
    # Legacy
    "body_left_detail": ImageKindEnum.IDENTITY_BODY_LEFT_DETAIL,
    "body_right_detail": ImageKindEnum.IDENTITY_BODY_RIGHT_DETAIL,
    "body_three_quarter": ImageKindEnum.IDENTITY_BODY_THREE_QUARTER,
    "tattoo_layout": ImageKindEnum.IDENTITY_TATTOO_LAYOUT,
}

# Face canon slots are stored in identity_anchor_json["anchors"], not body_slots.
_FACE_CANON_SLOTS = frozenset({"face_front", "face_three_quarter_left", "face_three_quarter_right"})

# Accessory slots stored in identity_anchor_json["accessory_slots"]
_ACCESSORY_CANON_SLOTS = frozenset({"accessory_design", "accessory_fit"})

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
        "pose": "neutral standing, both arms visible and relaxed at sides, facing forward",
        "clothing": "sleeveless or minimal clothing — no long sleeves, no jacket; no tattoos printed on clothing",
        "framing": "full body — head to feet or knees-up; both arms in frame",
        "lighting": "neutral, flat, no dramatic shadows",
        "background": "plain neutral — no clutter, no props",
        "purpose": "PRIMARY body truth — body proportions and all marking placement; all permanent markings visible where possible",
        "required_when_markings": True,
    },
    "body_left_detail": {
        "pose": "left side toward camera, left arm slightly extended — no cinematic pose",
        "clothing": "sleeveless — left arm and torso fully exposed; no clothing covering marks; no tattoos printed on clothing",
        "framing": "left arm shoulder to wrist fully in frame; left torso visible",
        "lighting": "neutral, even",
        "background": "plain neutral",
        "purpose": "high-fidelity left-side marking reproduction",
        "constraints": "LEFT ARM AND LEFT SIDE ONLY — no right arm substitution; no mirror; no design reinterpretation",
        "required_when_markings": False,
    },
    "body_right_detail": {
        "pose": "right side toward camera, right arm slightly extended — no cinematic pose",
        "clothing": "sleeveless — right arm and torso fully exposed; no clothing covering marks; no tattoos printed on clothing",
        "framing": "right arm shoulder to wrist fully in frame; right torso visible",
        "lighting": "neutral, even",
        "background": "plain neutral",
        "purpose": "high-fidelity right-side marking reproduction",
        "constraints": "RIGHT ARM AND RIGHT SIDE ONLY — no left arm substitution; no mirror; no design reinterpretation",
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
        "clothing": "no jacket, no long sleeves — all markings exposed; no tattoos on clothing",
        "framing": "full body, all limbs visible — front body placement primary; back/side only if markings require",
        "lighting": "flat reference lighting",
        "background": "plain neutral — reference card style",
        "labels": "clear left/right side labels required — left markings on left only, right markings on right only",
        "purpose": "canonical placement map — NOT cinematic art, NOT outfit/fashion image; no extra designs",
        "required_when_markings": False,
    },
    "final_character_card": {
        "pose": "cinematic — any aesthetically appropriate pose",
        "clothing": "final costume / canonical outfit",
        "framing": "full character — cinematic framing",
        "lighting": "cinematic",
        "background": "contextual or atmospheric",
        "purpose": "CINEMATIC PRESENTATION ONLY — NOT primary anatomical truth; SUPPORT reference only — never used for marking placement or body morphology decisions",
        "required_when_markings": False,
        "support_only": True,
        "cinematic_only": True,
        "not_anatomical_truth": True,
        "preserve_locked_refs": True,
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
            "Full body head-to-feet or knees-up. Both arms visible, relaxed at sides. Facing forward. "
            "Sleeveless or minimal clothing — no long sleeves, no jacket. "
            "All permanent markings visible where possible. No tattoos printed on clothing. "
            "No dramatic pose, no props, no background clutter. "
            "Clean neutral lighting. Preserve exact body type and proportions. "
            "Anatomical reference card — not a scene, not a fashion image."
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
            "LEFT ARM AND LEFT SIDE ONLY — do not substitute or mirror right arm. "
            "Left side of body toward camera. Left arm slightly extended, shoulder to wrist fully in frame. "
            "Sleeveless — left arm and left torso fully exposed. No clothing covering marks. "
            "No tattoos or designs printed on clothing. "
            "All tattoos and markings on left side fully visible, no obstruction. "
            "Neutral even lighting. Plain neutral background. No cinematic pose. "
            "Exact marking placement and design — no reinterpretation, no alternate design. "
            "High-fidelity anatomical marking reference."
        )[:800]

    if slot == "body_right_detail":
        return (
            f"Right-side detail reference of {name_part}{lock_part}{markings_part}"
            "RIGHT ARM AND RIGHT SIDE ONLY — do not substitute or mirror left arm. "
            "Right side of body toward camera. Right arm slightly extended, shoulder to wrist fully in frame. "
            "Sleeveless — right arm and right torso fully exposed. No clothing covering marks. "
            "No tattoos or designs printed on clothing. "
            "All tattoos and markings on right side fully visible, no obstruction. "
            "Neutral even lighting. Plain neutral background. No cinematic pose. "
            "Exact marking placement and design — no reinterpretation, no alternate design. "
            "High-fidelity anatomical marking reference."
        )[:800]

    if slot == "body_map":
        return (
            f"Canonical body marking placement map — reference sheet for {name_part}{lock_part}{markings_part}"
            "NOT cinematic art. NOT outfit or fashion image. "
            "Full-body reference card — front body placement shown. Both arms extended slightly from sides. "
            "Clear left/right side labels: left markings on left side only, right markings on right side only. "
            "No jacket, no long sleeves — all markings fully exposed. "
            "No crossed arms. No props. No extra designs beyond the character's own markings. "
            "Back/side sections only if markings require it. "
            "Flat reference-card lighting. Plain neutral background. "
            "Spatial placement truth — used as canonical generation reference."
        )[:800]

    if slot == "final_character_card":
        return (
            f"Final character card for {name_part}{lock_part}{markings_part}"
            "CINEMATIC PRESENTATION ONLY — NOT primary anatomical truth or marking reference. "
            "Preserve locked face and body identity references exactly. "
            "Full character in canonical costume and appearance. "
            "Cinematic lighting and composition — aesthetically appropriate pose. "
            "SUPPORT reference only — never used for marking placement or body morphology decisions."
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
        if ref_images and provider_supports(provider, Capability.MULTI_IMAGE_ANCHORS):
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

# Identity OS Beta: extended set of admin-uploadable canon slots.
# Face canon slots are stored in identity_anchor_json["anchors"].
# Body/accessory canon slots are stored in identity_anchor_json["body_slots"].
_CANON_IMPORT_SLOTS = (
    # Face canon
    "face_front",
    "face_three_quarter_left",
    "face_three_quarter_right",
    # Body canon
    "body_front",
    "body_left",
    "body_right",
    "body_back",
    "body_map",
    "final_character_card",
    # Accessory canon
    "accessory_design",
    "accessory_fit",
    # Legacy
    "tattoo_layout",
)
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
    summary="[Admin only] Upload a canon reference image for any canon slot",
)
async def admin_canon_import(
    character_id: int,
    file: UploadFile = File(..., description="PNG or JPEG image file"),
    target_slot: str = Form(..., description=(
        "Canon slot: face_front | face_three_quarter_left | face_three_quarter_right | "
        "body_front | body_left | body_right | body_back | body_map | "
        "final_character_card | accessory_design | accessory_fit | tattoo_layout"
    )),
    source_note: Optional[str] = Form(default=None, description="Optional provenance note"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanonImportResponse:
    """Upload a pre-produced canonical reference image to any canon slot.

    Admin-only. Designed for beta tuning by the content team. Supports:
    - Face canon: face_front, face_three_quarter_left, face_three_quarter_right
    - Body canon: body_front, body_left, body_right, body_back, body_map,
                  final_character_card
    - Accessory canon: accessory_design, accessory_fit
    - Legacy: tattoo_layout

    Does NOT delete or reset any existing body canon markings.
    Does NOT affect normal generation or library flows.
    """
    _require_admin(current_user)

    if target_slot not in _CANON_IMPORT_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"target_slot must be one of: {sorted(_CANON_IMPORT_SLOTS)}",
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
    kind = _SLOT_IMAGE_KIND[target_slot]

    # Archive any existing active CharacterImage for this kind
    db.query(CharacterImage).filter(
        CharacterImage.character_id == character_id,
        CharacterImage.kind == kind,
    ).update({"status": ImageStatusEnum.ARCHIVED})

    _import_pack_version = get_pack_version(char)
    meta: dict = {
        "source": "admin_canon_import",
        "admin_email": current_user.email,
        "pack_version": _import_pack_version,
        "canon_slot": target_slot,
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

    # ── Store slot entry in identity_anchor_json ──────────────────
    slot_entry = {
        "url": image_url,
        "status": "locked",
        "prompt": None,
        "source": "admin_canon_import",
        "pack_version": _import_pack_version,
    }

    if target_slot in _FACE_CANON_SLOTS:
        # Face canon slots → identity_anchor_json["anchors"]
        _face_anchor_key_map = {
            "face_front": "front",
            "face_three_quarter_left": "three_quarter",
            "face_three_quarter_right": "three_quarter",
        }
        anchor_key = _face_anchor_key_map[target_slot]
        try:
            anchor_data = _json.loads(char.identity_anchor_json or "{}")
        except (ValueError, TypeError):
            anchor_data = {}
        anchors = anchor_data.get("anchors") or {}
        anchors[anchor_key] = {"url": image_url, "id": ci.id}
        anchor_data["anchors"] = anchors
        char.identity_anchor_json = _json.dumps(anchor_data)
    elif target_slot in _ACCESSORY_CANON_SLOTS:
        # Accessory slots → identity_anchor_json["accessory_slots"]
        try:
            anchor_data = _json.loads(char.identity_anchor_json or "{}")
        except (ValueError, TypeError):
            anchor_data = {}
        acc_slots = anchor_data.get("accessory_slots") or {}
        acc_slots[target_slot] = slot_entry
        anchor_data["accessory_slots"] = acc_slots
        char.identity_anchor_json = _json.dumps(anchor_data)
    else:
        # Body canon slots → body_slots
        _save_body_slot(char, target_slot, slot_entry)

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
