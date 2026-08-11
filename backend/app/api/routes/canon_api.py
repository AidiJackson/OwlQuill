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
from app.core.dependencies import get_current_user, get_owned_character, user_is_admin
from app.core.storage import save_image, load_image_bytes, file_path_to_url
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.user import User
from app.schemas.canon import (
    AddAccessoryRequest,
    AddPermanentMarkRequest,
    BodyCanonUpdate,
    CharacterCanonRead,
    FaceCanonUpdate,
    PermanentBodyMark,
    RemovableAccessory,
    SLOT_FIELD_MAP,
)
from app.schemas.character_image import CharacterImageRead
from app.services.canon_compiler import compile_canon_prompt, has_any_canon_content
from app.services.scene_router import (
    route_canon_refs,
    routing_diagnostics as _routing_diagnostics,
)
from app.services.canon_service import (
    add_accessory,
    add_permanent_mark,
    assign_canon_slot_image,
    assign_mark_detail_crop,
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
from app.services.image_provider import (
    get_provider_for_option,
    get_fallback_provider,
    resolve_canon_provider_option,
)
from app.services.stub_image_generator import generate_placeholder_png

logger = logging.getLogger(__name__)

router = APIRouter()

_CANON_IMPORT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# Bound on the diagnostic copy of the compiled prompt stored on each image
# record. Above _PROMPT_CAP (2400) so the stored value is the whole prompt in
# every non-pathological case, while still capping storage growth. The previous
# 400-char cut is why a real visual-QA investigation had to replay the compiler
# to recover what had actually been sent to the provider.
_STORED_PROMPT_CHARS = 4000


# ── Guards ────────────────────────────────────────────────────────────

def _get_owned_character(character_id: int, user: User, db: Session) -> CharacterModel:
    # Canon API keeps its original, distinct 403 message.
    return get_owned_character(
        character_id, user, db, not_owner_detail="You don't own this character."
    )


def _require_admin(user: User) -> None:
    if not user_is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")


def _servable(model, *fields):
    """Rewrite stored file paths on ``model`` into browser-servable URLs.

    Storage keeps whatever :func:`app.core.storage.save_image` returned: an
    absolute ``https://`` R2 URL in object-storage mode, or a bare relative
    ``static/generated/<uuid>.png`` on local disk. Only the first is safe to
    hand a browser. The second has no leading slash, so an ``<img>`` on a route
    like ``/characters/42`` resolves it against the CURRENT PATH and requests
    ``/characters/static/generated/...`` — which the SPA catch-all answers with
    index.html: HTTP 200, Content-Type text/html. The browser cannot decode
    that as an image and falls back to the alt text, which is why the panels
    read "Front Face", "Left ¾"… while every server-side check looked healthy.

    ``file_path_to_url`` is the codebase's existing answer to this and is
    already applied by the character, user, editor and adult-studio routes.
    The canon routes were the outlier that returned raw storage values.

    Read-side only: the routing and prompt-compiler layers keep reading the
    stored value through ``load_image_bytes``, which expects the raw path.
    Nothing is written back, so no stored data changes.
    """
    if model is None:
        return None
    for field in fields:
        value = getattr(model, field, None)
        if isinstance(value, str) and value:
            setattr(model, field, file_path_to_url(value))
    return model


_FACE_URL_FIELDS = (
    "face_front_image_url", "face_left_3q_image_url", "face_right_3q_image_url",
    "face_profile_image_url", "face_expression_image_url",
)
_BODY_URL_FIELDS = (
    "body_front_image_url", "body_left_image_url", "body_right_image_url",
    "body_back_image_url", "body_map_image_url", "final_character_card_image_url",
    "torso_front_image_url", "torso_side_image_url",
    "standing_relaxed_image_url", "seated_relaxed_image_url",
)
_MARK_URL_FIELDS = ("reference_image_url", "detail_crop_url")
_ACCESSORY_URL_FIELDS = ("design_anchor_image_url", "fit_anchor_image_url")


def _canon_to_read(canon: CharacterIdentityCanon) -> CharacterCanonRead:
    """Serialize a CharacterIdentityCanon ORM record to the read schema."""
    face = _servable(load_face_canon(canon), *_FACE_URL_FIELDS)
    body = _servable(load_body_canon(canon), *_BODY_URL_FIELDS)
    if body is not None:
        for mark in body.permanent_body_marks:
            _servable(mark, *_MARK_URL_FIELDS)
    accessories = [
        _servable(a, *_ACCESSORY_URL_FIELDS) for a in load_accessories(canon)
    ]
    return CharacterCanonRead(
        id=canon.id,
        character_id=canon.character_id,
        status=canon.status,
        face_canon=face,
        body_canon=body,
        accessories=accessories,
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
        # Same normalisation as _canon_to_read: the UI renders this value
        # straight into the slot preview (onUploaded -> <img src>), so a raw
        # relative path would break the just-uploaded card until a reload.
        url=file_path_to_url(image_url),
        canon=_canon_to_read(canon),
    )


@router.post(
    "/{character_id}/identity-canon/upload/mark/{mark_id}",
    response_model=CanonUploadResponse,
    status_code=201,
    summary="[Admin] Upload a reference / detail-crop image for a permanent body mark",
)
async def admin_upload_mark_reference(
    character_id: int,
    mark_id: str,
    file: UploadFile = File(...),
    slot: str = Form("reference"),  # "reference" | "detail" (high-fidelity close-up)
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CanonUploadResponse:
    _require_admin(current_user)
    _get_owned_character(character_id, current_user, db)

    if slot not in ("reference", "detail"):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown mark image slot {slot!r}. Valid: 'reference', 'detail'.",
        )

    content_type = file.content_type or ""
    if content_type not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(status_code=422, detail="Only PNG, JPEG, or WebP images accepted.")

    raw = await file.read()
    if len(raw) > _CANON_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit.")

    image_url = save_image(raw)
    canon = get_or_create_canon(character_id, db)
    if slot == "detail":
        found = assign_mark_detail_crop(canon, mark_id, image_url)
    else:
        found = assign_mark_reference_image(canon, mark_id, image_url)
    if not found:
        raise HTTPException(status_code=404, detail=f"Mark '{mark_id}' not found.")
    db.commit()
    db.refresh(canon)

    return CanonUploadResponse(
        character_id=character_id,
        slot=f"mark/{mark_id}/{slot}",
        url=file_path_to_url(image_url),
        canon=_canon_to_read(canon),
    )


# ── Scene generation from locked canon ───────────────────────────────

class SceneGenerateRequest(BaseModel):
    prompt: str
    include_accessories: bool = True
    # Beta: Google (option2) is the default Canon provider; OpenAI (option1) is
    # admin-only and falls back to Google for non-admins (enforced server-side).
    provider_option: str = "option2"


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
    # prompt_diag is filled by the compiler on the pass it already performs
    # (which clauses were emitted, whether fitting ran) and persisted below, so
    # a visual-QA failure can be diagnosed from the record rather than by
    # replaying the compiler.
    prompt_diag: dict = {}
    if canon and has_any_canon_content(canon):
        compiled_prompt = compile_canon_prompt(
            canon,
            req.prompt,
            include_accessories=req.include_accessories,
            diagnostics=prompt_diag,
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
    loaded_urls: set[str] = set()
    for url in reference_urls[:6]:  # cap at 6 reference images
        try:
            b = load_image_bytes(url)
            ref_bytes.append(b)
            loaded_urls.add(url)
            logger.info("SCENE_GEN_REF_LOADED url=%s bytes=%d", url, len(b))
        except Exception as exc:
            logger.warning("SCENE_GEN_REF_LOAD_FAILED url=%s error=%r", url, str(exc))

    # Diagnostic: confirm which exposed permanent-mark image refs actually
    # reached the provider payload (routed AND successfully loaded into ref_bytes).
    # Covered/hidden marks never produce a binding, so they never log here.
    if scene_meta is not None:
        for binding in scene_meta.mark_crop_bindings:
            if binding.url in loaded_urls:
                logger.info(
                    "BODY_MARK_REF_USED character_id=%s mark_id=%s label=%r side=%s "
                    "region=%s source=%s",
                    character_id, binding.mark_id, binding.label, binding.side,
                    binding.body_region, binding.source,
                )

    # ── Generate ──────────────────────────────────────────────────
    provider_name = "stub"
    png_bytes: bytes | None = None

    # Beta gating: OpenAI (option1) is admin-only; non-admins fall back to Google.
    effective_option, provider_gate_meta = resolve_canon_provider_option(
        req.provider_option, is_admin=bool(current_user.is_admin)
    )
    if provider_gate_meta:
        logger.info(
            "SCENE_GEN_PROVIDER_GATED character_id=%s user_id=%s requested=%s effective=%s reason=%s",
            character_id, current_user.id, req.provider_option, effective_option,
            provider_gate_meta.get("provider_fallback_reason"),
        )

    try:
        provider = get_provider_for_option(effective_option)
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
            # Bounded well above _PROMPT_CAP (2400) so the stored value IS the
            # prompt in every non-pathological case. The old 400-char cut meant a
            # real visual-QA investigation had to replay the compiler to recover
            # what was actually sent.
            "compiled_prompt": compiled_prompt[:_STORED_PROMPT_CHARS],
            "compiled_prompt_len": len(compiled_prompt),
            "provider": provider_name,
            **({"prompt_diagnostics": prompt_diag} if prompt_diag else {}),
            **(_routing_diagnostics(scene_meta) if scene_meta is not None else {}),
            **provider_gate_meta,  # beta provider-gating audit trail (empty unless fallback)
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


# ── V2 canon pack generation (S24AN) ──────────────────────────────────
# Self-serve replacement for the legacy 4-anchor identity-pack path: generates
# all 13 v2 canon cards (+ permanent-mark detail crops) directly into canon via
# canon_card_generator. Gemini default; admin-only OpenAI fallback; dry-run +
# hard spend cap. Does NOT lock — the creation flow locks face/body separately.

_V2_PACK_SPEND_CEILING = 8.0  # hard $ ceiling; requests cannot raise above this


class V2PackGenerateRequest(BaseModel):
    dry_run: bool = False
    provider_option: str = "option2"   # option2=Gemini (default), option1=OpenAI (admin)
    admin_fallback: bool = False        # allow OpenAI retry after the gate fails twice
    max_spend: float = _V2_PACK_SPEND_CEILING


class V2PackCard(BaseModel):
    slot: str
    section: str                  # "face" | "body"
    role: str
    url: Optional[str] = None
    status: str                   # planned | generated | skipped | gate_failed | error
    provider: Optional[str] = None
    similarity: Optional[float] = None
    estimated_cost: Optional[float] = None
    prompt: Optional[str] = None
    grounds_on: Optional[list[str]] = None


class V2PackMark(BaseModel):
    label: str
    mark_id: str
    detail_crop_url: Optional[str] = None
    skipped: Optional[bool] = None
    estimated_cost: Optional[float] = None


class V2PackResponse(BaseModel):
    pack_id: str
    dry_run: bool
    cards: list[V2PackCard]
    marks: list[V2PackMark]
    total_spend: float = 0.0
    image_count: int = 0
    estimated_cost: Optional[float] = None
    regenerations: list[str] = []
    openai_fallback: list[str] = []
    gate_failed: list[str] = []
    errors: list[str] = []
    clean_pass: bool = False
    stopped: Optional[str] = None


@router.post(
    "/{character_id}/identity-canon/generate-v2-pack",
    response_model=V2PackResponse,
    summary="Generate the full v2 canon pack (13 cards + mark detail crops)",
)
def generate_v2_pack(
    character_id: int,
    req: V2PackGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> V2PackResponse:
    """Populate all 13 v2 canon slots (and any mark detail crops) for a character.

    Gemini is the default provider. OpenAI is used only as an admin-gated retry
    after the consistency gate fails twice. Spend is capped (hard ceiling $8).
    The canon is left UNLOCKED — callers lock face/body explicitly afterwards.
    """
    char = _get_owned_character(character_id, current_user, db)

    from app.services.canon_card_generator import SpendTracker
    from app.services.canon_pack_builder import (
        build_v2_pack,
        founder_identity_from_character,
    )

    canon = get_or_create_canon(character_id, db)
    identity = founder_identity_from_character(char, canon, db)

    is_admin = user_is_admin(current_user)
    cap = max(0.5, min(float(req.max_spend or _V2_PACK_SPEND_CEILING), _V2_PACK_SPEND_CEILING))
    spend = SpendTracker(cap_usd=cap)

    report = build_v2_pack(
        canon=canon, identity=identity, db=db, spend=spend,
        provider_option=req.provider_option, is_admin=is_admin,
        admin_fallback=bool(req.admin_fallback and is_admin),
        dry_run=req.dry_run,
    )

    logger.info(
        "V2_PACK_GEN character_id=%s dry_run=%s cards=%d marks=%d spend=$%.3f "
        "clean=%s openai_fallback=%d stopped=%s",
        character_id, req.dry_run, len(report["cards"]), len(report["marks"]),
        report["total_spend"], report["clean_pass"], len(report["openai_fallback"]),
        report["stopped"],
    )

    return V2PackResponse(
        pack_id=report["pack_id"],
        dry_run=report["dry_run"],
        cards=[V2PackCard(**c) for c in report["cards"]],
        marks=[V2PackMark(**m) for m in report["marks"]],
        total_spend=report["total_spend"],
        image_count=report["image_count"],
        estimated_cost=report.get("estimated_cost"),
        regenerations=report["regenerations"],
        openai_fallback=report["openai_fallback"],
        gate_failed=report["gate_failed"],
        errors=report["errors"],
        clean_pass=report["clean_pass"],
        stopped=report["stopped"],
    )


# ── Sprint 35: async v2 pack jobs (fire-and-poll) ─────────────────────
#
# POST /{id}/identity-canon/generate-v2-pack/jobs   submit → 202 + job view
# GET  /{id}/identity-canon/pack-jobs/latest        latest job (refresh recovery)
# GET  /{id}/identity-canon/pack-jobs/{public_id}   poll one job
#
# The synchronous generate-v2-pack route above is preserved unchanged (legacy/
# dev callers); the creation wizard uses these job endpoints. The expensive
# pipeline runs in a detached driver process — never inside these requests.

from datetime import datetime as _dt  # noqa: E402

from app.services import identity_pack_job_service as _pack_jobs  # noqa: E402
from app.models.identity_pack_job import IdentityPackJob  # noqa: E402


class V2PackJobSubmitRequest(BaseModel):
    provider_option: str = "option2"
    admin_fallback: bool = False
    max_spend: float = _V2_PACK_SPEND_CEILING
    # Client-generated key; identical resubmissions return the same job.
    idempotency_key: Optional[str] = None


class V2PackJobView(BaseModel):
    """Owner-visible job state. diag_json is internal and never serialised."""
    job_id: str
    character_id: int
    status: str                       # queued | running | completed | failed
    stage: Optional[str] = None
    progress_message: Optional[str] = None
    progress_percent: Optional[int] = None
    attempt_count: int = 0
    created_at: Optional[_dt] = None
    started_at: Optional[_dt] = None
    finished_at: Optional[_dt] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    reused: bool = False
    # True when this completed job predates an accepted/locked canon — the
    # wizard must not resurrect its snapshot as fresh candidates on refresh.
    superseded: bool = False
    result: Optional[V2PackResponse] = None


def _job_to_view(
    job: IdentityPackJob, *, reused: bool = False, superseded: bool = False
) -> V2PackJobView:
    result: Optional[V2PackResponse] = None
    if job.status == "completed" and job.result_json:
        r = job.result_json
        try:
            result = V2PackResponse(
                pack_id=r["pack_id"],
                dry_run=bool(r.get("dry_run")),
                cards=[V2PackCard(**c) for c in r.get("cards", [])],
                marks=[V2PackMark(**m) for m in r.get("marks", [])],
                total_spend=r.get("total_spend", 0.0),
                image_count=r.get("image_count", 0),
                estimated_cost=r.get("estimated_cost"),
                regenerations=r.get("regenerations", []),
                openai_fallback=r.get("openai_fallback", []),
                gate_failed=r.get("gate_failed", []),
                errors=r.get("errors", []),
                clean_pass=bool(r.get("clean_pass")),
                stopped=r.get("stopped"),
            )
        except Exception:  # noqa: BLE001 — malformed stored report must not 500 the poll
            logger.exception("pack job result deserialisation failed job=%s", job.public_id)
    return V2PackJobView(
        job_id=job.public_id,
        character_id=job.character_id,
        status=job.status,
        stage=job.stage,
        progress_message=job.progress_message,
        progress_percent=job.progress_percent,
        attempt_count=job.attempt_count or 0,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        error_message=job.error_message,
        reused=reused,
        superseded=superseded,
        result=result,
    )


def _job_superseded(db: Session, job: IdentityPackJob) -> bool:
    """A completed job is superseded once its pack has been accepted — i.e. the
    canon was locked (v2 Dossier lock) or the character's visual identity was
    locked (legacy accept) after generation. Its stored snapshot may no longer
    match the live canon slots, so refresh recovery must not re-present it."""
    if job.status != "completed":
        return False
    char = db.query(CharacterModel).filter(CharacterModel.id == job.character_id).first()
    if char is not None and char.visual_locked:
        return True
    canon = (
        db.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == job.character_id)
        .first()
    )
    return bool(canon is not None and (canon.face_locked or canon.body_locked))


@router.post(
    "/{character_id}/identity-canon/generate-v2-pack/jobs",
    response_model=V2PackJobView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an async v2 canon-pack generation job (Sprint 35)",
)
def submit_v2_pack_job(
    character_id: int,
    req: V2PackJobSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> V2PackJobView:
    """Validate, create (or return the existing active) job, respond immediately.

    The provider pipeline runs in a detached driver process; this request only
    writes the job row and launches the driver. If an active job already exists
    for the character, it is returned with ``reused=true`` — no new generation
    and no additional spend.
    """
    _get_owned_character(character_id, current_user, db)

    is_admin = user_is_admin(current_user)
    cap = max(0.5, min(float(req.max_spend or _V2_PACK_SPEND_CEILING), _V2_PACK_SPEND_CEILING))
    params = {
        "provider_option": req.provider_option or "option2",
        "admin_fallback": bool(req.admin_fallback and is_admin),
        "is_admin": is_admin,
        "max_spend": cap,
    }

    try:
        job, reused = _pack_jobs.start_identity_pack_job(
            db,
            character_id=character_id,
            user_id=current_user.id,
            params=params,
            idempotency_key=(req.idempotency_key or None),
        )
    except _pack_jobs.IdentityPackJobError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    logger.info(
        "V2_PACK_JOB_SUBMIT character_id=%s job=%s reused=%s status=%s",
        character_id, job.public_id, reused, job.status,
    )
    return _job_to_view(job, reused=reused)


@router.get(
    "/{character_id}/identity-canon/pack-jobs/latest",
    response_model=Optional[V2PackJobView],
    summary="Latest v2 pack job for this character (refresh recovery)",
)
def get_latest_v2_pack_job(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[V2PackJobView]:
    """Return the most recent job (any status), reconciling stale active jobs.

    Lets a refreshed browser rediscover an in-flight generation, or recover a
    completed pack it never displayed. Owner-only (admins may inspect too).
    """
    char = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found.")
    is_admin = user_is_admin(current_user)
    if char.owner_id != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="You don't own this character.")

    job = _pack_jobs.get_latest_job_reconciled(db, character_id)
    if job is None:
        return None
    return _job_to_view(job, superseded=_job_superseded(db, job))


@router.get(
    "/{character_id}/identity-canon/pack-jobs/{job_public_id}",
    response_model=V2PackJobView,
    summary="Poll one v2 pack job (owner or admin only)",
)
def get_v2_pack_job(
    character_id: int,
    job_public_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> V2PackJobView:
    """Poll a job. 404 for jobs that don't exist OR aren't visible to the caller."""
    char = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not char:
        raise HTTPException(status_code=404, detail="Job not found.")
    is_admin = user_is_admin(current_user)
    if char.owner_id != current_user.id and not is_admin:
        # Indistinguishable from nonexistent — never confirm another user's jobs.
        raise HTTPException(status_code=404, detail="Job not found.")

    job = _pack_jobs.get_job_for_owner(
        db, character_id=character_id, public_id=job_public_id
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _job_to_view(job, superseded=_job_superseded(db, job))
