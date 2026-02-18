"""Scene image generation endpoints — anchored to a character's locked identity."""
import json as _json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum
from app.schemas.character_image import CharacterImageRead
from app.services.image_provider import get_image_provider, get_fallback_provider
from app.services.stub_image_generator import generate_placeholder_png

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_STYLES = {"realistic", "anime", "cartoon", "illustration", "comic", "pixel"}

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"

_PROVIDER_PROMPT_CAP = 250


# ── Request / helpers ────────────────────────────────────────────────

class SceneImageGenerateRequest(BaseModel):
    """Request body for POST /characters/{id}/scene-images/generate."""
    prompt: str = Field(..., min_length=1, max_length=800)
    style: str = "realistic"

    @field_validator("style")
    @classmethod
    def _coerce_style(cls, v: str) -> str:
        normed = v.strip().lower()
        return normed if normed in _VALID_STYLES else "realistic"


def _save_png_bytes(png_bytes: bytes) -> str:
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    (_GENERATED_DIR / filename).write_bytes(png_bytes)
    return f"static/generated/{filename}"


def _is_moderation_block(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in ("moderation_blocked", "safety system", "safety_violation"))


# ── Endpoint ─────────────────────────────────────────────────────────

@router.post(
    "/{character_id}/scene-images/generate",
    response_model=CharacterImageRead,
    summary="Generate a scene image anchored to the character's locked identity",
)
def generate_scene_image(
    character_id: int,
    body: SceneImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterImageRead:
    """Generate a single scene image for a locked character.

    Uses the character's front anchor as a reference image when possible,
    falling back to text-only generation and finally to a stub placeholder.
    """
    # ── Auth + ownership ──────────────────────────────────────────
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to modify this character.")

    # ── Preconditions ─────────────────────────────────────────────
    if not character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lock your character's identity before generating scene images.",
        )

    anchor_data = _parse_anchor_json(character.identity_anchor_json)
    if anchor_data is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="We couldn't find your character's identity anchor. Please regenerate and accept the identity pack.",
        )

    front_anchor = anchor_data.get("anchors", {}).get("front")
    front_url: str | None = front_anchor.get("url") if front_anchor else None

    # ── Build prompt ──────────────────────────────────────────────
    identity_lock = anchor_data.get("identity_lock_string") or ""
    identity_hash = anchor_data.get("identity_prompt_hash")
    style = body.style

    # Combine user prompt + lock string, keeping under 800 total
    if identity_lock:
        combined = f"{body.prompt}, {identity_lock}"
        if len(combined) > 800:
            # Trim lock string to fit
            budget = 800 - len(body.prompt) - 2  # 2 for ", "
            combined = f"{body.prompt}, {identity_lock[:max(budget, 0)]}" if budget > 0 else body.prompt
    else:
        combined = body.prompt

    # Provider prompt hard-capped at 250 for the image API
    provider_prompt = combined[:_PROVIDER_PROMPT_CAP]

    # ── Resolve front anchor URL for reference-image edits ────────
    front_ref_url: str | None = None
    if front_url:
        # Convert stored path to a full URL the provider can download
        if front_url.startswith("/static/"):
            base = settings.BACKEND_PUBLIC_URL.rstrip("/")
            front_ref_url = f"{base}{front_url}"
        elif front_url.startswith("http"):
            front_ref_url = front_url

    # ── Generate image (tiered fallback) ──────────────────────────
    provider_name = "stub"
    used_anchor = False

    try:
        provider = get_image_provider()
    except (RuntimeError, ValueError):
        provider = None

    png_bytes: bytes | None = None

    # Tier A: edit with reference image (preserves identity)
    if provider is not None and front_ref_url:
        try:
            png_bytes = provider.generate_image(
                prompt=provider_prompt,
                reference_image_url=front_ref_url,
            )
            provider_name = "openai"
            used_anchor = True
        except (ValueError, RuntimeError, NotImplementedError):
            logger.info("scene_image edit_failed character_id=%s, falling back to text-to-image", character_id)

    # Tier B: text-to-image via primary provider
    if png_bytes is None and provider is not None:
        try:
            png_bytes = provider.generate_image(prompt=provider_prompt)
            provider_name = "openai"
        except (ValueError, RuntimeError):
            logger.info("scene_image text_to_image_failed character_id=%s, trying fallback", character_id)

    # Tier C: fallback provider (fal.ai)
    if png_bytes is None:
        fallback = get_fallback_provider()
        if fallback is not None:
            try:
                png_bytes = fallback.generate_image(prompt=provider_prompt)
                provider_name = "fal"
            except (ValueError, RuntimeError):
                logger.info("scene_image fallback_failed character_id=%s, using stub", character_id)

    # Tier D: stub placeholder
    if png_bytes is not None:
        file_path = _save_png_bytes(png_bytes)
    else:
        file_path = generate_placeholder_png(
            label=f"{character.name} — scene",
            sublabel=body.prompt[:80],
            role="generated",
        )
        provider_name = "stub"

    # ── Save CharacterImage ───────────────────────────────────────
    img = CharacterImage(
        character_id=character_id,
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider_name,
        prompt_summary=body.prompt[:200],
        metadata_json={
            "library": True,
            "scene": True,
            "prompt": body.prompt,
            "style": style,
            "used_anchor": used_anchor,
            "identity_hash": identity_hash,
        },
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    return CharacterImageRead.model_validate(img)


def _parse_anchor_json(raw: str | None) -> dict | None:
    """Parse identity_anchor_json, returning None if missing/invalid or has no front anchor."""
    if not raw:
        return None
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return None
    # Must have anchors.front.url at minimum
    front = (data.get("anchors") or {}).get("front")
    if not front or not front.get("url"):
        return None
    return data
