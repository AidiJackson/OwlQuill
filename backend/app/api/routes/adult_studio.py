"""Adult Studio (18+ Studio) endpoints — SEPARATE from Canon Studio.

Routes (mounted under /adult-studio):
  GET  /adult-studio/characters/{id}            → current 18+ identity status
  POST /adult-studio/characters/{id}/prepare    → build identity manifest from canon
  POST /adult-studio/characters/{id}/generate   → generate an adult-adjacent image

This module READS the locked Canon Pack as source truth. It NEVER routes through
the Canon Studio generator (image_generator.generate_image), never mutates canon,
and never touches Identity OS / Scene Router / Canon Router / tattoo routing.
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.api.routes.admin import require_admin
from app.core.storage import save_image, file_path_to_url
from app.models.user import User
from app.models.character import Character as CharacterModel
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
)
from app.services import adult_studio as svc
from app.services.provider_capabilities import Capability, provider_supports
from app.services.adult_identity_preparation import (
    CanonNotReadyError,
    prepare_adult_identity,
)

logger = logging.getLogger(__name__)

# S24D FIX 2: the explicit-image Adult Studio surface is ADMIN-ONLY, enforced in
# code at the router level so every current and future route requires an admin
# caller (not just the ownership check). ADULT_STUDIO_GENERATION_ENABLED remains a
# defense-in-depth kill-switch, but admin is now the primary gate.
router = APIRouter(dependencies=[Depends(require_admin)])

_ADULT_PROVIDER_NAME = "openai"


def _get_adult_provider():
    """Instantiate the Adult Studio image provider (OpenAI admin path).

    Wrapped so tests can patch it. Adult Studio reuses the OpenAI multi-image
    provider but is invoked ONLY from here with adult-specific framing — it does
    not go through the Canon Studio generator.
    """
    from app.services.image_provider import get_identity_provider_by_name
    return get_identity_provider_by_name(_ADULT_PROVIDER_NAME)


# ── Schemas ────────────────────────────────────────────────────────────


class AdultStudioMarkRoute(BaseModel):
    """One permanent mark's resolved render route (from the new mark-render plan)."""

    canon_mark_id: str
    region: Optional[str] = None
    side: Optional[str] = None
    route: str
    reason: Optional[str] = None


class AdultStudioStatusResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    character_id: int
    # status now comes from the 6-value AdultIdentityModel vocabulary:
    #   not_trained | prepared | training | ready | stale | failed
    status: str
    provider: Optional[str] = None
    model_ref: Optional[str] = None
    refs_count: int = 0
    marks_count: int = 0
    # ── Phase 2 additive fields (read from AdultIdentityModel) ────────────
    canon_fingerprint: Optional[str] = None
    stale: bool = False
    active_version_id: Optional[int] = None
    version_index: Optional[int] = None
    marks: list[AdultStudioMarkRoute] = []
    # Echo the env flags so the UI can gate itself (both False in Phase 2).
    training_enabled: bool = False
    generation_enabled: bool = False


class AdultStudioGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=800)
    style: Optional[str] = None
    settings: Optional[dict] = None


class AdultStudioGenerateResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    image_url: str
    provider: str
    model_ref: Optional[str] = None
    refs_count: int
    used_refs: list[str]
    multi_image_used: bool
    failure_reason: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────


def _require_owned_character(character_id: int, current_user: User, db: Session) -> CharacterModel:
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this character.",
        )
    return character


def _load_locked_canon(character_id: int, db: Session) -> CharacterIdentityCanon:
    canon = (
        db.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == character_id)
        .first()
    )
    if not canon or not (canon.face_locked and canon.body_locked):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Character canon must be locked (face and body) before preparing "
                "an 18+ Studio identity."
            ),
        )
    return canon


def _not_prepared_payload(character_id: int) -> AdultStudioStatusResponse:
    """Status for a character that has no AdultIdentityModel yet (echoes flags)."""
    return AdultStudioStatusResponse(
        character_id=character_id,
        status="not_trained",
        training_enabled=settings.ADULT_STUDIO_TRAINING_ENABLED,
        generation_enabled=settings.ADULT_STUDIO_GENERATION_ENABLED,
    )


