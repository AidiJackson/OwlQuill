"""Simplified image generator endpoint with provider toggle (B17).

Replaces the mental model of 'scene generator' with a plain image generator:
  - Always tied to a character for ownership/auth
  - include_character controls whether identity references are injected
  - provider_option selects the backend provider (option1=OpenAI, option2=Google)

B18: Strict identity mode is automatically enabled when include_character=True.
  - Prepends a strong identity-preservation wrapper to the provider prompt
  - Injects identity lock string, face signature, and available anchor refs
  - Instructs the provider not to substitute a generic archetype or different person
  - Blocks silent fallback to plain generic generation or stub placeholder
  - Allows at most one retry with stronger identity wording before controlled failure
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

# B17 provider option → internal provider name (not exposed to end users).
# To collapse to single-provider: set IMAGE_GENERATOR_PROVIDER_TOGGLE=False in config.
_OPTION_PROVIDER_NAMES: dict[str, str] = {
    "option1": "openai",
    "option2": "google",
}

# ── B18 strict identity constants ─────────────────────────────────────

_STRICT_IDENTITY_PREFIX = (
    "STRICT IDENTITY LOCK — this image depicts a specific named character, "
    "NOT a generic person or archetype. "
    "You MUST reproduce the exact same individual shown in the reference: "
    "exact face, exact hair colour and style, exact skin tone, exact eye colour. "
    "Do NOT substitute a different person. Do NOT use a generic or averaged appearance. "
    "Use the reference image for facial identity ONLY; outfit must follow the scene prompt. "
)

_STRICT_IDENTITY_RETRY_PREFIX = (
    "ABSOLUTE IDENTITY REQUIREMENT — CRITICAL: Reproduce the EXACT person from the reference. "
    "Same specific individual ONLY. Zero substitution permitted. "
    "Same facial geometry, same hair, same colouring, same distinguishing marks. "
    "Use the reference image for facial identity ONLY; outfit must follow the scene prompt. "
)


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


def _build_strict_identity_prompt(
    *,
    base_prompt: str,
    anchor_data: dict,
    retry: bool = False,
) -> str:
    """Build a strict-identity-mode prompt for character-grounded generation.

    Wraps base_prompt with a strong identity-preservation header that includes:
    - Identity lock directive (retry escalates the language)
    - Face signature text (canonical textual description of the face)
    - Identity lock string (hair, eyes, skin, body morphology)
    - Available anchor reference angles

    Hard-capped at 800 characters.
    """
    prefix = _STRICT_IDENTITY_RETRY_PREFIX if retry else _STRICT_IDENTITY_PREFIX
    parts: list[str] = [prefix.rstrip()]

    # Canonical face signature for textual grounding
    face_sig = (anchor_data.get("face_signature") or {}).get("text", "")
    if face_sig:
        parts.append(f"FACE SIGNATURE: {face_sig}")

    # Identity lock string already includes hair/eyes/skin and body morphology (B16)
    lock = anchor_data.get("identity_lock_string") or ""
    if lock:
        parts.append(f"IDENTITY: {lock}")

    # List available anchor reference angles for the provider's context
    anchor_keys = [
        k for k in ("front", "three_quarter", "torso", "full_body")
        if (anchor_data.get("anchors") or {}).get(k)
    ]
    if anchor_keys:
        parts.append(f"Anchor refs: {', '.join(anchor_keys)}")

    # Original scene prompt last
    parts.append(base_prompt)

    combined = ". ".join(p.rstrip(". ") for p in parts)
    return combined[:800]


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post(
    "/{character_id}/image-generator/generate",
    response_model=CharacterImageRead,
    summary="Generate an image with optional character identity and provider selection (B17/B18)",
)
def generate_image(
    character_id: int,
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterImageRead:
    """Generate a single image.

    When include_character=True, strict identity mode (B18) is automatically
    enabled.  The character must be visually locked with an identity anchor.
    A strong identity-preservation wrapper is prepended to the prompt; the
    provider is instructed not to substitute a generic archetype.  At most one
    retry with escalated wording is attempted before a controlled failure is
    returned — the route never silently falls back to plain or stub generation.

    When include_character=False, generation uses the user prompt only with no
    character references; the normal stub fallback chain applies.

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
    base_prompt = body.prompt.strip()

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

        identity_hash = anchor_data.get("identity_prompt_hash")

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

    # Scene prompt hard-capped at 800 for provider (identity wrapper is built separately)
    provider_prompt = base_prompt[:800]

    # ── Resolve provider ──────────────────────────────────────────
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
    retry_attempted = False

    # ── B18 STRICT IDENTITY MODE (include_character=True) ─────────
    if body.include_character:
        anchor_refs = [
            k for k in ("front", "three_quarter", "torso", "full_body")
            if (anchor_data.get("anchors") or {}).get(k)  # type: ignore[union-attr]
        ]
        logger.info(
            "strict_identity_enabled character_id=%s provider=%s anchor_refs=%s",
            character_id,
            resolved_provider_name,
            anchor_refs,
        )

        # Provider is required — stub fallback is never acceptable for character images
        if provider is None:
            logger.info(
                "strict_identity_outcome character_id=%s outcome=controlled_failure "
                "reason=provider_unavailable retry_attempted=False",
                character_id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Character image generation could not be completed: "
                    "image provider is unavailable. Please try again later."
                ),
            )

        # ── Attempt 1 ──────────────────────────────────────────
        strict_prompt = _build_strict_identity_prompt(
            base_prompt=provider_prompt,
            anchor_data=anchor_data,  # type: ignore[arg-type]
            retry=False,
        )

        if face_ref_bytes is not None:
            try:
                png_bytes = provider.generate_grounded_image(
                    prompt=strict_prompt,
                    reference_image_bytes=face_ref_bytes,
                )
                actual_provider_name = resolved_provider_name
                used_face_ref = True
            except (ValueError, RuntimeError, NotImplementedError):
                logger.info(
                    "strict_identity_grounded_failed attempt=1 character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )

        if png_bytes is None:
            try:
                png_bytes = provider.generate_image(prompt=strict_prompt)
                actual_provider_name = resolved_provider_name
            except (ValueError, RuntimeError):
                logger.info(
                    "strict_identity_text_failed attempt=1 character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )

        # ── Attempt 2 (retry with escalated wording) ───────────
        if png_bytes is None:
            retry_attempted = True
            logger.info("strict_identity_retry character_id=%s", character_id)

            retry_prompt = _build_strict_identity_prompt(
                base_prompt=provider_prompt,
                anchor_data=anchor_data,  # type: ignore[arg-type]
                retry=True,
            )

            if face_ref_bytes is not None:
                try:
                    png_bytes = provider.generate_grounded_image(
                        prompt=retry_prompt,
                        reference_image_bytes=face_ref_bytes,
                    )
                    actual_provider_name = resolved_provider_name
                    used_face_ref = True
                except (ValueError, RuntimeError, NotImplementedError):
                    logger.info(
                        "strict_identity_grounded_failed attempt=2 character_id=%s provider=%s",
                        character_id,
                        resolved_provider_name,
                    )

            if png_bytes is None:
                try:
                    png_bytes = provider.generate_image(prompt=retry_prompt)
                    actual_provider_name = resolved_provider_name
                except (ValueError, RuntimeError):
                    logger.info(
                        "strict_identity_text_failed attempt=2 character_id=%s provider=%s",
                        character_id,
                        resolved_provider_name,
                    )

        # ── Controlled failure — do not save non-conditioned output ──
        if png_bytes is None:
            logger.info(
                "strict_identity_outcome character_id=%s outcome=controlled_failure "
                "retry_attempted=%s",
                character_id,
                retry_attempted,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Character image generation could not be completed with reliable "
                    "identity conditioning. Please try again. If the issue persists, "
                    "regenerate the character's identity pack."
                ),
            )

        logger.info(
            "strict_identity_outcome character_id=%s outcome=success "
            "retry_attempted=%s used_face_ref=%s",
            character_id,
            retry_attempted,
            used_face_ref,
        )
        file_path = _save_png_bytes(png_bytes)

    # ── NORMAL MODE (include_character=False) ─────────────────────
    else:
        # Tier B: text-to-image (no identity context in normal mode)
        if provider is not None:
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
    metadata: dict = {
        "image_generator": True,
        "provider_option": effective_option,
        "provider": actual_provider_name,
        "include_character": body.include_character,
        "character_id": character_id if body.include_character else None,
        "prompt": body.prompt,
        "strict_identity_mode": body.include_character,
    }
    if body.include_character:
        metadata["used_face_ref"] = used_face_ref
        metadata["identity_hash"] = identity_hash
        metadata["strict_identity_retry"] = retry_attempted

    img = CharacterImage(
        character_id=character_id,
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=actual_provider_name,
        prompt_summary=body.prompt[:200],
        metadata_json=metadata,
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    logger.info(
        "image_generator_result image_id=%s character_id=%s provider=%s "
        "provider_option=%s include_character=%s strict_identity_mode=%s",
        img.id,
        character_id,
        actual_provider_name,
        effective_option,
        body.include_character,
        body.include_character,
    )

    return CharacterImageRead.model_validate(img)
