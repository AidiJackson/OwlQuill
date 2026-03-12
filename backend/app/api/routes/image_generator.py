"""Simplified image generator endpoint with provider toggle (B17).

Replaces the mental model of 'scene generator' with a plain image generator:
  - Always tied to a character for ownership/auth
  - include_character controls whether identity references are injected
  - provider_option selects the backend provider (option1=OpenAI, option2=Google)
"""
import json as _json
import logging
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.character import Character as CharacterModel
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.schemas.character_image import CharacterImageRead
from app.services.image_provider import get_provider_for_option, get_fallback_provider
from app.services.stub_image_generator import generate_placeholder_png

logger = logging.getLogger(__name__)

router = APIRouter()

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"

# Prepended to the grounded prompt when a face reference image is used.
_FACE_REF_INSTRUCTION = (
    "Use the reference image ONLY for facial identity. "
    "Do NOT copy clothing; outfit must follow the image prompt. "
)

# B17 provider option → internal provider name (not exposed to end users).
# To collapse to single-provider: set IMAGE_GENERATOR_PROVIDER_TOGGLE=False in config.
_OPTION_PROVIDER_NAMES: dict[str, str] = {
    "option1": "openai",
    "option2": "google",
}


# ── Request schema ────────────────────────────────────────────────────


class ImageGenerateRequest(BaseModel):
    """Request body for POST /characters/{id}/image-generator/generate."""

    prompt: str = Field(..., min_length=1, max_length=800)
    include_character: bool = False
    provider_option: Literal["option1", "option2"] = "option1"


# ── Helpers ───────────────────────────────────────────────────────────


def _save_png_bytes(png_bytes: bytes) -> str:
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    (_GENERATED_DIR / filename).write_bytes(png_bytes)
    return f"static/generated/{filename}"