def _status_payload_from_model(
    model: AdultIdentityModel, db: Session
) -> AdultStudioStatusResponse:
    """Build the status response from the new AdultIdentityModel + its render plan."""
    manifest = model.prepared_manifest_json or {}

    mark_rows = (
        db.query(AdultIdentityMarkRender)
        .filter(AdultIdentityMarkRender.identity_id == model.id)
        .all()
    )
    marks = [
        AdultStudioMarkRoute(
            canon_mark_id=r.canon_mark_id,
            region=r.body_region,
            side=r.side,
            route=r.route,
            reason=(r.params_json or {}).get("reason"),
        )
        for r in mark_rows
    ]

    version_index: Optional[int] = None
    if model.active_version_id is not None:
        version = db.get(AdultIdentityModelVersion, model.active_version_id)
        if version is not None:
            version_index = version.version_index

    return AdultStudioStatusResponse(
        character_id=model.character_id,
        status=model.status,
        provider=model.provider,
        model_ref=model.base_model,
        refs_count=len(manifest.get("refs") or []),
        marks_count=len(manifest.get("marks") or []),
        canon_fingerprint=model.canon_fingerprint,
        stale=(model.status == "stale"),
        active_version_id=model.active_version_id,
        version_index=version_index,
        marks=marks,
        training_enabled=settings.ADULT_STUDIO_TRAINING_ENABLED,
        generation_enabled=settings.ADULT_STUDIO_GENERATION_ENABLED,
    )


# ── Endpoints ──────────────────────────────────────────────────────────


