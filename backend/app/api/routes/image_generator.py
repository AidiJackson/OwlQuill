"""Simplified image generator endpoint with provider toggle (B17).

Replaces the mental model of 'scene generator' with a plain image generator:
  - Always tied to a character for ownership/auth
  - include_character controls whether identity references are injected
  - provider_option selects the backend provider (option1=OpenAI, option2=Google)

B18: Strict identity mode is automatically enabled when include_character=True.
  - Blocks silent fallback to plain generic generation or stub placeholder
  - Allows at most one retry with escalated wording before controlled failure

B19: Anchor-image conditioning.
  - Loads identity pack images (front, three-quarter, torso, full-body) from disk
  - Passes them as real provider inputs via generate_with_anchors when supported
  - Falls back to single-image grounded generation (face-ref crop) when not
  - Tightens the strict identity text wrapper to be short and punchy
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
from app.core.storage import save_image, load_image_bytes
from app.models.user import User
from app.services.image_quota import check_weekly_quota
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
_OPTION_PROVIDER_NAMES: dict[str, str] = {
    "option1": "openai",
    "option2": "google",
}

# ── B18/B19 strict identity prompt constants ──────────────────────────
# Shorter, punchier wording — actual images carry the visual identity;
# the text wrapper confirms the requirement without bloat.

_STRICT_IDENTITY_PREFIX = (
    "The subject must be the same person as the reference images. "
    "Match their exact face shape, nose, jaw, and eye shape precisely. "
    "Preserve facial structure, hair, and body build. "
    "Do not use a generic or average face. Do not generate a different person."
)

_STRICT_IDENTITY_RETRY_PREFIX = (
    "CRITICAL: Reproduce the exact person from the reference images only. "
    "Same face shape, jaw, nose, eye shape, hair, and build. "
    "No generic or average faces. No substitution permitted."
)

# Preferred anchor load order: widest-identity coverage first
_ANCHOR_LOAD_ORDER = ("front", "three_quarter", "torso", "full_body")

# ── Cover-generation prompt directives ────────────────────────────────
#
# _COVER_BANNER_PREFIX   — always prepended when is_cover=True (~225 chars).
# _COVER_CHARACTER_FRAMING — appended additionally when is_cover=True AND
#                            include_character=True (~140 chars).
#
# Combined budget: up to ~365 chars of cover instructions, leaving ~435 chars
# for the user's scene description inside the 800-char provider_prompt cap.
# When include_character=True, _build_strict_identity_prompt wraps the result
# and hard-caps the final combined output at 800 chars; cover instructions
# travel at the tail of that prompt where image models weight them well.

_COVER_BANNER_PREFIX = (
    "PROFILE HEADER BANNER — ultra-wide 2.84:1 panoramic ratio. Not a portrait, not centered. "
    "COMPOSITION: subject in LEFT THIRD only. "
    "RIGHT two-thirds: open background, sky, or environment — no subject there. "
    "Full face and head completely visible. No head or face cropping. "
    "Intentional website profile banner layout. "
)

# Applied additionally when the character is included in the cover image.
# Enforces medium-shot framing so the face is reliably visible at banner scale.
_COVER_CHARACTER_FRAMING = (
    "CHARACTER: chest-up or waist-up framing. Full face clearly visible. No full-body shot. "
)

# Used for the single deterministic retry issued when a character-inclusive
# cover is generated. The retry escalates framing language and re-anchors
# the composition rule to give the model a second chance at banner layout.
# Kept to ~230 chars so it fits comfortably inside _build_strict_identity_prompt.
_COVER_RETRY_PROMPT = (
    "COVER RETRY — PROFILE HEADER BANNER, ultra-wide 2.84:1. "
    "Subject in LEFT THIRD, chest-up or waist-up ONLY, full face visible. "
    "Right two-thirds: open background — no subject. "
    "No full-body shot. No face crop. Intentional banner layout. "
)


# ── Request schema ────────────────────────────────────────────────────


class ImageGenerateRequest(BaseModel):
    """Request body for POST /characters/{id}/image-generator/generate."""

    prompt: str = Field(..., min_length=1, max_length=800)
    include_character: bool = False
    provider_option: Literal["option1", "option2"] = "option1"
    is_cover: bool = False  # When True, saves with kind=COVER for use as a character cover banner


# ── Helpers ───────────────────────────────────────────────────────────


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


def _build_anchor_data_from_db(character_id: int, db: Session) -> dict | None:
    """Legacy compatibility: rebuild anchor_data from active anchor image rows.

    Characters locked before the identity_anchor_json field was introduced
    (pre-Feb 2026) may have valid anchor images in the DB but a null
    identity_anchor_json on the character record.  This helper reconstructs
    the minimal dict expected by _load_anchor_images so generation can proceed
    without requiring the user to re-lock their character.

    Returns None when no ANCHOR_FRONT image is found — that means the character
    genuinely has no usable anchors and must regenerate the identity pack.
    """
    kind_to_key = {
        ImageKindEnum.ANCHOR_FRONT: "front",
        ImageKindEnum.ANCHOR_THREE_QUARTER: "three_quarter",
        ImageKindEnum.ANCHOR_TORSO: "torso",
        ImageKindEnum.ANCHOR_FULL_BODY: "full_body",
    }

    rows = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind.in_(list(kind_to_key.keys())),
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )

    if not rows:
        return None

    anchors_dict: dict[str, dict] = {}
    for img in rows:
        key = kind_to_key.get(img.kind)
        if key is None:
            continue
        path = img.file_path.lstrip("/")
        url = f"/{path}" if path.startswith("static/") else f"/static/{path}"
        anchors_dict[key] = {"id": img.id, "url": url}

    # Must have at least the front anchor to be usable for identity conditioning.
    if "front" not in anchors_dict:
        return None

    return {"version": 1, "anchors": anchors_dict}


def _load_anchor_images(
    anchor_data: dict,
    character_id: int,
) -> tuple[list[bytes], list[str]]:
    """Load identity anchor images in preferred order (B19).

    Works for both R2 (https://...) and local (/static/generated/...) URLs
    via load_image_bytes.  Preferred order: front → three_quarter → torso → full_body.

    Returns:
        (loaded_bytes, loaded_type_keys) — parallel lists.
        Entries for missing or unreadable files are silently skipped.
    """
    anchors = anchor_data.get("anchors") or {}
    loaded_bytes: list[bytes] = []
    loaded_keys: list[str] = []

    logger.info(
        "DIAG anchor_load_start character_id=%s anchors_in_json=%s",
        character_id,
        list(anchors.keys()),
    )

    for key in _ANCHOR_LOAD_ORDER:
        entry = anchors.get(key)
        if not entry:
            logger.info("DIAG anchor_skip character_id=%s key=%s reason=not_in_json", character_id, key)
            continue
        url = entry.get("url", "")
        if not url:
            logger.info("DIAG anchor_skip character_id=%s key=%s reason=empty_url", character_id, key)
            continue
        logger.info("DIAG anchor_attempt character_id=%s key=%s url=%s", character_id, key, url)
        try:
            img_bytes = load_image_bytes(url)
            loaded_bytes.append(img_bytes)
            loaded_keys.append(key)
            logger.info(
                "DIAG anchor_loaded character_id=%s key=%s bytes=%d",
                character_id, key, len(img_bytes),
            )
        except Exception as _exc:
            logger.warning(
                "DIAG anchor_load_failed character_id=%s key=%s url=%s error=%r",
                character_id, key, url, str(_exc),
            )

    logger.info(
        "DIAG anchor_load_done character_id=%s loaded=%d/%d keys=%s",
        character_id, len(loaded_bytes), len(anchors), loaded_keys,
    )
    return loaded_bytes, loaded_keys


def _prioritise_face_anchors(
    loaded_bytes: list[bytes],
    loaded_keys: list[str],
) -> tuple[list[bytes], list[str]]:
    """Boost face anchor signal by duplicating the front anchor (B21).

    Prepends a second copy of the front-facing anchor image so the provider
    sees it with higher effective weight. Face-forward shots carry the most
    facial geometry information (nose, jaw, cheekbones, eye shape) and are
    the primary defence against generic-face drift.

    Only the front anchor is duplicated; torso and full-body shots are not
    repeated since they add body/pose information, not face specificity.

    When no front anchor is available, returns the inputs unchanged —
    the existing fallback chain (grounded → text-only) remains intact.
    """
    if not loaded_bytes or "front" not in loaded_keys:
        return loaded_bytes, loaded_keys

    front_idx = loaded_keys.index("front")
    prioritised_bytes = [loaded_bytes[front_idx]] + list(loaded_bytes)
    prioritised_keys = ["front"] + list(loaded_keys)
    return prioritised_bytes, prioritised_keys


def _build_strict_identity_prompt(
    *,
    base_prompt: str,
    anchor_data: dict,
    character_name: str = "",
    retry: bool = False,
) -> str:
    """Build a tightened strict-identity prompt (B19).

    Short, punchy directive + character name + identity lock string + scene prompt.
    Face-signature text and anchor-ref listing are omitted here — actual image
    inputs carry that information when the provider supports multi-image input.

    Hard-capped at 800 characters.
    """
    prefix = _STRICT_IDENTITY_RETRY_PREFIX if retry else _STRICT_IDENTITY_PREFIX
    parts: list[str] = [prefix.rstrip()]

    if character_name:
        parts.append(f"Character: {character_name}")

    # Identity lock string already includes hair/eyes/skin and body morphology (B16)
    lock = anchor_data.get("identity_lock_string") or ""
    if lock:
        parts.append(lock)

    # User's scene prompt last
    parts.append(base_prompt)

    combined = ". ".join(p.rstrip(". ") for p in parts)
    return combined[:800]


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post(
    "/{character_id}/image-generator/generate",
    response_model=CharacterImageRead,
    summary="Generate an image with optional character identity and provider selection (B17-B19)",
)
def generate_image(
    character_id: int,
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a single image.

    When include_character=True, strict identity mode (B18) with anchor-image
    conditioning (B19) is automatically enabled:
      - All available identity pack images are loaded from disk
      - Passed as real provider inputs via generate_with_anchors (multi-image)
      - Falls back to single-image grounded generation when multi-image unsupported
      - Short, punchy identity directive is prepended to the prompt
      - Provider is required; stub fallback is blocked
      - At most one retry with escalated wording; then controlled 503 failure

    When include_character=False, normal generation applies (text → fallback → stub).

    provider_option:
      option1 → OpenAI  |  option2 → Google
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

    # ── B22: Weekly allowance check ────────────────────────────────
    # Checked before generation starts; deducted only on successful save.
    # Admin users bypass this check entirely.
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    # ── Provider resolution ────────────────────────────────────────
    effective_option = body.provider_option if settings.IMAGE_GENERATOR_PROVIDER_TOGGLE else "option1"
    resolved_provider_name = _OPTION_PROVIDER_NAMES[effective_option]

    # ── Character inclusion ────────────────────────────────────────
    anchor_data: dict | None = None
    face_ref_bytes: bytes | None = None
    identity_hash: str | None = None
    base_prompt = body.prompt.strip()

    # Cover mode: prepend banner-composition directives before the user's prompt.
    # Character framing is added additionally when include_character=True so the
    # medium-shot instruction travels with the scene description inside the
    # strict-identity wrapper.
    if body.is_cover:
        cover_block = _COVER_BANNER_PREFIX
        if body.include_character:
            cover_block += _COVER_CHARACTER_FRAMING
        base_prompt = cover_block + base_prompt

    if body.include_character:
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
            # Legacy compatibility: character was locked before identity_anchor_json was
            # introduced (pre-Feb 2026).  Attempt to rebuild from active anchor rows.
            anchor_data = _build_anchor_data_from_db(character_id, db)
            if anchor_data is not None:
                # Persist the rebuilt snapshot so future requests use it directly.
                logger.info(
                    "anchor_json_repaired_from_db character_id=%s anchor_count=%d",
                    character_id,
                    len(anchor_data.get("anchors", {})),
                )
                character.identity_anchor_json = _json.dumps(anchor_data)
                db.commit()
                db.refresh(character)
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Character identity anchor not found. "
                        "Please regenerate and accept the identity pack."
                    ),
                )

        identity_hash = anchor_data.get("identity_prompt_hash")

        # Load face reference bytes (tight head crop — fallback for single-image path)
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
        if face_ref_img is None:
            logger.info(
                "DIAG face_ref_missing character_id=%s name=%r — no IDENTITY_FACE_REF in DB",
                character_id, character.name,
            )
        else:
            logger.info(
                "DIAG face_ref_found character_id=%s name=%r file_path=%s",
                character_id, character.name, face_ref_img.file_path,
            )
            try:
                face_ref_bytes = load_image_bytes(face_ref_img.file_path)
                logger.info(
                    "DIAG face_ref_loaded character_id=%s bytes=%d",
                    character_id, len(face_ref_bytes),
                )
            except Exception as _fre:
                logger.warning(
                    "DIAG face_ref_load_failed character_id=%s file_path=%s error=%r",
                    character_id, face_ref_img.file_path, str(_fre),
                )

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
    multi_image_used = False

    # ── B18/B19 STRICT IDENTITY MODE (include_character=True) ─────
    if body.include_character:
        logger.info(
            "DIAG identity_mode_enter character_id=%s name=%r provider=%s "
            "face_ref_available=%s anchor_json_present=%s",
            character_id, character.name, resolved_provider_name,
            face_ref_bytes is not None,
            character.identity_anchor_json is not None,
        )

        # B19: load actual anchor images from disk
        anchor_images, anchor_types = _load_anchor_images(
            anchor_data,  # type: ignore[arg-type]
            character_id,
        )

        # B21: boost face anchor signal — duplicate front anchor for stronger conditioning.
        # Tracked separately so metadata accurately reflects the boost.
        _face_anchor_boosted = "front" in anchor_types
        anchor_images, anchor_types = _prioritise_face_anchors(anchor_images, anchor_types)

        provider_supports_multi = getattr(provider, "supports_multi_image_input", False)
        logger.info(
            "DIAG strict_identity_state character_id=%s provider=%s "
            "anchors_loaded=%d anchor_types=%s multi_image_supported=%s "
            "face_ref_bytes=%s",
            character_id,
            resolved_provider_name,
            len(anchor_images),
            anchor_types,
            provider_supports_multi,
            f"{len(face_ref_bytes)}b" if face_ref_bytes else "None",
        )
        logger.info(
            "strict_identity_enabled character_id=%s provider=%s "
            "anchors_loaded=%d anchor_types=%s multi_image_supported=%s",
            character_id,
            resolved_provider_name,
            len(anchor_images),
            anchor_types,
            provider_supports_multi,
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
            character_name=character.name,
            retry=False,
        )

        # Tier 1: multi-image anchor conditioning (B19)
        if provider_supports_multi and anchor_images:
            logger.info("DIAG tier1_attempt character_id=%s anchor_count=%d", character_id, len(anchor_images))
            try:
                png_bytes = provider.generate_with_anchors(
                    prompt=strict_prompt,
                    anchor_images=anchor_images,
                )
                actual_provider_name = resolved_provider_name
                multi_image_used = True
                logger.info("DIAG tier1_success character_id=%s", character_id)
            except (ValueError, RuntimeError, NotImplementedError) as _t1e:
                logger.warning(
                    "DIAG tier1_failed character_id=%s provider=%s error=%r",
                    character_id, resolved_provider_name, str(_t1e),
                )
                logger.info(
                    "anchor_multi_image_failed attempt=1 character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )
        else:
            logger.info(
                "DIAG tier1_skip character_id=%s reason=%s anchors=%d",
                character_id,
                "multi_image_not_supported" if not provider_supports_multi else "no_anchors",
                len(anchor_images),
            )
            logger.info(
                "anchor_conditioning_fallback character_id=%s "
                "reason=multi_image_not_supported anchors_available=%d using=face_ref",
                character_id,
                len(anchor_images),
            )

        # Tier 2: single-image grounded (face-ref crop)
        if png_bytes is None and face_ref_bytes is not None:
            logger.info("DIAG tier2_attempt character_id=%s face_ref_bytes=%d", character_id, len(face_ref_bytes))
            try:
                png_bytes = provider.generate_grounded_image(
                    prompt=strict_prompt,
                    reference_image_bytes=face_ref_bytes,
                )
                actual_provider_name = resolved_provider_name
                used_face_ref = True
                logger.info("DIAG tier2_success character_id=%s", character_id)
            except (ValueError, RuntimeError, NotImplementedError) as _t2e:
                logger.warning(
                    "DIAG tier2_failed character_id=%s provider=%s error=%r",
                    character_id, resolved_provider_name, str(_t2e),
                )
                logger.info(
                    "strict_identity_grounded_failed attempt=1 character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )
        elif png_bytes is None:
            logger.info(
                "DIAG tier2_skip character_id=%s reason=face_ref_not_available",
                character_id,
            )

        # Tier 3: text-only strict (no image reference available)
        if png_bytes is None:
            logger.info("DIAG tier3_attempt character_id=%s text_only_fallback=TRUE", character_id)
            try:
                png_bytes = provider.generate_image(prompt=strict_prompt)
                actual_provider_name = resolved_provider_name
                logger.info("DIAG tier3_success character_id=%s WARNING=text_only_no_identity_grounding", character_id)
            except (ValueError, RuntimeError) as _t3e:
                logger.warning(
                    "DIAG tier3_failed character_id=%s provider=%s error=%r",
                    character_id, resolved_provider_name, str(_t3e),
                )
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
                character_name=character.name,
                retry=True,
            )

            if provider_supports_multi and anchor_images:
                logger.info("DIAG retry_tier1_attempt character_id=%s", character_id)
                try:
                    png_bytes = provider.generate_with_anchors(
                        prompt=retry_prompt,
                        anchor_images=anchor_images,
                    )
                    actual_provider_name = resolved_provider_name
                    multi_image_used = True
                    logger.info("DIAG retry_tier1_success character_id=%s", character_id)
                except (ValueError, RuntimeError, NotImplementedError) as _r1e:
                    logger.warning(
                        "DIAG retry_tier1_failed character_id=%s error=%r", character_id, str(_r1e),
                    )
                    logger.info(
                        "anchor_multi_image_failed attempt=2 character_id=%s provider=%s",
                        character_id,
                        resolved_provider_name,
                    )

            if png_bytes is None and face_ref_bytes is not None:
                logger.info("DIAG retry_tier2_attempt character_id=%s", character_id)
                try:
                    png_bytes = provider.generate_grounded_image(
                        prompt=retry_prompt,
                        reference_image_bytes=face_ref_bytes,
                    )
                    actual_provider_name = resolved_provider_name
                    used_face_ref = True
                    logger.info("DIAG retry_tier2_success character_id=%s", character_id)
                except (ValueError, RuntimeError, NotImplementedError) as _r2e:
                    logger.warning(
                        "DIAG retry_tier2_failed character_id=%s error=%r", character_id, str(_r2e),
                    )
                    logger.info(
                        "strict_identity_grounded_failed attempt=2 character_id=%s provider=%s",
                        character_id,
                        resolved_provider_name,
                    )

            if png_bytes is None:
                logger.info("DIAG retry_tier3_attempt character_id=%s text_only_fallback=TRUE", character_id)
                try:
                    png_bytes = provider.generate_image(prompt=retry_prompt)
                    actual_provider_name = resolved_provider_name
                    logger.info("DIAG retry_tier3_success character_id=%s WARNING=text_only_no_grounding", character_id)
                except (ValueError, RuntimeError) as _r3e:
                    logger.warning(
                        "DIAG retry_tier3_failed character_id=%s error=%r", character_id, str(_r3e),
                    )
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
            "retry_attempted=%s used_face_ref=%s multi_image_used=%s anchors_attached=%d",
            character_id,
            retry_attempted,
            used_face_ref,
            multi_image_used,
            len(anchor_images),
        )
        file_path = save_image(png_bytes)

    # ── NORMAL MODE (include_character=False) ─────────────────────
    else:
        anchor_images = []
        anchor_types = []

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

        if png_bytes is not None:
            file_path = save_image(png_bytes)
        else:
            file_path = generate_placeholder_png(
                label=character.name,
                sublabel=body.prompt[:80],
                role="generated",
            )
            actual_provider_name = "stub"

    # ── Cover composition retry (character-inclusive covers only) ─────────
    # No image-content heuristic can detect poor banner composition without
    # vision infrastructure. We apply one deterministic retry with an
    # escalated prompt whenever a character is included in a cover image.
    # The retry result supersedes the first-pass result; if it fails the
    # first-pass image is kept and committed as normal.
    cover_retry_attempted = False
    cover_retry_succeeded = False
    if body.is_cover and body.include_character and png_bytes is not None:
        cover_retry_attempted = True
        retry_base = _COVER_RETRY_PROMPT + body.prompt.strip()
        cover_retry_str_prompt = _build_strict_identity_prompt(
            base_prompt=retry_base[:800],
            anchor_data=anchor_data,  # type: ignore[arg-type]
            character_name=character.name,
            retry=False,
        )
        cover_retry_png: bytes | None = None
        if provider_supports_multi and anchor_images:
            try:
                cover_retry_png = provider.generate_with_anchors(
                    prompt=cover_retry_str_prompt,
                    anchor_images=anchor_images,
                )
            except (ValueError, RuntimeError, NotImplementedError):
                pass
        if cover_retry_png is None and face_ref_bytes is not None:
            try:
                cover_retry_png = provider.generate_grounded_image(
                    prompt=cover_retry_str_prompt,
                    reference_image_bytes=face_ref_bytes,
                )
            except (ValueError, RuntimeError, NotImplementedError):
                pass
        if cover_retry_png is None:
            try:
                cover_retry_png = provider.generate_image(prompt=cover_retry_str_prompt)
            except (ValueError, RuntimeError):
                pass
        if cover_retry_png is not None:
            file_path = save_image(cover_retry_png)
            png_bytes = cover_retry_png
            cover_retry_succeeded = True
            logger.info("cover_retry_succeeded character_id=%s", character_id)
        else:
            logger.info(
                "cover_retry_failed_using_first_pass character_id=%s", character_id
            )

    # ── Persist image record ──────────────────────────────────────
    metadata: dict = {
        "image_generator": True,
        "provider_option": effective_option,
        "provider": actual_provider_name,
        "include_character": body.include_character,
        "character_id": character_id if body.include_character else None,
        "prompt": body.prompt,
        "strict_identity_mode": body.include_character,
        "is_cover": body.is_cover,
    }
    if body.include_character:
        metadata["used_face_ref"] = used_face_ref
        metadata["identity_hash"] = identity_hash
        metadata["strict_identity_retry"] = retry_attempted
        metadata["anchors_attached"] = len(anchor_images)
        metadata["anchor_types"] = anchor_types
        metadata["multi_image_used"] = multi_image_used
        metadata["face_anchor_boosted"] = _face_anchor_boosted  # B21
        metadata["cover_retry_attempted"] = cover_retry_attempted
        metadata["cover_retry_succeeded"] = cover_retry_succeeded

    img = CharacterImage(
        character_id=character_id,
        user_id=current_user.id,  # B22: stamp for quota tracking
        kind=ImageKindEnum.COVER if body.is_cover else ImageKindEnum.GENERATED,
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
        "provider_option=%s include_character=%s anchors_attached=%s",
        img.id,
        character_id,
        actual_provider_name,
        effective_option,
        body.include_character,
        len(anchor_images),
    )

    return CharacterImageRead.model_validate(img)