def _parse_anchor_json(raw: str | None) -> dict | None:
    """Parse identity_anchor_json; return None if missing, invalid, or has no front anchor."""
    if not raw:
        return None
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return None
    front = (data.get("anchors") or {}).get("front")
    if not front or not front.get("url"):
        return None
    return data


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post(
    "/{character_id}/image-generator/generate",
    response_model=CharacterImageRead,
    summary="Generate an image with optional character identity and provider selection (B17)",
)
def generate_image(
    character_id: int,
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterImageRead:
    """Generate a single image.

    When include_character=True, the character must be visually locked and an
    identity anchor must exist.  The locked identity lock string, body morphology,
    and face reference are automatically injected into the generation prompt.

    When include_character=False, generation uses the user prompt only with no
    character references.

    provider_option selects the backend provider:
      option1  →  OpenAI
      option2  →  Google
    When IMAGE_GENERATOR_PROVIDER_TOGGLE is disabled in config, option1 is
    always used regardless of the value sent by the client.
    """
    # ── Auth + ownership ──────────────────────────────────────────
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to use this character.",
        )

    # ── Provider resolution ────────────────────────────────────────
    # Respect the toggle: if disabled, always use option1 regardless of request.
    effective_option = body.provider_option if settings.IMAGE_GENERATOR_PROVIDER_TOGGLE else "option1"
    resolved_provider_name = _OPTION_PROVIDER_NAMES[effective_option]

    # ── Character inclusion ────────────────────────────────────────
    anchor_data: dict | None = None
    face_ref_bytes: bytes | None = None
    identity_hash: str | None = None
    prompt = body.prompt.strip()

    if body.include_character:
        # Guard: must be visually locked
        if not character.visual_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Your character's visual identity must be locked before "
                    "including them in an image. Complete the identity pack first."
                ),
            )

        anchor_data = _parse_anchor_json(character.identity_anchor_json)
        if anchor_data is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Character identity anchor not found. "
                    "Please regenerate and accept the identity pack."
                ),
            )

        # Inject identity lock string + body morphology into the prompt
        identity_lock = anchor_data.get("identity_lock_string") or ""
        identity_hash = anchor_data.get("identity_prompt_hash")

        if identity_lock:
            combined = f"{prompt}, {identity_lock}"
            if len(combined) > 800:
                budget = 800 - len(prompt) - 2
                combined = f"{prompt}, {identity_lock[:max(budget, 0)]}" if budget > 0 else prompt
            prompt = combined

        # Load face reference bytes (tight head crop for facial grounding)
        face_ref_img = (
            db.query(CharacterImage)
            .filter(
                CharacterImage.character_id == character_id,
                CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
                CharacterImage.status == ImageStatusEnum.ACTIVE,
            )
            .order_by(CharacterImage.created_at.desc())
            .first()
        )
        if face_ref_img is not None:
            try:
                _face_abs = _GENERATED_DIR / Path(face_ref_img.file_path).name
                face_ref_bytes = _face_abs.read_bytes()
            except Exception:
                logger.warning(
                    "image_generator face_ref_load_failed character_id=%s", character_id
                )

    # Hard-cap the prompt for the provider
    provider_prompt = prompt[:800]

    # ── Generate image ────────────────────────────────────────────
    try:
        provider = get_provider_for_option(effective_option)
    except (RuntimeError, ValueError):
        logger.warning(
            "image_generator provider_unavailable option=%s provider=%s character_id=%s",
            effective_option,
            resolved_provider_name,
            character_id,
        )
        provider = None

    png_bytes: bytes | None = None
    actual_provider_name = "stub"
    used_face_ref = False

    # Tier A: grounded generation using face reference bytes (when include_character)
    if provider is not None and body.include_character and face_ref_bytes is not None:
        _face_sig_text = ((anchor_data or {}).get("face_signature") or {}).get("text", "")
        grounded_prompt = (
            (f"FACE SIGNATURE (canonical): {_face_sig_text}. " if _face_sig_text else "")
            + _FACE_REF_INSTRUCTION
            + provider_prompt
        )
        try:
            png_bytes = provider.generate_grounded_image(
                prompt=grounded_prompt,
                reference_image_bytes=face_ref_bytes,
            )
            actual_provider_name = resolved_provider_name
            used_face_ref = True
        except (ValueError, RuntimeError, NotImplementedError):
            logger.info(
                "image_generator grounded_failed character_id=%s provider=%s",
                character_id,
                resolved_provider_name,
            )

    # Tier B: text-to-image (with identity lock injected into prompt if include_character)
    if png_bytes is None and provider is not None:
        try:
            png_bytes = provider.generate_image(prompt=provider_prompt)
            actual_provider_name = resolved_provider_name
        except (ValueError, RuntimeError):
            logger.info(
                "image_generator text_gen_failed character_id=%s provider=%s",
                character_id,
                resolved_provider_name,
            )

    # Tier C: fallback provider
    if png_bytes is None:
        fallback = get_fallback_provider()
        if fallback is not None:
            try:
                png_bytes = fallback.generate_image(prompt=provider_prompt)
                actual_provider_name = "fal"
            except (ValueError, RuntimeError):
                logger.info(
                    "image_generator fallback_failed character_id=%s", character_id
                )

    # Tier D: stub placeholder
    if png_bytes is not None:
        file_path = _save_png_bytes(png_bytes)
    else:
        file_path = generate_placeholder_png(
            label=character.name,
            sublabel=body.prompt[:80],
            role="generated",
        )
        actual_provider_name = "stub"

    # ── Persist image record with evaluation metadata ─────────────
    img = CharacterImage(
        character_id=character_id,
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=actual_provider_name,
        prompt_summary=body.prompt[:200],
        metadata_json={
            "image_generator": True,
            "provider_option": effective_option,
            "provider": actual_provider_name,
            "include_character": body.include_character,
            "character_id": character_id if body.include_character else None,
            "prompt": body.prompt,
            "used_face_ref": used_face_ref,
            "identity_hash": identity_hash,
        },
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    logger.info(
        "image_generator_result image_id=%s character_id=%s provider=%s "
        "provider_option=%s include_character=%s",
        img.id,
        character_id,
        actual_provider_name,
        effective_option,
        body.include_character,
    )

    return CharacterImageRead.model_validate(img)