@router.get(
    "/characters/{character_id}",
    response_model=AdultStudioStatusResponse,
    summary="Get the 18+ Studio identity status for a character",
)
def get_adult_studio_status(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_owned_character(character_id, current_user, db)
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if not model:
        return _not_prepared_payload(character_id)
    return _status_payload_from_model(model, db)


@router.post(
    "/characters/{character_id}/prepare",
    response_model=AdultStudioStatusResponse,
    summary="Prepare an 18+ Studio identity manifest from the locked Canon Pack",
)
def prepare_adult_studio_identity(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Prepare the 18+ identity on the new AdultIdentityModel system.

    Bridges onto Phase 1's idempotent ``prepare_adult_identity``: it loads LOCKED
    canon (read-only), computes the canon fingerprint, resolves every permanent mark
    to a render route, and upserts the AdultIdentityModel (creates as 'prepared';
    flips 'stale' on a canon change). The legacy adult_studio_identities table is NOT
    written. No training, no generation, no provider, no external call.
    """
    character = _require_owned_character(character_id, current_user, db)

    try:
        prepare_adult_identity(character_id, db)
    except CanonNotReadyError:
        # Same UX as before: lock canon (face + body) first.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Character canon must be locked (face and body) before preparing "
                "an 18+ Studio identity."
            ),
        )

    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )

    # Persist the source manifest on the new model so ref counts and the offline
    # training-pack keep working (no provider, no network — pure canon packaging).
    canon = _load_locked_canon(character_id, db)
    manifest = svc.build_manifest(canon)
    if not manifest.get("refs"):
        model.last_error = "no_canon_refs"
        model.status = "failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Canon has no usable reference images to prepare an 18+ identity.",
        )
    model.prepared_manifest_json = manifest
    db.commit()
    db.refresh(model)

    logger.info(
        "adult_studio prepared character_id=%s status=%s refs=%d marks=%d",
        character_id, model.status,
        len(manifest.get("refs") or []), len(manifest.get("marks") or []),
    )
    _ = character  # ownership already validated
    return _status_payload_from_model(model, db)


@router.post(
    "/characters/{character_id}/generate",
    response_model=AdultStudioGenerateResponse,
    summary="Generate an adult-adjacent image through Adult Studio (no Canon Studio routing)",
)
def generate_adult_studio_image(
    character_id: int,
    body: AdultStudioGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Phase 2: generation is disabled by default. Return 409 BEFORE constructing
    # any provider or touching canon — guarantees no provider/no external call.
    if not settings.ADULT_STUDIO_GENERATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adult Studio generation is disabled in this environment.",
        )

    character = _require_owned_character(character_id, current_user, db)

    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if not model or model.status not in ("prepared", "ready", "stale"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prepare the 18+ Studio identity for this character first.",
        )
    rec = model  # alias: downstream provider path reads the manifest/model_ref below

    # Safety gate — block minors / illegal content. Adult-adjacent is allowed.
    block_reason = svc.check_prompt_safety(body.prompt)
    if block_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=block_reason)

    manifest = rec.prepared_manifest_json or {}
    ref_bytes, ref_roles = svc.load_manifest_refs(manifest)
    refs_count = len(ref_bytes)

    prompt = svc.build_adult_prompt(body.prompt, manifest, character_name=character.name)

    base_meta = {
        "provider": _ADULT_PROVIDER_NAME,
        "model_ref": rec.base_model or settings.IMAGE_MODEL,
        "refs_count": refs_count,
        "used_refs": ref_roles,
    }

    if refs_count == 0:
        # No usable references — do NOT silently fall back to text-only.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={**base_meta, "multi_image_used": False,
                    "failure_reason": "no_canon_refs_available"},
        )

    # Instantiate provider (may raise if creds missing) — surface as clear error.
    try:
        provider = _get_adult_provider()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={**base_meta, "multi_image_used": False,
                    "failure_reason": f"provider_unavailable: {exc}"},
        )

    if not provider_supports(provider, Capability.MULTI_IMAGE_ANCHORS):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={**base_meta, "multi_image_used": False,
                    "failure_reason": "provider_no_multi_image_support"},
        )

    # Multi-image conditioned generation. On failure, return clear metadata —
    # NO silent fallback to text-only generation.
    try:
        png = provider.generate_with_anchors(prompt=prompt, anchor_images=ref_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("adult_studio generate failed character_id=%s err=%r", character_id, str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={**base_meta, "multi_image_used": False,
                    "failure_reason": f"provider_error: {exc}"},
        )

    if not png or len(png) < 1000:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={**base_meta, "multi_image_used": False,
                    "failure_reason": "empty_image_returned"},
        )

    file_path = save_image(png)
    image_url = file_path_to_url(file_path)

    logger.info(
        "adult_studio generated character_id=%s refs=%d bytes=%d",
        character_id, refs_count, len(png),
    )
    return AdultStudioGenerateResponse(
        image_url=image_url,
        provider=_ADULT_PROVIDER_NAME,
        model_ref=rec.base_model or settings.IMAGE_MODEL,
        refs_count=refs_count,
        used_refs=ref_roles,
        multi_image_used=True,
        failure_reason=None,
    )


@router.post(
    "/characters/{character_id}/train",
    response_model=AdultStudioStatusResponse,
    summary="Train the 18+ identity model (disabled by default → 409)",
)
def train_adult_studio_identity(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kick off identity training. DISABLED in Phase 2.

    With ``ADULT_STUDIO_TRAINING_ENABLED`` false (the default) this returns 409 BEFORE
    any provider is constructed — no TrainingProvider, no RunPod/Replicate, no external
    call, no GPU, no spend. When the flag is enabled in a later phase this will drive
    AdultIdentityTrainingService through the configured provider.
    """
    if not settings.ADULT_STUDIO_TRAINING_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Adult Studio training is disabled in this environment.",
        )

    # Unreachable while disabled — ownership/precondition checks live here for when
    # the flag is turned on in a later sprint.
    _require_owned_character(character_id, current_user, db)
    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if not model or model.status not in ("prepared", "stale"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prepare the 18+ Studio identity for this character first.",
        )
    return _status_payload_from_model(model, db)


@router.get(
    "/characters/{character_id}/training-pack",
    summary="Export a per-character SDXL LoRA training pack (ZIP) from the manifest",
)
def export_adult_studio_training_pack(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Package the prepared Adult Studio manifest into a downloadable training ZIP.

    Offline only — packages locked-canon references + captions for SDXL LoRA
    training OUTSIDE Ficshon. Does NOT train, generate, or call any provider.
    """
    character = _require_owned_character(character_id, current_user, db)

    model = (
        db.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == character_id)
        .first()
    )
    if not model or model.status not in ("prepared", "ready", "stale"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prepare the 18+ Studio identity for this character first.",
        )

    manifest = model.prepared_manifest_json or {}
    if not (manifest.get("refs")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No identity manifest references are available to export.",
        )

    try:
        zip_bytes, summary = svc.build_training_pack(
            manifest, character_id=character_id, character_name=character.name
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("adult_studio training-pack failed character_id=%s err=%r", character_id, str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build training pack: {exc}",
        )

    if summary["image_count"] == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No reference images could be loaded for the training pack.",
        )

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", character.name or "character").strip("_") or "character"
    filename = f"ficshon_training_pack_{safe_name}_{character_id}.zip"

    logger.info(
        "adult_studio training-pack exported character_id=%s images=%d skipped=%d",
        character_id, summary["image_count"], len(summary["skipped"]),
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Training-Pack-Images": str(summary["image_count"]),
            "X-Training-Pack-Trigger": summary["trigger_token"],
        },
    )
