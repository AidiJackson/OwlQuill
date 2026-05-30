"""Identity Canon API — clean single source of truth for character identity.

Routes:
  GET    /{character_id}/identity-canon                        Get full canon state
  PATCH  /{character_id}/identity-canon/face                  Update face canon fields
  POST   /{character_id}/identity-canon/face/lock             Lock face canon
  PATCH  /{character_id}/identity-canon/body                  Update body canon fields
  POST   /{character_id}/identity-canon/body/lock             Lock body canon
  POST   /{character_id}/identity-canon/body/marks            Add permanent body mark
  DELETE /{character_id}/identity-canon/body/marks/{mark_id}  Remove permanent body mark
  POST   /{character_id}/identity-canon/accessories           Add removable accessory
  DELETE /{character_id}/identity-canon/accessories/{acc_id}  Remove accessory
  POST   /{character_id}/identity-canon/upload                [Admin] Upload image to canon slot
  POST   /{character_id}/identity-canon/upload/mark/{mark_id} [Admin] Upload reference for a mark
  POST   /{character_id}/identity-canon/scenes/generate       Generate scene from locked canon

All writes require character ownership.
Admin upload requires admin role.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import save_image, load_image_bytes
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.user import User
from app.schemas.canon import (
    AddAccessoryRequest,
    AddPermanentMarkRequest,
    BodyCanonUpdate,
    CANON_UPLOAD_SLOTS,
    CharacterCanonRead,
    FaceCanonUpdate,
    PermanentBodyMark,
    RemovableAccessory,
    SLOT_FIELD_MAP,
)
from app.schemas.character_image import CharacterImageRead
from app.services.canon_compiler import compile_canon_prompt, has_any_canon_content
from app.services.scene_router import route_canon_refs
from app.services.canon_service import (
    add_accessory,
    add_permanent_mark,
    assign_accessory_image,
    assign_canon_slot_image,
    assign_mark_reference_image,
    get_or_create_canon,
    load_accessories,
    load_body_canon,
    load_face_canon,
    lock_body_canon,
    lock_face_canon,
    remove_accessory,
    remove_permanent_mark,
    update_body_canon,
    update_face_canon,
)
from app.services.image_provider import get_provider_for_option, get_fallback_provider
from app.services.stub_image_generator import generate_placeholder_png

logger = logging.getLogger(__name__)

router = APIRouter()

_CANON_IMPORT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


# ── Guards ────────────────────────────────────────────────────────────

def _get_owned_character(character_id: int, user: User, db: Session) -> CharacterModel:
    char = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found.")
    if char.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You don't own this character.")
    return char


def _require_admin(user: User) -> None:
    is_admin = bool(user.is_admin) or user.email.lower() in settings.get_admin_emails()
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")


def _canon_to_read(canon: CharacterIdentityCanon) -> CharacterCanonRead:
    """Serialize a CharacterIdentityCanon ORM record to the read schema."""
    return CharacterCanonRead(
        id=canon.id,
        character_id=canon.character_id,
        status=canon.status,
        face_canon=load_face_canon(canon),
        body_canon=load_body_canon(canon),
        accessories=load_accessories(canon),
        face_locked=canon.face_locked,
        body_locked=canon.body_locked,
        created_at=canon.created_at,
        updated_at=canon.updated_at,
        locked_at=canon.locked_at,
    )


# ── GET full canon ────────────────────────────────────────────────────

@router.get(
    "/{character_id}/identity-canon",
    response_model=CharacterCanonRead,
    summary="Get the full identity canon for a character",
)
def get_canon(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterCanonRead:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    db.commit()
    return _canon_to_read(canon)


# ── Face canon ────────────────────────────────────────────────────────

@router.patch(
    "/{character_id}/identity-canon/face",
    response_model=CharacterCanonRead,
    summary="Update face canon fields",
)
def patch_face_canon(
    character_id: int,
    body: FaceCanonUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterCanonRead:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    update_face_canon(canon, body)
    db.commit()
    db.refresh(canon)
    return _canon_to_read(canon)


@router.post(
    "/{character_id}/identity-canon/face/lock",
    response_model=CharacterCanonRead,
    summary="Lock face canon — requires face_front_image_url to be set",
)
def lock_face(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterCanonRead:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    try:
        lock_face_canon(canon)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    db.refresh(canon)
    logger.info("CANON_FACE_LOCKED character_id=%s", character_id)
    return _canon_to_read(canon)


# ── Body canon ────────────────────────────────────────────────────────

@router.patch(
    "/{character_id}/identity-canon/body",
    response_model=CharacterCanonRead,
    summary="Update body canon anatomy fields",
)
def patch_body_canon(
    character_id: int,
    body: BodyCanonUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterCanonRead:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    update_body_canon(canon, body)
    db.commit()
    db.refresh(canon)
    return _canon_to_read(canon)


@router.post(
    "/{character_id}/identity-canon/body/lock",
    response_model=CharacterCanonRead,
    summary="Lock body canon — requires body_front_image_url to be set",
)
def lock_body(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterCanonRead:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    try:
        lock_body_canon(canon)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    db.refresh(canon)
    logger.info("CANON_BODY_LOCKED character_id=%s", character_id)
    return _canon_to_read(canon)


# ── Permanent body marks ──────────────────────────────────────────────

class MarkResponse(BaseModel):
    character_id: int
    mark: PermanentBodyMark
    canon: CharacterCanonRead


@router.post(
    "/{character_id}/identity-canon/body/marks",
    response_model=MarkResponse,
    status_code=201,
    summary="Add a permanent body mark to body canon",
)
def add_mark(
    character_id: int,
    req: AddPermanentMarkRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkResponse:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    mark = add_permanent_mark(canon, req)
    db.commit()
    db.refresh(canon)
    return MarkResponse(character_id=character_id, mark=mark, canon=_canon_to_read(canon))


@router.delete(
    "/{character_id}/identity-canon/body/marks/{mark_id}",
    response_model=CharacterCanonRead,
    summary="Remove a permanent body mark from body canon",
)
def delete_mark(
    character_id: int,
    mark_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterCanonRead:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    found = remove_permanent_mark(canon, mark_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Mark '{mark_id}' not found.")
    db.commit()
    db.refresh(canon)
    return _canon_to_read(canon)


# ── Removable accessories ─────────────────────────────────────────────

class AccessoryResponse(BaseModel):
    character_id: int
    accessory: RemovableAccessory
    canon: CharacterCanonRead


@router.post(
    "/{character_id}/identity-canon/accessories",
    response_model=AccessoryResponse,
    status_code=201,
    summary="Add a removable accessory",
)
def add_acc(
    character_id: int,
    req: AddAccessoryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessoryResponse:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    acc = add_accessory(canon, req)
    db.commit()
    db.refresh(canon)
    return AccessoryResponse(character_id=character_id, accessory=acc, canon=_canon_to_read(canon))


@router.delete(
    "/{character_id}/identity-canon/accessories/{acc_id}",
    response_model=CharacterCanonRead,
    summary="Remove a removable accessory",
)
def delete_acc(
    character_id: int,
    acc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterCanonRead:
    _get_owned_character(character_id, current_user, db)
    canon = get_or_create_canon(character_id, db)
    found = remove_accessory(canon, acc_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Accessory '{acc_id}' not found.")
    db.commit()
    db.refresh(canon)
    return _canon_to_read(canon)


# ── Admin upload ──────────────────────────────────────────────────────

class CanonUploadResponse(BaseModel):
    character_id: int
    slot: str
    url: str
    canon: CharacterCanonRead


@router.post(
    "/{character_id}/identity-canon/upload",
    response_model=CanonUploadResponse,
    status_code=201,
    summary="[Admin] Upload an image to a canon slot",
)
async def admin_upload_canon_image(
    character_id: int,
    file: UploadFile = File(...),
    slot: str = Form(..., description=(
        "Canon slot: face_front | face_left_3q | face_right_3q | face_expression | "
        "body_front | body_left | body_right | body_back | body_map | final_character_card"
    )),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanonUploadResponse:
    """Upload an image to a specific canon slot. Admin only.

    Accepts: face_front, face_left_3q, face_right_3q, face_expression,
             body_front, body_left, body_right, body_back, body_map,
             final_character_card

    This is the primary workflow for beta tuning with manually-produced
    reference images. Does not affect scene generation directly — canon
    must be locked after upload for generation to use it.
    """
    _require_admin(current_user)
    _get_owned_character(character_id, current_user, db)

    if slot not in SLOT_FIELD_MAP:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown slot {slot!r}. Valid slots: {sorted(SLOT_FIELD_MAP.keys())}",
        )

    content_type = file.content_type or ""
    if content_type not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(status_code=422, detail="Only PNG, JPEG, or WebP images accepted.")

    raw = await file.read()
    if len(raw) > _CANON_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit.")

    image_url = save_image(raw)
    canon = get_or_create_canon(character_id, db)
    assign_canon_slot_image(canon, slot, image_url)
    db.commit()
    db.refresh(canon)

    logger.info(
        "ADMIN_CANON_UPLOAD character_id=%s slot=%s url=%s admin=%s",
        character_id, slot, image_url, current_user.email,
    )
    return CanonUploadResponse(
        character_id=character_id,
        slot=slot,
        url=image_url,
        canon=_canon_to_read(canon),
    )


@router.post(
    "/{character_id}/identity-canon/upload/mark/{mark_id}",
    response_model=CanonUploadResponse,
    status_code=201,
    summary="[Admin] Upload a reference image for a permanent body mark",
)
async def admin_upload_mark_reference(
    character_id: int,
    mark_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanonUploadResponse:
    _require_admin(current_user)
    _get_owned_character(character_id, current_user, db)

    content_type = file.content_type or ""
    if content_type not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(status_code=422, detail="Only PNG, JPEG, or WebP images accepted.")

    raw = await file.read()
    if len(raw) > _CANON_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit.")

    image_url = save_image(raw)
    canon = get_or_create_canon(character_id, db)
    found = assign_mark_reference_image(canon, mark_id, image_url)
    if not found:
        raise HTTPException(status_code=404, detail=f"Mark '{mark_id}' not found.")
    db.commit()
    db.refresh(canon)

    return CanonUploadResponse(
        character_id=character_id,
        slot=f"mark/{mark_id}",
        url=image_url,
        canon=_canon_to_read(canon),
    )


# ── Scene generation from locked canon ───────────────────────────────

class SceneGenerateRequest(BaseModel):
    prompt: str
    include_accessories: bool = True
    provider_option: str = "option1"


@router.post(
    "/{character_id}/identity-canon/scenes/generate",
    response_model=CharacterImageRead,
    summary="Generate a scene image using the character's locked canon",
)
def generate_scene_from_canon(
    character_id: int,
    req: SceneGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterImageRead:
    """Generate a scene image using the character's locked identity canon.

    Uses face and body images as reference anchors.
    Compiles prompt in strict order: face → body → marks → accessories → scene.
    Saves result as SCENE_ONLY — never updates canon.

    Logging covers: payload, compiled prompt, selected references,
    image kind, provider response, saved record.
    """
    char = _get_owned_character(character_id, current_user, db)

    canon = db.query(CharacterIdentityCanon).filter(
        CharacterIdentityCanon.character_id == character_id
    ).first()

    # ── Compile prompt ────────────────────────────────────────────
    if canon and has_any_canon_content(canon):
        compiled_prompt = compile_canon_prompt(
            canon,
            req.prompt,
            include_accessories=req.include_accessories,
        )
        # P10: scene-aware reference routing replaces static ordering.
        reference_urls, scene_meta = route_canon_refs(req.prompt, canon)
        using_canon = True
    else:
        compiled_prompt = req.prompt
        reference_urls = []
        scene_meta = None
        using_canon = False

    logger.info(
        "SCENE_GEN_START character_id=%s using_canon=%s camera=%s routed=%s "
        "exposure=%s refs=%d prompt_len=%d prompt_preview=%r",
        character_id,
        using_canon,
        scene_meta.camera if scene_meta else "n/a",
        scene_meta.routed if scene_meta else False,
        scene_meta.exposure if scene_meta else [],
        len(reference_urls),
        len(compiled_prompt),
        compiled_prompt[:120],
    )

    # ── Load reference image bytes ────────────────────────────────
    ref_bytes: list[bytes] = []
    for url in reference_urls[:6]:  # cap at 6 reference images
        try:
            b = load_image_bytes(url)
            ref_bytes.append(b)
            logger.info("SCENE_GEN_REF_LOADED url=%s bytes=%d", url, len(b))
        except Exception as exc:
            logger.warning("SCENE_GEN_REF_LOAD_FAILED url=%s error=%r", url, str(exc))

    # ── Generate ──────────────────────────────────────────────────
    provider_name = "stub"
    png_bytes: bytes | None = None

    try:
        provider = get_provider_for_option(req.provider_option)
    except (RuntimeError, ValueError):
        provider = None

    if provider is not None and ref_bytes:
        try:
            png_bytes = provider.generate_with_anchors(
                prompt=compiled_prompt,
                anchor_images=ref_bytes,
            )
            provider_name = settings.IMAGE_PROVIDER.lower()
            logger.info("SCENE_GEN_MULTI_IMAGE_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            logger.info("SCENE_GEN_MULTI_IMAGE_FAILED character_id=%s fallback=grounded", character_id)

    if png_bytes is None and provider is not None and ref_bytes:
        try:
            png_bytes = provider.generate_grounded_image(
                prompt=compiled_prompt,
                reference_image_bytes=ref_bytes[0],
            )
            provider_name = settings.IMAGE_PROVIDER.lower()
            logger.info("SCENE_GEN_GROUNDED_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            logger.info("SCENE_GEN_GROUNDED_FAILED character_id=%s fallback=text", character_id)

    if png_bytes is None and provider is not None:
        try:
            png_bytes = provider.generate_image(prompt=compiled_prompt)
            provider_name = settings.IMAGE_PROVIDER.lower()
            logger.info("SCENE_GEN_TEXT_ONLY_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError):
            logger.info("SCENE_GEN_TEXT_FAILED character_id=%s fallback=stub", character_id)

    if png_bytes is None:
        fallback = get_fallback_provider()
        if fallback is not None:
            try:
                png_bytes = fallback.generate_image(prompt=compiled_prompt)
                provider_name = "fal"
                logger.info("SCENE_GEN_FAL_SUCCESS character_id=%s", character_id)
            except (ValueError, RuntimeError):
                pass

    if png_bytes is not None:
        file_path = save_image(png_bytes)
    else:
        file_path = generate_placeholder_png(
            label=f"{char.name} — scene",
            sublabel=req.prompt[:80],
            role="scene_only",
        )
        provider_name = "stub"
        logger.info("SCENE_GEN_STUB character_id=%s", character_id)

    # ── Save as SCENE_ONLY — NEVER update canon ───────────────────
    img = CharacterImage(
        character_id=character_id,
        user_id=current_user.id,
        kind=ImageKindEnum.SCENE_ONLY,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider_name,
        prompt_summary=req.prompt[:200],
        metadata_json={
            "scene_only": True,
            "canon_used": using_canon,
            "refs_count": len(ref_bytes),
            "compiled_prompt": compiled_prompt[:400],
            "provider": provider_name,
        },
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    logger.info(
        "SCENE_GEN_SAVED image_id=%s character_id=%s kind=%s provider=%s",
        img.id, character_id, img.kind, provider_name,
    )

    from app.schemas.character_image import CharacterImageRead as _CIR
    return _CIR.model_validate(img)
