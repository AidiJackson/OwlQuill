"""Character visual endpoints — DNA, identity pack, and moment generation."""
import io
import json as _json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_optional
from app.core.storage import save_image, file_path_to_url, load_image_bytes
from app.models.user import User
from app.models.character import Character as CharacterModel, VisibilityEnum
from app.models.character_dna import CharacterDNA
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum
from app.schemas.character_dna import CharacterDNACreate, CharacterDNAUpdate, CharacterDNARead
from app.schemas.character_image import CharacterImageCreate, CharacterImageRead
from app.schemas.character_visual import (
    IdentityPackGenerateRequest,
    IdentityPackGenerateResponse,
    IdentityPackAcceptRequest,
    IdentityPackAcceptResponse,
    MomentGenerateRequest,
    IdentitySketchGenerateRequest,
    IdentitySketchGenerateResponse,
)
from app.services.character_visual import upsert_character_dna, get_character_dna
from app.services.identity_evolution import write_pack_stages
from app.services.appearance_spec import (
    build_appearance_spec,
    build_generation_prompt,
    PromptBlockedError,
)
from app.services.identity_compiler import (
    compile_identity_prompt,
    compile_identity_lock_string,
    identity_prompt_hash,
    _SAFETY_PREFIX,
)
from app.services.stub_image_generator import generate_placeholder_png
from app.services.image_provider import (
    get_identity_provider_by_name,
    get_fallback_provider,
    ImageProvider,
    _OpenAIImageProvider,
)
from app.services.identity_front_validator import validate_front_anchor_png

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Single-frame enforcement ──────────────────────────────────────────
# Appended to EVERY identity-pack shot prompt to prevent Gemini from
# returning turntable strips, contact sheets, or multi-panel composites.
SINGLE_FRAME_ENFORCEMENT = (
    "Return exactly ONE image. Single-frame photo only. "
    "NO collage, NO diptych, NO split-screen, NO storyboard, NO contact sheet, "
    "NO multiple panels, NO repeated subject, NO turntable strip. One person only."
)

# Appended on the ONE retry when a strip is detected in the response.
_STRIP_RETRY_SUFFIX = (
    " CRITICAL: Do not return a strip or multiple poses. One frame only."
)

# B8: PG-13 safety clamp — appended to EVERY identity-pack prompt so OpenAI's
# content moderation never triggers a 500 on wardrobe/character descriptions.
_PG13_SAFETY_SUFFIX = (
    "Fully clothed. Non-sexual. Non-suggestive. No lingerie. No nudity. PG-13."
)

# B7.1: Hard preamble for the front anchor (seed) image.
# Placed first in the prompt so the model sees strict framing rules before
# any identity descriptors.  Must begin with "Passport-style headshot."
_FRONT_ANCHOR_PREAMBLE = (
    "Passport-style headshot. Head-and-shoulders only. Straight-on camera. "
    "Cropped mid-chest. Plain neutral background. "
    "NO full-body. NO sitting/crouching. NO hands visible. NO props. "
    "NO action pose. NO dramatic lighting."
)


def _build_identity_prompt(
    spec,  # CharacterIdentitySpec
    role: str,
    *,
    char_traits: "list[str] | None" = None,
    failsafe: bool = False,
) -> str:
    """Build a full identity prompt for any pack role via the single shared compiler.

    Routes ALL structured-spec prompt building through compile_identity_prompt
    so gender/style/age_band + NEUTRAL_STUDIO_OUTFIT are always present and
    wardrobe fields are never read.  Appends SINGLE_FRAME_ENFORCEMENT and
    _PG13_SAFETY_SUFFIX after the compiled base.
    """
    base = compile_identity_prompt(spec, role, char_traits=char_traits, failsafe=failsafe)
    return f"{base}. {SINGLE_FRAME_ENFORCEMENT}. {_PG13_SAFETY_SUFFIX}"


def _build_front_anchor_prompt(
    *,
    use_structured_spec: bool,
    identity_spec,  # CharacterIdentitySpec | None
    char_traits: "list[str] | None" = None,
    failsafe: bool = False,
) -> str:
    """Build the anchor_front seed prompt.

    For structured spec: delegates entirely to _build_identity_prompt (which
    calls compile_identity_prompt) so gender/style/age_band + NEUTRAL_STUDIO_OUTFIT
    are guaranteed.  compile_identity_prompt includes the passport-headshot role
    shot description for anchor_front.

    For legacy (no spec): builds a minimal prompt from char_traits + preamble.
    """
    if use_structured_spec and identity_spec is not None:
        return _build_identity_prompt(
            identity_spec, "anchor_front",
            char_traits=char_traits,
            failsafe=failsafe,
        )

    # Legacy path: use char_traits as minimal descriptors.
    parts: list[str] = [_FRONT_ANCHOR_PREAMBLE]
    if char_traits:
        parts.append(", ".join(char_traits))
    parts.append(SINGLE_FRAME_ENFORCEMENT)
    parts.append(_PG13_SAFETY_SUFFIX)
    return f"{_SAFETY_PREFIX}. " + ". ".join(parts)


def _is_strip_image(image_bytes: bytes) -> bool:
    """Return True when the image aspect ratio exceeds 1.2 : 1 (wider than tall).

    Such images are likely turntable strips or composite panels.
    Returns False on any decode failure so callers never crash on this check.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as img:
            w, h = img.size
            return h > 0 and (w / h) > 1.2
    except Exception:
        return False


def _enforce_single_frame(
    image_bytes: bytes,
    *,
    retry_fn,
    role: str,
    pack_id: str,
) -> bytes:
    """Retry once if image_bytes appears to be a strip/composite.

    Args:
        image_bytes: The image returned by the provider.
        retry_fn: Zero-argument callable that returns fresh image bytes.
        role: Pack role name, used only for logging.
        pack_id: Request ID, used only for logging.

    Returns:
        image_bytes unchanged if it passes the aspect-ratio check, or the
        result of retry_fn() if the first attempt was a strip.

    Raises:
        RuntimeError: If retry_fn() also returns a strip.
    """
    if not _is_strip_image(image_bytes):
        return image_bytes
    logger.warning(
        "strip_image_detected strip_retry=true role=%s request_id=%s",
        role, pack_id,
    )
    retried = retry_fn()
    if _is_strip_image(retried):
        raise RuntimeError(
            f"Composite/strip image returned for role={role!r}; retry exhausted"
        )
    logger.info("strip_retry_succeeded role=%s request_id=%s", role, pack_id)
    return retried


# ── B6 Front Anchor Gate constants and helpers ───────────────────────

# Maximum number of front-image generation attempts before falling back.
MAX_FRONT_RETRIES = 3


def _front_precheck(png_bytes: bytes) -> tuple[bool, str]:
    """Cheap Pillow pre-check before spending vision-API tokens.

    Rejects images that are obviously not passport headshots based on
    aspect ratio alone.

    Returns (ok, reason_if_failed).  Never raises — errors return True
    so the vision gate can make a finer call instead.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(png_bytes)) as img:
            w, h = img.size
            if h > 0 and w >= h * 2.2:
                return False, "strip_composite_ratio"
            if w > 0 and h >= w * 3.5:
                return False, "likely_full_body_ratio"
        return True, ""
    except Exception:
        return True, ""


def _crop_face_reference(png_bytes: bytes) -> bytes:
    """Crop a tight head/face region from a passport headshot for use as a grounding reference.

    Crops x=20%..80%, y=5%..60% of the image (captures the face, excludes shoulders/body).
    Resizes to 512×512 for stable, consistent byte size.
    Returns original bytes unchanged on any error so callers never crash.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(png_bytes)) as img:
            w, h = img.size
            left = int(w * 0.20)
            right = int(w * 0.80)
            top = int(h * 0.05)
            bottom = int(h * 0.60)
            if right <= left or bottom <= top:
                return png_bytes
            cropped = img.crop((left, top, right, bottom))
            resized = cropped.resize((512, 512), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return png_bytes


def _crop_passport_headshot(png_bytes: bytes) -> bytes:
    """Apply deterministic upper-body crop for UI card consistency.

    Keeps width; crops to roughly top-10% → 70% of image height so the
    face is centred in a standard portrait frame.  Returns original bytes
    unchanged on any error.
    """
    try:
        from PIL import Image
        with Image.open(io.BytesIO(png_bytes)) as img:
            w, h = img.size
            top = int(h * 0.10)
            bottom = int(h * 0.70)
            if bottom <= top:
                return png_bytes
            cropped = img.crop((0, top, w, bottom))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return png_bytes


# ── Helpers ──────────────────────────────────────────────────────────

PACK_ROLES = ["anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"]

KIND_FOR_ROLE = {
    "anchor_front": ImageKindEnum.ANCHOR_FRONT,
    "anchor_three_quarter": ImageKindEnum.ANCHOR_THREE_QUARTER,
    "anchor_torso": ImageKindEnum.ANCHOR_TORSO,
    "anchor_full_body": ImageKindEnum.ANCHOR_FULL_BODY,
}

ROLE_SHOT_DESCRIPTION = {
    "anchor_front": (
        "Passport-style headshot. NO sitting, NO crouching, NO full-body, NO hands. "
        "Head-and-shoulders only, straight-on camera, cropped mid-chest. "
        "Neutral expression, plain neutral background, even lighting. "
        "NO crossed arms, NO props, NO dramatic pose."
    ),
    "anchor_three_quarter": "three-quarter view, head turned about 45 degrees, angled shoulders, clearly not straight-on",
    "anchor_torso": "mid-torso framing, chest and shoulders visible, face smaller in frame, slight angle not portrait crop",
    "anchor_full_body": "full-body shot, head-to-toe, standing, natural stance, full outfit visible",
}

# Short pose-only prompts used for grounded angle generation.
# SINGLE_FRAME_ENFORCEMENT is appended at call time (not here) so the constant
# remains readable and tests can inspect the base prompts independently.
ROLE_EDIT_PROMPT = {
    "anchor_three_quarter": "same person, 3/4 view, head turned 45\u00b0, angled shoulders, not straight-on",
    "anchor_torso": "same person, camera pulled back, mid-torso framing, chest clearly visible, more body than face, not a close portrait, natural stance, slight angle",
    "anchor_full_body": "same person, full-body shot, head-to-toe, standing, natural stance, full outfit visible",
}

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"


def _build_pack_prompt(
    character: CharacterModel,
    dna: CharacterDNA | None,
    role: str,
    prompt_vibe: str | None,
    tweaks_label: str | None,
) -> str:
    """Build a concise image prompt from character data + role. Max 250 chars."""
    parts: list[str] = []

    # Character identity
    parts.append(character.name)
    if dna:
        if dna.species:
            parts.append(dna.species)
        if dna.gender_presentation:
            parts.append(dna.gender_presentation)
    elif character.species:
        parts.append(character.species)

    # Vibe / tweaks
    if prompt_vibe:
        parts.append(prompt_vibe)
    elif tweaks_label:
        parts.append(tweaks_label)

    # Shot framing for this role
    parts.append(ROLE_SHOT_DESCRIPTION[role])

    prompt = ", ".join(parts)
    # Hard-cap at 250 chars (provider validates this)
    return prompt[:250]


def _get_owned_character(
    character_id: int,
    current_user: User,
    db: Session,
) -> CharacterModel:
    """Fetch a character and verify the current user owns it."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found.",
        )
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )
    return character


# ── 0) GET /characters/{id}/images ──────────────────────────────────

@router.get(
    "/{character_id}/images",
    response_model=list[CharacterImageRead],
    summary="List persisted images for a character",
)
def list_character_images(
    character_id: int,
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> list[CharacterImageRead]:
    """Return all active, non-temporary images for a character.

    Public characters are viewable by anyone.  Non-public characters
    require the caller to be the owner or an admin.
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")

    if character.visibility != VisibilityEnum.PUBLIC:
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated.")
        is_admin = current_user.email.lower() in settings.get_admin_emails()
        if character.owner_id != current_user.id and not is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    rows: list[CharacterImage] = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .order_by(CharacterImage.created_at.desc())
        .all()
    )

    # Exclude temporary pack previews that were never accepted
    visible = [
        r for r in rows
        if not (r.metadata_json or {}).get("is_temp", False)
    ]

    return [CharacterImageRead.model_validate(r) for r in visible]


# ── 0b) POST /characters/{id}/images/{image_id}/set-avatar ─────────

@router.post(
    "/{character_id}/images/{image_id}/set-avatar",
    response_model=CharacterImageRead,
    summary="Set a character image as the avatar",
)
def set_avatar(
    character_id: int,
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterImageRead:
    """Set the character's avatar to an existing persisted image.

    Only the character owner or an admin may call this endpoint.
    The image must be ACTIVE and non-temporary.
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")

    is_admin = current_user.email.lower() in settings.get_admin_emails()
    if character.owner_id != current_user.id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    image = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.id == image_id,
            CharacterImage.character_id == character_id,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .first()
    )
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    if (image.metadata_json or {}).get("is_temp", False):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot use a temporary image as avatar.",
        )

    avatar_url = file_path_to_url(image.file_path)
    character.avatar_url = avatar_url
    db.commit()
    db.refresh(image)

    return CharacterImageRead.model_validate(image)


# ── 0c) DELETE /characters/{id}/images/{image_id} ─────────────────

_PROTECTED_KINDS = {
    ImageKindEnum.ANCHOR_FRONT,
    ImageKindEnum.ANCHOR_THREE_QUARTER,
    ImageKindEnum.ANCHOR_TORSO,
    ImageKindEnum.ANCHOR_FULL_BODY,
}


@router.delete(
    "/{character_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive (soft-delete) a character image",
)
def delete_character_image(
    character_id: int,
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Archive a generated character image. Owner or admin only.
    Identity anchor images are protected and cannot be deleted here.
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")

    is_admin = current_user.email.lower() in settings.get_admin_emails()
    if character.owner_id != current_user.id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    image = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.id == image_id,
            CharacterImage.character_id == character_id,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .first()
    )
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    if image.kind in _PROTECTED_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Identity anchor images cannot be deleted. Reset the character to start over.",
        )

    image.status = ImageStatusEnum.ARCHIVED
    db.commit()


# ── 1) POST /characters/{id}/dna ────────────────────────────────────

@router.post(
    "/{character_id}/dna",
    response_model=CharacterDNARead,
    summary="Create or update character DNA",
)
def upsert_dna(
    character_id: int,
    body: CharacterDNACreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterDNARead:
    """Upsert the visual-identity DNA for a character.

    Only the character owner may call this endpoint.
    """
    _get_owned_character(character_id, current_user, db)
    dna = upsert_character_dna(db, character_id, body)
    return dna


# ── 2) POST /characters/{id}/identity-pack/generate ─────────────────

@router.post(
    "/{character_id}/identity-pack/generate",
    response_model=IdentityPackGenerateResponse,
    summary="Generate an identity pack preview",
)
def generate_identity_pack(
    character_id: int,
    body: IdentityPackGenerateRequest,
    dry_run: bool = Query(
        False,
        description=(
            "If true, compile prompts and resolve providers without calling any "
            "image generation API or writing DB records. Returns a plan JSON."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate 4 temporary preview images for the identity pack.

    Requires that the character is NOT yet visually locked.
    The returned ``pack_id`` is used to accept or discard the pack.
    """
    character = _get_owned_character(character_id, current_user, db)

    if character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This character's visual identity is already locked. "
                "You can generate new moment images instead."
            ),
        )

    pack_id = uuid.uuid4().hex

    # Build sublabel from tweaks / vibe (used as fallback + prompt_summary)
    # Uses the raw user text so UI display is unmodified.
    tweaks_parts: list[str] = []
    if body.tweaks:
        for field, value in body.tweaks.model_dump(exclude_none=True).items():
            tweaks_parts.append(f"{field}: {value}")
    if body.prompt_vibe:
        tweaks_parts.append(f"vibe: {body.prompt_vibe}")
    sublabel = " | ".join(tweaks_parts) if tweaks_parts else "default style"

    # Fetch DNA for prompt enrichment
    dna = get_character_dna(db, character_id)

    # Character identity traits for prompt construction
    char_traits: list[str] = [character.name]
    if dna:
        if dna.species:
            char_traits.append(dna.species)
        if dna.gender_presentation:
            char_traits.append(dna.gender_presentation)
    elif character.species:
        char_traits.append(character.species)

    # ── Determine prompt source: structured spec or legacy vibe ───
    use_structured_spec = body.identity_spec is not None
    identity_spec = body.identity_spec

    # Hard validation: structured spec must have gender + age_band.
    # Pydantic already enforces this via Field(...) but we add an explicit
    # check here so the 422 message is unambiguous if somehow bypassed.
    if use_structured_spec and identity_spec is not None:
        missing = [f for f in ("gender", "age_band") if not getattr(identity_spec, f, None)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"identity_spec is missing required fields: {', '.join(missing)}",
            )

    # Normalize empty/missing style before compilation or storage
    if identity_spec and (
        not identity_spec.style
        or not identity_spec.style.strip()
    ):
        identity_spec.style = "realistic"

    if use_structured_spec:
        # identity_spec_json and identity_spec_version are written only at accept time
        # (bound to the accepted pack, not the most-recently-generated pack).
        spec_meta = {"did_rewrite": False, "reasons": [], "original_len": 0, "final_len": 0}
    else:
        identity_spec = None

    # ── Legacy appearance-spec rewrite pipeline (fallback for old clients) ─
    raw_vibe = body.prompt_vibe or ""
    if not use_structured_spec:
        try:
            appearance_spec, spec_meta = build_appearance_spec(
                raw_vibe, request_id=pack_id,
            )
            appearance_spec_conservative, _ = build_appearance_spec(
                raw_vibe, conservative=True, request_id=pack_id,
            )
            appearance_spec_failsafe, _ = build_appearance_spec(
                raw_vibe, failsafe=True, request_id=pack_id,
            )
        except PromptBlockedError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.friendly_message,
            ) from None
    else:
        appearance_spec = ""
        appearance_spec_conservative = ""
        appearance_spec_failsafe = ""

    # Resolved style (already validated/coerced by the schema)
    style = body.style

    # B7: Determine per-phase providers for the identity pack.
    # If IDENTITY_IMAGE_PROVIDER is set (legacy override), use it for both seed and angles.
    # Otherwise use IDENTITY_SEED_PROVIDER for the front anchor and
    # IDENTITY_ANGLES_PROVIDER for the 3 grounded angle shots.
    try:
        if settings.IDENTITY_IMAGE_PROVIDER:
            seed_provider_name = settings.IDENTITY_IMAGE_PROVIDER.lower()
            angles_provider_name = settings.IDENTITY_IMAGE_PROVIDER.lower()
        else:
            seed_provider_name = settings.IDENTITY_SEED_PROVIDER.lower()
            angles_provider_name = settings.IDENTITY_ANGLES_PROVIDER.lower()
        seed_provider = get_identity_provider_by_name(seed_provider_name)
        angles_provider = get_identity_provider_by_name(angles_provider_name)
        logger.info(
            "identity_pack_seed_provider=%s identity_pack_angles_provider=%s context=identity_pack",
            seed_provider_name, angles_provider_name,
        )
        use_openai = True
    except RuntimeError:
        # API key not configured — degrade to stub
        use_openai = False
        seed_provider_name = "stub"
        angles_provider_name = "stub"
        seed_provider = None  # type: ignore[assignment]
        angles_provider = None  # type: ignore[assignment]
    except ValueError as exc:
        # Provider does not support image guidance — refuse clearly
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # ── Dry-run: compile prompts + resolve providers; no API calls, no DB writes ──
    if dry_run:
        _front_preview = _build_front_anchor_prompt(
            use_structured_spec=use_structured_spec,
            identity_spec=identity_spec,
            char_traits=char_traits,
            failsafe=False,
        )
        if use_structured_spec and identity_spec is not None:
            # Use the same compile_identity_prompt path as real generation —
            # angle prompts include gender/style/age_band + NEUTRAL_STUDIO_OUTFIT.
            _angle_previews = {
                "three_quarter": _build_identity_prompt(
                    identity_spec, "anchor_three_quarter", char_traits=char_traits,
                ),
                "torso": _build_identity_prompt(
                    identity_spec, "anchor_torso", char_traits=char_traits,
                ),
                "full_body": _build_identity_prompt(
                    identity_spec, "anchor_full_body", char_traits=char_traits,
                ),
            }
        else:
            _angle_previews = {
                "three_quarter": (
                    f"{_SAFETY_PREFIX}, {ROLE_EDIT_PROMPT['anchor_three_quarter']}. "
                    f"{SINGLE_FRAME_ENFORCEMENT}. {_PG13_SAFETY_SUFFIX}"
                ),
                "torso": (
                    f"{_SAFETY_PREFIX}, {ROLE_EDIT_PROMPT['anchor_torso']}. "
                    f"{SINGLE_FRAME_ENFORCEMENT}. {_PG13_SAFETY_SUFFIX}"
                ),
                "full_body": (
                    f"{_SAFETY_PREFIX}, {ROLE_EDIT_PROMPT['anchor_full_body']}. "
                    f"{SINGLE_FRAME_ENFORCEMENT}. {_PG13_SAFETY_SUFFIX}"
                ),
            }
        return JSONResponse(content={
            "dry_run": True,
            "pack_id": pack_id,
            "seed_provider": seed_provider_name,
            "angles_provider": angles_provider_name,
            "roles": PACK_ROLES,
            "prompts_preview": {"front": _front_preview, **_angle_previews},
        })

    # Tier tracking — populated during generation
    tier_used: str = "stub"
    blocked_roles: list[str] = []

    images: list[CharacterImage] = []

    def _make_image_record(role: str, file_path: str, provider_name: str) -> CharacterImage:
        return CharacterImage(
            character_id=character_id,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            provider=provider_name,
            prompt_summary=sublabel[:200] if sublabel else None,
            metadata_json={
                "pack_role": role,
                "pack_id": pack_id,
                "is_temp": True,
                "library": False,
                "identity_spec": identity_spec.model_dump() if identity_spec is not None else None,
            },
            file_path=file_path,
        )

    if use_openai:

        def _is_moderation_block(exc: BaseException) -> bool:
            msg = str(exc).lower()
            return any(kw in msg for kw in (
                "moderation_blocked", "safety system", "safety_violation",
            ))

        def _build_prompt_for_role(spec_str: str, role: str, *, failsafe: bool = False) -> str:
            """Build a prompt for a given role using structured spec or legacy path.

            Always appends SINGLE_FRAME_ENFORCEMENT after the compiled base so
            every shot explicitly requests one frame with no strips or panels.
            """
            if use_structured_spec and identity_spec is not None:
                base = compile_identity_prompt(
                    identity_spec, role,
                    char_traits=char_traits,
                    failsafe=failsafe,
                )
            else:
                base = build_generation_prompt(
                    spec_str, char_traits,
                    ROLE_SHOT_DESCRIPTION[role],
                    style=style,
                )
            return f"{base}. {SINGLE_FRAME_ENFORCEMENT}. {_PG13_SAFETY_SUFFIX}"

        def _generate_pack_tier_ab(
            spec: str,
            tier: str,
        ) -> list[CharacterImage] | None:
            """Attempt to generate the full 4-image pack.

            Tier A uses the normal spec with images.edit for 3/4, torso, and full_body.
            Tier B uses the conservative spec with images.edit for 3/4, torso, and full_body.
            Returns None if any role is blocked by moderation.

            B7: front anchor is generated by seed_provider; the 3 angle shots are
            generated by angles_provider using generate_grounded_image.
            """
            tier_images: list[CharacterImage] = []

            # ── Step 1: Front Anchor Gate (B6) ──────────────────────
            # Generate → cheap precheck → vision validate → crop.
            # Retry up to MAX_FRONT_RETRIES times using the seed provider.
            # If seed is Google and exhausted, fall back to OpenAI (B3 legacy path).
            # If seed is OpenAI and exhausted, raise RuntimeError immediately.
            # B7.1: Front seed uses a hard passport-headshot preamble so the
            # OpenAI model never produces a full-body or dramatic shot.
            front_prompt = _build_front_anchor_prompt(
                use_structured_spec=use_structured_spec,
                identity_spec=identity_spec,
                char_traits=char_traits,
                failsafe=(tier == "C"),
            )
            # Safe preview log — only emitted at DEBUG level; first 200 chars,
            # newlines collapsed, so it never pollutes INFO streams.
            logger.debug(
                "identity_pack_front_prompt_preview request_id=%s preview=%r",
                pack_id,
                front_prompt[:200].replace("\n", " "),
            )
            front_bytes: bytes | None = None
            # Local copy of seed name — updated to "openai" if B3 Google fallback fires.
            _seed_name = seed_provider_name
            _last_front_reason = ""

            for _attempt in range(1, MAX_FRONT_RETRIES + 1):
                try:
                    _raw = seed_provider.generate_image(prompt=front_prompt)
                except (ValueError, RuntimeError) as exc:
                    if _is_moderation_block(exc):
                        logger.warning(
                            "moderation_block request_id=%s tier=%s role=anchor_front",
                            pack_id, tier,
                        )
                        blocked_roles.append(f"{tier}:anchor_front")
                        return None
                    raise

                _pre_ok, _pre_reason = _front_precheck(_raw)
                if not _pre_ok:
                    logger.warning(
                        "identity_pack_front_precheck_failed attempt=%d "
                        "provider=%s reason=%s request_id=%s",
                        _attempt, _seed_name, _pre_reason, pack_id,
                    )
                    _last_front_reason = _pre_reason
                    continue

                _verdict = validate_front_anchor_png(_raw)
                if (
                    _verdict["ok"]
                    and _verdict["is_passport_headshot"]
                    and not _verdict["has_hands_or_props"]
                    and not _verdict["is_full_body_or_seated"]
                    and _verdict["background_is_neutral"]
                ):
                    logger.info(
                        "identity_pack_front_validation_passed attempt=%d "
                        "provider=%s confidence=%.2f request_id=%s",
                        _attempt, _seed_name,
                        _verdict["confidence"], pack_id,
                    )
                    _raw = _crop_passport_headshot(_raw)
                    logger.info(
                        "identity_pack_front_crop_applied=true request_id=%s", pack_id,
                    )
                    front_bytes = _raw
                    break
                else:
                    _last_front_reason = _verdict.get("fail_reason", "validation_failed")
                    logger.warning(
                        "identity_pack_front_validation_failed attempt=%d "
                        "provider=%s reason=%s confidence=%.2f request_id=%s",
                        _attempt, _seed_name, _last_front_reason,
                        _verdict["confidence"], pack_id,
                    )

            # ── B3 Fallback: seed=Google exhausted → try OpenAI for front ──
            # Only applies to the legacy path where IDENTITY_IMAGE_PROVIDER="google".
            # In the default B7 path (seed=openai), this block is skipped and we
            # raise immediately so the caller sees a clear error.
            if front_bytes is None and _seed_name == "google":
                logger.warning(
                    "identity_pack_front_validation_fallback "
                    "provider_from=google provider_to=openai "
                    "reason=retry_exhausted last_reason=%s request_id=%s",
                    _last_front_reason, pack_id,
                )
                try:
                    _openai_fb = _OpenAIImageProvider()
                    for _fb_attempt in range(1, 3):
                        try:
                            _fb_raw = _openai_fb.generate_image(prompt=front_prompt)
                        except (ValueError, RuntimeError):
                            continue
                        _fb_pre_ok, _fb_pre_reason = _front_precheck(_fb_raw)
                        if not _fb_pre_ok:
                            logger.warning(
                                "identity_pack_front_precheck_failed attempt=%d "
                                "provider=openai reason=%s request_id=%s",
                                _fb_attempt, _fb_pre_reason, pack_id,
                            )
                            continue
                        _fb_verdict = validate_front_anchor_png(_fb_raw)
                        if (
                            _fb_verdict["ok"]
                            and _fb_verdict["is_passport_headshot"]
                            and not _fb_verdict["has_hands_or_props"]
                            and not _fb_verdict["is_full_body_or_seated"]
                            and _fb_verdict["background_is_neutral"]
                        ):
                            logger.info(
                                "identity_pack_front_validation_passed attempt=%d "
                                "provider=openai confidence=%.2f request_id=%s",
                                _fb_attempt, _fb_verdict["confidence"], pack_id,
                            )
                            _fb_raw = _crop_passport_headshot(_fb_raw)
                            logger.info(
                                "identity_pack_front_crop_applied=true request_id=%s",
                                pack_id,
                            )
                            front_bytes = _fb_raw
                            _seed_name = "openai"
                            break
                        else:
                            logger.warning(
                                "identity_pack_front_validation_failed attempt=%d "
                                "provider=openai reason=%s request_id=%s",
                                _fb_attempt,
                                _fb_verdict.get("fail_reason", "validation_failed"),
                                pack_id,
                            )
                except (RuntimeError, ValueError) as _fb_exc:
                    raise RuntimeError(
                        f"Front seed fallback to OpenAI also failed: {_fb_exc}"
                    ) from _fb_exc
                if front_bytes is None:
                    raise RuntimeError(
                        "Front anchor validation failed after OpenAI fallback"
                    )
            elif front_bytes is None:
                raise RuntimeError(
                    f"Front anchor validation failed after {MAX_FRONT_RETRIES} retries "
                    f"(seed_provider={_seed_name!r}); retry exhausted"
                )

            front_path = save_image(front_bytes)
            logger.info(
                "identity_pack_seed_generated provider=%s bytes=%d request_id=%s",
                _seed_name, len(front_bytes), pack_id,
            )
            tier_images.append(_make_image_record("anchor_front", front_path, _seed_name))

            # Step 2: 3 angle shots grounded from the cropped seed image.
            # B7: angles_provider is used for all grounded calls (default: Google).
            logger.info(
                "identity_pack_angles_provider=%s grounded=true request_id=%s",
                angles_provider_name, pack_id,
            )
            for role in ("anchor_three_quarter", "anchor_torso", "anchor_full_body"):
                # For structured spec: full identity prompt via compile_identity_prompt
                # (includes gender/style/age_band + NEUTRAL_STUDIO_OUTFIT + role pose).
                # For legacy: short pose-only edit prompt grounded from seed image.
                if use_structured_spec and identity_spec is not None:
                    edit_prompt = _build_identity_prompt(
                        identity_spec, role, char_traits=char_traits, failsafe=False,
                    )
                else:
                    edit_prompt = (
                        f"{_SAFETY_PREFIX}, {ROLE_EDIT_PROMPT[role]}. "
                        f"{SINGLE_FRAME_ENFORCEMENT}. {_PG13_SAFETY_SUFFIX}"
                    )
                # Per-angle provider name — may be updated to "openai" by B7.2/B7.3 fallback.
                _angle_provider_name = angles_provider_name

                try:
                    png_bytes = angles_provider.generate_grounded_image(
                        prompt=edit_prompt,
                        reference_image_bytes=front_bytes,
                    )
                except (ValueError, RuntimeError) as exc:
                    if _is_moderation_block(exc):
                        logger.warning(
                            "moderation_block request_id=%s tier=%s role=%s",
                            pack_id, tier, role,
                        )
                        blocked_roles.append(f"{tier}:{role}")
                        return None
                    # B7.3: Google transient/refusal error — fall back to OpenAI grounded.
                    # Covers: network timeout, URLError, and explicit content refusal.
                    _exc_str = str(exc).lower()
                    _is_google_timeout = angles_provider_name == "google" and (
                        "timed out" in _exc_str
                        or "timeout" in _exc_str
                        or "urlerror" in _exc_str
                    )
                    _is_google_refusal = (
                        angles_provider_name == "google"
                        and "google_refused_image" in _exc_str
                    )
                    if _is_google_refusal:
                        logger.warning(
                            "identity_pack_angle_refusal_fallback angle=%s "
                            "provider_from=google provider_to=openai "
                            "reason=%r request_id=%s",
                            role, str(exc)[:120], pack_id,
                        )
                    elif _is_google_timeout:
                        logger.warning(
                            "identity_pack_angle_timeout_fallback angle=%s "
                            "provider_from=google provider_to=openai "
                            "reason=%r request_id=%s",
                            role, str(exc)[:120], pack_id,
                        )
                    if _is_google_timeout or _is_google_refusal:
                        _oai_tf = get_identity_provider_by_name("openai")
                        try:
                            png_bytes = _oai_tf.generate_grounded_image(
                                prompt=edit_prompt,
                                reference_image_bytes=front_bytes,
                            )
                        except (ValueError, RuntimeError) as _oai_exc:
                            if _is_moderation_block(_oai_exc):
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=(
                                        "Identity packs must be fully clothed and non-sexual. "
                                        f"Please adjust wardrobe/notes. (role={role})"
                                    ),
                                )
                            raise
                        _angle_provider_name = "openai"
                    else:
                        raise

                # Strip enforcement only applies when this angle is still on Google.
                # (Skipped when B7.3 timeout fallback already set _angle_provider_name="openai".)
                if _angle_provider_name == "google":
                    _ep = edit_prompt  # capture for lambda closure
                    _fb = front_bytes  # capture for lambda closure
                    try:
                        png_bytes = _enforce_single_frame(
                            png_bytes,
                            retry_fn=lambda: angles_provider.generate_grounded_image(
                                prompt=_ep + _STRIP_RETRY_SUFFIX,
                                reference_image_bytes=_fb,
                            ),
                            role=role,
                            pack_id=pack_id,
                        )
                    except RuntimeError:
                        # B7.2: Google strip retry exhausted for this angle —
                        # fall back to OpenAI grounded for this angle only.
                        logger.warning(
                            "identity_pack_angle_strip_fallback angle=%s "
                            "provider_from=google provider_to=openai request_id=%s",
                            role, pack_id,
                        )
                        _oai_fb = get_identity_provider_by_name("openai")
                        try:
                            png_bytes = _oai_fb.generate_grounded_image(
                                prompt=edit_prompt,
                                reference_image_bytes=front_bytes,
                            )
                        except (ValueError, RuntimeError) as _oai_exc:
                            if _is_moderation_block(_oai_exc):
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=(
                                        "Identity packs must be fully clothed and non-sexual. "
                                        f"Please adjust wardrobe/notes. (role={role})"
                                    ),
                                )
                            raise
                        _angle_provider_name = "openai"

                file_path = save_image(png_bytes)
                logger.info(
                    "identity_pack_angle_generated provider=%s grounded=true angle=%s request_id=%s",
                    _angle_provider_name, role, pack_id,
                )
                tier_images.append(_make_image_record(role, file_path, _angle_provider_name))

            return tier_images

        def _generate_pack_tier_c(spec: str) -> list[CharacterImage]:
            """Failsafe tier: generate all 4 images via text-to-image only.

            Attempts the primary provider first (OpenAI, text-to-image only).
            On moderation block, tries the fallback provider (e.g. fal.ai).
            If both fail, falls back to stub placeholders.
            Always returns 4 images.

            In structured spec mode, failsafe softens wardrobe (drops colors,
            keeps outfit type only) to reduce moderation risk.
            """
            fallback = get_fallback_provider()
            tier_images: list[CharacterImage] = []
            for role in PACK_ROLES:
                # B8: front must use the strict passport preamble prompt builder.
                if role == "anchor_front":
                    prompt = _build_front_anchor_prompt(
                        use_structured_spec=use_structured_spec,
                        identity_spec=identity_spec,
                        char_traits=char_traits,
                        failsafe=True,
                    )
                else:
                    prompt = _build_prompt_for_role(spec, role, failsafe=True)

                # Try primary provider (text-to-image, no reference)
                try:
                    png_bytes = seed_provider.generate_image(prompt=prompt)
                    file_path = save_image(png_bytes)
                    tier_images.append(_make_image_record(role, file_path, seed_provider_name))
                    continue
                except (ValueError, RuntimeError) as exc:
                    if not _is_moderation_block(exc):
                        raise
                    logger.warning(
                        "moderation_block request_id=%s tier=C role=%s "
                        "trying_fallback",
                        pack_id, role,
                    )
                    blocked_roles.append(f"C:{role}")

                # Try fallback provider (e.g. fal.ai)
                if fallback is not None:
                    try:
                        png_bytes = fallback.generate_image(prompt=prompt)
                        file_path = save_image(png_bytes)
                        tier_images.append(_make_image_record(role, file_path, "fal"))
                        continue
                    except (ValueError, RuntimeError):
                        logger.warning(
                            "fallback_failed request_id=%s tier=C role=%s "
                            "falling_back_to_stub",
                            pack_id, role,
                        )

                # Final safety net: stub placeholder
                file_path = generate_placeholder_png(
                    label=f"{character.name} — {role.replace('_', ' ')}",
                    sublabel=sublabel,
                    role=role,
                )
                tier_images.append(_make_image_record(role, file_path, "stub"))
            return tier_images

        # ── 3-tier generation: A (normal) -> B (conservative) -> C (failsafe)
        # B8: _make_image_record no longer calls db.add(), so escalation never
        # creates orphan records — only the winning tier's images reach the session.
        result_images = _generate_pack_tier_ab(appearance_spec, "A")
        if result_images is not None:
            tier_used = "A"

        if result_images is None:
            logger.info(
                "tier_escalation request_id=%s from=A to=B", pack_id,
            )
            result_images = _generate_pack_tier_ab(appearance_spec_conservative, "B")
            if result_images is not None:
                tier_used = "B"

        if result_images is None:
            logger.info(
                "tier_escalation request_id=%s from=B to=C", pack_id,
            )
            result_images = _generate_pack_tier_c(appearance_spec_failsafe)
            tier_used = "C"

        # result_images is guaranteed non-None from tier C
        images = result_images
        db.add_all(images)
    else:
        # Stub fallback — 4 independent placeholders
        for role in PACK_ROLES:
            file_path = generate_placeholder_png(
                label=f"{character.name} — {role.replace('_', ' ')}",
                sublabel=sublabel,
                role=role,
            )
            images.append(_make_image_record(role, file_path, "stub"))
        db.add_all(images)

    db.commit()
    for img in images:
        db.refresh(img)

    return IdentityPackGenerateResponse(
        pack_id=pack_id,
        images=[CharacterImageRead.model_validate(img) for img in images],
        tier_used=tier_used,
        rewrite_applied=spec_meta.get("did_rewrite", False),
        blocked_roles=blocked_roles,
    )


# ── 3) POST /characters/{id}/identity-pack/accept ───────────────────

@router.post(
    "/{character_id}/identity-pack/accept",
    response_model=IdentityPackAcceptResponse,
    summary="Accept an identity pack and lock the visual identity",
)
def accept_identity_pack(
    character_id: int,
    body: IdentityPackAcceptRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IdentityPackAcceptResponse:
    """Promote the 4 temporary pack images to anchors and lock the character.

    After locking, the character can no longer regenerate identity packs —
    only moment images are allowed.
    """
    character = _get_owned_character(character_id, current_user, db)

    if character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This character's visual identity is already locked. "
                "No further identity packs can be accepted."
            ),
        )

    # Find the 4 temp images belonging to this pack_id
    pack_images: list[CharacterImage] = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind == ImageKindEnum.GENERATED,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )

    # Filter to the ones matching the pack_id in metadata
    matching = [
        img for img in pack_images
        if img.metadata_json
        and img.metadata_json.get("pack_id") == body.pack_id
        and img.metadata_json.get("is_temp") is True
    ]

    # Validate we have exactly 4 with the right roles
    found_roles = {img.metadata_json["pack_role"] for img in matching}
    missing = set(PACK_ROLES) - found_roles

    if len(matching) != 4 or missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Could not find a complete identity pack for pack_id '{body.pack_id}'. "
                f"Expected 4 images (anchor_front, anchor_three_quarter, anchor_torso, anchor_full_body). "
                f"{'Missing roles: ' + ', '.join(sorted(missing)) + '.' if missing else 'Found ' + str(len(matching)) + ' image(s).'}"
            ),
        )

    # Archive any existing active anchors (shouldn't exist for v1, but be safe)
    existing_anchors = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind.in_([
                ImageKindEnum.ANCHOR_FRONT,
                ImageKindEnum.ANCHOR_THREE_QUARTER,
                ImageKindEnum.ANCHOR_TORSO,
                ImageKindEnum.ANCHOR_FULL_BODY,
            ]),
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )

    had_prior_anchors = len(existing_anchors) > 0
    for anchor in existing_anchors:
        anchor.status = ImageStatusEnum.ARCHIVED

    # Promote temp images to anchors
    for img in matching:
        role = img.metadata_json["pack_role"]
        img.kind = KIND_FOR_ROLE[role]
        img.metadata_json = {
            **img.metadata_json,
            "is_temp": False,
        }

    # Update DNA anchor_version
    dna = get_character_dna(db, character_id)
    if dna and had_prior_anchors:
        dna.anchor_version += 1

    # Lock the character
    character.visual_locked = True

    # Build and persist identity anchor snapshot
    _role_key_map = {
        "anchor_front": "front",
        "anchor_three_quarter": "three_quarter",
        "anchor_torso": "torso",
        "anchor_full_body": "full_body",
    }
    anchors_dict: dict[str, dict] = {}
    for img in matching:
        role = img.metadata_json["pack_role"]
        short_key = _role_key_map.get(role, role)
        anchors_dict[short_key] = {"id": img.id, "url": file_path_to_url(img.file_path)}

    # Derive identity lock/hash from the accepted pack's bound spec.
    # Primary: identity_spec stored in pack image metadata at generation time —
    #   this is the spec that was actually used to generate these images.
    # Fallback: character.identity_spec_json for packs generated before spec binding.
    _lock_string = None
    _prompt_hash = None
    _style = "realistic"
    _anchor_height: str | None = None
    _anchor_build: str | None = None

    _pack_spec_raw = (matching[0].metadata_json or {}).get("identity_spec")
    if not isinstance(_pack_spec_raw, dict):
        # Backward compat: packs generated before spec binding lack the metadata field.
        _pack_spec_raw = None
        if character.identity_spec_json:
            try:
                _pack_spec_raw = _json.loads(character.identity_spec_json)
            except (ValueError, TypeError):
                pass

    if isinstance(_pack_spec_raw, dict):
        try:
            from app.schemas.character_visual import CharacterIdentitySpec
            spec_obj = CharacterIdentitySpec(**_pack_spec_raw)
            _lock_string = compile_identity_lock_string(spec_obj)
            _prompt_hash = identity_prompt_hash(spec_obj)
            _style = spec_obj.style
            _anchor_height = getattr(spec_obj, "body_height", None)
            _anchor_build = getattr(spec_obj, "body_build", None)
            # Commit the accepted pack's spec as the canonical identity spec (Fix 1 + Fix 2):
            # identity_spec_json reflects the spec whose images are now locked in canon,
            # and identity_spec_version counts committed identity revisions, not generate calls.
            character.identity_spec_json = _json.dumps(_pack_spec_raw)
            character.identity_spec_version = (character.identity_spec_version or 0) + 1
        except Exception:
            pass  # graceful fallback — lock/hash stay null

    character.identity_anchor_json = _json.dumps({
        "version": 1,
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "style": _style,
        "identity_prompt_hash": _prompt_hash,
        "identity_lock_string": _lock_string,
        "anchors": anchors_dict,
        "height": _anchor_height,
        "build": _anchor_build,
    })

    # Create a tight face-reference crop from the accepted front anchor.
    # Stored as IDENTITY_FACE_REF so future scene generation can use it as a
    # grounding seed for facial consistency without copying outfit/pose.
    _front_for_ref = next(
        (img for img in matching if img.metadata_json.get("pack_role") == "anchor_front"),
        None,
    )
    if _front_for_ref is not None:
        try:
            _front_raw = load_image_bytes(_front_for_ref.file_path)
            _face_ref_bytes = _crop_face_reference(_front_raw)
            _face_ref_path = save_image(_face_ref_bytes)
            _face_ref_img = CharacterImage(
                character_id=character_id,
                kind=ImageKindEnum.IDENTITY_FACE_REF,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                provider=_front_for_ref.provider,
                prompt_summary="face reference crop",
                metadata_json={
                    "pack_id": body.pack_id,
                    "is_temp": False,
                    "source": "accept_crop",
                },
                file_path=_face_ref_path,
            )
            db.add(_face_ref_img)
            logger.info(
                "identity_face_ref_created character_id=%s pack_id=%s",
                character_id, body.pack_id,
            )

            # B12: Derive face signature from the tight face crop.
            # This is best-effort — never fails the accept if the API is unavailable.
            try:
                from app.services.face_signature import build_face_signature_from_png
                _sig_result = build_face_signature_from_png(_face_ref_bytes)
                if _sig_result.get("ok"):
                    _existing_anchor = _json.loads(character.identity_anchor_json or "{}")
                    _existing_anchor["face_signature"] = {
                        "text": _sig_result["signature"],
                        "confidence": _sig_result["confidence"],
                        "model": settings.OPENAI_VISION_MODEL,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    character.identity_anchor_json = _json.dumps(_existing_anchor)
                    logger.info(
                        "face_signature_stored character_id=%s sig_chars=%d confidence=%.2f",
                        character_id,
                        len(_sig_result["signature"]),
                        _sig_result["confidence"],
                    )
                else:
                    logger.info(
                        "face_signature_skipped character_id=%s reason=%s",
                        character_id, _sig_result.get("skip_reason", "unknown"),
                    )
            except Exception as _sig_exc:
                logger.warning(
                    "face_signature_failed character_id=%s error=%s",
                    character_id, type(_sig_exc).__name__,
                )

        except Exception as _face_ref_exc:
            logger.warning(
                "identity_face_ref_crop_failed character_id=%s error=%s",
                character_id, _face_ref_exc,
            )

    write_pack_stages(character)
    db.commit()

    # Refresh everything
    for img in matching:
        db.refresh(img)
    if dna:
        db.refresh(dna)

    return IdentityPackAcceptResponse(
        anchors=[CharacterImageRead.model_validate(img) for img in matching],
        dna=CharacterDNARead.model_validate(dna) if dna else None,
    )


# ── 3b) POST /characters/{id}/identity-sketch/generate ──────────────

_SKETCH_STYLE_PROMPTS = {
    "pencil": (
        "fine pencil sketch portrait, graphite on white paper, delicate hatching, "
        "detailed facial structure, soft shading"
    ),
    "charcoal": (
        "charcoal portrait sketch, bold strokes, high contrast, dramatic shading, "
        "smudged charcoal texture, detailed face"
    ),
    "dossier": (
        "police dossier portrait illustration, clean line art, flat shading, "
        "official style, minimal colour, identity document aesthetic"
    ),
}


# ── B15.4: Sketch generation helpers ────────────────────────────────


def _load_sketch_identity_spec(
    character: "CharacterModel",
    character_id: int,
    db: "Session",
) -> "tuple[object | None, str, int | None]":
    """Load identity spec for sketch generation.

    B15.8: Source priority is determined by the character's draft/locked state.

    DRAFT (visual_locked=False):
        DNA → identity_spec_json → none
        DNA is updated by POST /dna on every creation-flow StepPersonality save,
        so it always holds the user's latest interview answers.
        identity_spec_json is only written by POST /identity-pack/generate (step 3
        of the creation flow) and may be stale if the user went back to edit their
        answers without re-running step 3.

    LOCKED (visual_locked=True):
        identity_spec_json → DNA → none
        The locked spec is the canonical, committed representation of the
        character's visual identity.  DNA is not authoritative once locked.

    Returns:
        (identity_spec, source, dna_id) where source is one of
        ``"identity_spec_json"``, ``"dna"``, or ``"none"``.
    """
    from app.schemas.character_visual import CharacterIdentitySpec  # local import keeps top clean

    is_draft = not character.visual_locked

    # B15.8: dev-mode logging of priority decision
    if settings.is_dev_mode():
        logger.debug(
            "identity_sketch_spec_load character_id=%s is_draft=%s "
            "has_identity_spec_json=%s",
            character_id,
            is_draft,
            bool(character.identity_spec_json),
        )

    # ── Inner helpers ─────────────────────────────────────────────────

    def _from_json_spec():
        """Try to parse identity spec from character.identity_spec_json."""
        if not character.identity_spec_json:
            return None, "identity_spec_json", None
        try:
            spec = CharacterIdentitySpec(**_json.loads(character.identity_spec_json))
            return spec, "identity_spec_json", None
        except Exception:
            return None, "identity_spec_json", None

    def _from_dna():
        """Try to parse identity spec from the character's DNA record."""
        dna_record = (
            db.query(CharacterDNA)
            .filter(CharacterDNA.character_id == character_id)
            .first()
        )
        if not dna_record or not dna_record.visual_traits_json:
            return None, "dna", None
        spec_dict = dna_record.visual_traits_json.get("identity_spec")
        if not spec_dict or not isinstance(spec_dict, dict):
            return None, "dna", None
        try:
            spec = CharacterIdentitySpec(**spec_dict)
            logger.debug(
                "identity_sketch_spec_from_dna character_id=%s dna_id=%s",
                character_id, dna_record.id,
            )
            return spec, "dna", dna_record.id
        except Exception as _e:
            logger.debug(
                "identity_sketch_dna_spec_parse_failed character_id=%s err=%r",
                character_id, _e,
            )
            return None, "dna", None

    # ── B15.8: Draft vs locked source priority ────────────────────────

    if is_draft:
        # DRAFT: DNA is the editing source of truth (latest interview answers).
        spec, source, dna_id = _from_dna()
        if spec is not None:
            if settings.is_dev_mode():
                logger.debug(
                    "identity_sketch_draft_spec_chosen character_id=%s source=dna "
                    "dna_id=%s gender=%r hair_color=%r hair_length=%r "
                    "eye_color=%r species=%r",
                    character_id,
                    dna_id,
                    spec.gender,
                    spec.identity.hair_color if spec.identity else None,
                    spec.identity.hair_length if spec.identity else None,
                    spec.identity.eye_color if spec.identity else None,
                    spec.species,
                )
            return spec, source, dna_id
        # No DNA spec yet — fall back to identity_spec_json (e.g. legacy draft or
        # user who skipped the personality step and went straight to identity-pack/generate)
        spec, source, dna_id = _from_json_spec()
        if spec is not None and settings.is_dev_mode():
            logger.debug(
                "identity_sketch_draft_spec_chosen character_id=%s "
                "source=identity_spec_json (no-dna-spec fallback) gender=%r",
                character_id,
                spec.gender,
            )
        if spec is None:
            return None, "none", None
        return spec, source, dna_id
    else:
        # LOCKED: identity_spec_json is the canonical locked spec.
        spec, source, dna_id = _from_json_spec()
        if spec is not None:
            return spec, source, dna_id
        # Fallback to DNA for legacy locked characters that pre-date identity_spec_json.
        spec, source, dna_id = _from_dna()
        if spec is None:
            return None, "none", None
        return spec, source, dna_id


def _build_sketch_prompt(identity_spec, style: str, character_name: str | None = None) -> str:
    """Compose the final sketch prompt from an identity spec and style.

    Implements the B15.2 hardened prompt structure:
    style → gender lock → age → species → geometry → hair → extras →
    composition → safety.  Returns a string truncated to 400 characters.

    Args:
        identity_spec: ``CharacterIdentitySpec`` instance or ``None``.
        style: one of ``"pencil"``, ``"charcoal"``, ``"dossier"``.
        character_name: fallback name used when ``identity_spec`` is ``None``.
    """
    from app.services.identity_compiler import _species_prompt as _sp

    _GENDER_LOCK = {
        "male":   "adult male face, clearly masculine facial structure, not feminine",
        "female": "adult female face, clearly feminine facial structure, not masculine",
        "other":  "androgynous adult face, balanced masculine and feminine cues",
    }
    _GENDER_ANTI_DRIFT = {
        "male":   "do not depict a woman or feminine face",
        "female": "do not depict a man or masculine face",
        "other":  "",
    }
    _FH_LABELS = {
        "stubble":     "visible male stubble",
        "short_beard": "visible short beard",
        "full_beard":  "visible full beard",
        "long_beard":  "visible long beard",
        "mustache":    "visible mustache",
        "goatee":      "visible goatee",
    }

    prompt_parts: list[str] = [_SKETCH_STYLE_PROMPTS[style]]

    if identity_spec:
        gender_val = identity_spec.gender or ""

        # 1. Gender lock
        if gender_val:
            prompt_parts.append(_GENDER_LOCK.get(gender_val, f"adult {gender_val}"))

        # 2. Age range
        if identity_spec.age_band:
            prompt_parts.append(f"age range {identity_spec.age_band}")

        # 3. Species (non-human only)
        species_desc = _sp(identity_spec)
        if species_desc:
            prompt_parts.append(species_desc)

        # 4. Face geometry block
        _geo: list[str] = []
        if identity_spec.face_shape:
            _geo.append(f"{identity_spec.face_shape} face")
        if identity_spec.jaw_type:
            _geo.append(f"{identity_spec.jaw_type} jaw")
        if identity_spec.cheekbone_type:
            _geo.append(f"{identity_spec.cheekbone_type} cheekbones")
        if identity_spec.eye_shape:
            _geo.append(f"{identity_spec.eye_shape} eyes")
        if identity_spec.eye_spacing:
            _geo.append(f"{identity_spec.eye_spacing.replace('_', ' ')} eyes")
        if identity_spec.eyebrow_shape:
            _geo.append(f"{identity_spec.eyebrow_shape} eyebrows")
        elif identity_spec.brow_type:
            _geo.append(f"{identity_spec.brow_type} eyebrows")
        if identity_spec.nose_type:
            _geo.append(f"{identity_spec.nose_type} nose")
        if identity_spec.lip_type:
            _geo.append(f"{identity_spec.lip_type.replace('_', ' ')} lips")
        if _geo:
            prompt_parts.append(", ".join(_geo))

        # 5. Hair block
        _hair_parts: list[str] = []
        core = identity_spec.identity
        if core and core.hair_length:
            _hair_parts.append(core.hair_length.lower())
        if identity_spec.hair_style:
            _hair_parts.append(identity_spec.hair_style.replace("_", " "))
        if identity_spec.hair_texture:
            _hair_parts.append(identity_spec.hair_texture)
        if core and core.hair_color:
            _hair_parts.append(core.hair_color)
        if _hair_parts:
            _hair_parts.append("hair")
            prompt_parts.append(" ".join(_hair_parts))
        if identity_spec.hairline_type:
            prompt_parts.append(f"{identity_spec.hairline_type.replace('_', ' ')} hairline")

        # 6. Additional identity (eye colour, skin, face features)
        if core:
            if core.eye_color:
                prompt_parts.append(f"{core.eye_color} eyes")
            if core.skin_tone:
                prompt_parts.append(f"{core.skin_tone} skin")
            if core.face_features:
                prompt_parts.append(", ".join(core.face_features))

        # 7. Facial hair
        if identity_spec.facial_hair_type and identity_spec.facial_hair_type != "none":
            fh_label = _FH_LABELS.get(
                identity_spec.facial_hair_type,
                f"visible {identity_spec.facial_hair_type.replace('_', ' ')}",
            )
            prompt_parts.append(fh_label)

        # 8. Anti-drift negative clause
        anti_drift = _GENDER_ANTI_DRIFT.get(gender_val, "")
        if anti_drift:
            prompt_parts.append(anti_drift)

    elif character_name:
        prompt_parts.append(f"character named {character_name}")

    # 9. Composition + safety (always last)
    prompt_parts.append(
        "head and shoulders sketch, plain paper background, no glamour styling"
    )
    prompt_parts.append(
        f"{_SAFETY_PREFIX}. Fully clothed or bust portrait only. Non-sexual. PG-13."
    )

    return ". ".join(prompt_parts)[:400]


@router.post(
    "/{character_id}/identity-sketch/generate",
    response_model=IdentitySketchGenerateResponse,
    summary="Generate and store an identity sketch anchor image",
)
def generate_identity_sketch(
    character_id: int,
    body: IdentitySketchGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IdentitySketchGenerateResponse:
    """Generate a single sketch image and store it as a permanent identity anchor.

    Does not consume identity-pack quotas.  The sketch is saved immediately
    (is_temp=False) and the character's identity_anchor_json is updated with
    sketch metadata.  Regeneration is allowed unlimited times — each call
    simply overwrites the anchor entry.
    """
    character = _get_owned_character(character_id, current_user, db)

    style = body.style  # already coerced by schema validator

    # B15.4: load identity spec via shared helper (identity_spec_json → DNA → none)
    identity_spec, spec_source, dna_id = _load_sketch_identity_spec(
        character, character_id, db
    )

    # B15.4: build prompt via shared helper
    sketch_prompt = _build_sketch_prompt(identity_spec, style, character.name)

    # Generate image — requires a real provider; fail loudly if unavailable.
    # Mirror identity pack provider resolution: IDENTITY_IMAGE_PROVIDER overrides
    # IDENTITY_SEED_PROVIDER (same precedence rule as the identity pack path).
    if settings.IDENTITY_IMAGE_PROVIDER:
        provider_name = settings.IDENTITY_IMAGE_PROVIDER.lower()
    else:
        provider_name = (settings.IDENTITY_SEED_PROVIDER or "openai").lower()
    logger.debug("identity_sketch_provider_selected provider=%s", provider_name)
    try:
        provider = get_identity_provider_by_name(provider_name)
        png_bytes = provider.generate_image(prompt=sketch_prompt)
    except (RuntimeError, ValueError) as exc:
        exc_type = type(exc).__name__
        exc_msg = str(exc)
        logger.warning(
            "identity_sketch_generation_failed "
            "provider=%s exc_type=%s reason=%r "
            "IMAGE_PROVIDER=%s IDENTITY_IMAGE_PROVIDER=%r IDENTITY_SEED_PROVIDER=%s",
            provider_name, exc_type, exc_msg,
            settings.IMAGE_PROVIDER,
            settings.IDENTITY_IMAGE_PROVIDER or "(not set)",
            settings.IDENTITY_SEED_PROVIDER,
        )
        if settings.is_dev_mode():
            detail = (
                f"Sketch generation unavailable: provider={provider_name}, "
                f"exc={exc_type}, reason={exc_msg}"
            )
        else:
            detail = "Sketch generation is temporarily unavailable."
        raise HTTPException(status_code=503, detail=detail)

    file_path = save_image(png_bytes)

    # Archive any previous identity sketch for this character
    previous_sketches = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_SKETCH,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )
    for prev in previous_sketches:
        prev.status = ImageStatusEnum.ARCHIVED

    # Persist new sketch image
    sketch_img = CharacterImage(
        character_id=character_id,
        user_id=current_user.id,
        kind=ImageKindEnum.IDENTITY_SKETCH,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider_name,
        prompt_summary=sketch_prompt[:200],
        metadata_json={"style": style, "is_temp": False},
        file_path=file_path,
    )
    db.add(sketch_img)
    db.flush()  # assign id before updating anchor json

    # Update identity_anchor_json with sketch metadata
    try:
        existing_anchor = _json.loads(character.identity_anchor_json) if character.identity_anchor_json else {}
    except Exception:
        existing_anchor = {}

    existing_anchor["sketch"] = {
        "image_id": sketch_img.id,
        "style": style,
        "spec_text": sketch_prompt[:200],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    character.identity_anchor_json = _json.dumps(existing_anchor)

    db.commit()
    db.refresh(sketch_img)

    image_url = file_path_to_url(sketch_img.file_path)

    logger.info(
        "identity_sketch_generated character_id=%s style=%s provider=%s image_id=%s",
        character_id, style, provider_name, sketch_img.id,
    )

    # B15.4: comprehensive runtime trace — dev-only, not emitted in production
    if settings.is_dev_mode():
        _archived_ids = [p.id for p in previous_sketches]
        logger.debug(
            "identity_sketch_trace "
            "character_id=%s user_id=%s "
            "spec_source=%r dna_id=%s "
            "gender=%r age_band=%r hair_color=%r hair_length=%r hair_texture=%r "
            "eye_color=%r facial_hair=%r "
            "sketch_prompt=%r prompt_len=%d "
            "provider=%r provider_mode=text-to-image reference_image=None "
            "archived_sketch_ids=%s "
            "new_image_id=%s new_image_url=%r",
            character_id,
            current_user.id,
            spec_source,
            dna_id,
            (identity_spec.gender if identity_spec else None),
            (identity_spec.age_band if identity_spec else None),
            (identity_spec.identity.hair_color if identity_spec and identity_spec.identity else None),
            (identity_spec.identity.hair_length if identity_spec and identity_spec.identity else None),
            (identity_spec.hair_texture if identity_spec else None),
            (identity_spec.identity.eye_color if identity_spec and identity_spec.identity else None),
            (identity_spec.facial_hair_type if identity_spec else None),
            sketch_prompt,
            len(sketch_prompt),
            provider_name,
            _archived_ids,
            sketch_img.id,
            image_url,
        )

    return IdentitySketchGenerateResponse(
        image_url=image_url,
        image_id=sketch_img.id,
        style=style,
        prompt_preview=sketch_prompt,  # full prompt (already ≤ 400 chars)
        provider_used=provider_name,
    )


# ── B15.4: DEV-ONLY debug trace endpoint ─────────────────────────────
# Returns the composed sketch prompt and trace metadata WITHOUT calling
# the image provider.  Returns 404 when not in dev mode so it is never
# reachable in production.

@router.get(
    "/{character_id}/identity-sketch/debug-trace",
    summary="[DEV ONLY] Inspect the composed sketch prompt and trace metadata",
    include_in_schema=False,  # hidden from public OpenAPI docs
)
def sketch_debug_trace(
    character_id: int,
    style: str = Query(default="pencil"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Developer-only: compose and return the sketch prompt + full trace without generating an image.

    Only available when ``settings.is_dev_mode()`` is True (DEBUG=true or DEV_MODE=true).
    Returns HTTP 404 in production so it cannot be reached by normal users.

    Useful for inspecting:
    - which identity spec source is used (identity_spec_json / dna / none)
    - the exact prompt that *would* be sent to the image provider
    - the provider mode (always text-to-image — no reference image is ever attached)
    - how many active previous sketches exist (for stale-sketch diagnosis)
    """
    if not settings.is_dev_mode():
        raise HTTPException(status_code=404, detail="Not found")

    character = _get_owned_character(character_id, current_user, db)

    # Coerce style
    from app.schemas.character_visual import _VALID_SKETCH_STYLES
    style = style.strip().lower() if style else "pencil"
    if style not in _VALID_SKETCH_STYLES:
        style = "pencil"

    identity_spec, spec_source, dna_id = _load_sketch_identity_spec(
        character, character_id, db
    )
    sketch_prompt = _build_sketch_prompt(identity_spec, style, character.name)

    # Count active previous sketches (diagnostic: are old sketches piling up?)
    previous_active = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_SKETCH,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )

    # Snapshot of identity_anchor_json sketch entry
    try:
        anchor = _json.loads(character.identity_anchor_json) if character.identity_anchor_json else {}
        anchor_sketch = anchor.get("sketch")
    except Exception:
        anchor_sketch = None

    # Normalised identity spec summary (safe to serialise)
    spec_summary: dict | None = None
    if identity_spec:
        core = identity_spec.identity
        spec_summary = {
            "gender": identity_spec.gender,
            "age_band": identity_spec.age_band,
            "species": identity_spec.species,
            "face_shape": identity_spec.face_shape,
            "jaw_type": identity_spec.jaw_type,
            "cheekbone_type": identity_spec.cheekbone_type,
            "eye_shape": identity_spec.eye_shape,
            "eye_spacing": identity_spec.eye_spacing,
            "eyebrow_shape": identity_spec.eyebrow_shape,
            "nose_type": identity_spec.nose_type,
            "lip_type": identity_spec.lip_type,
            "hair_texture": identity_spec.hair_texture,
            "hair_style": identity_spec.hair_style,
            "facial_hair_type": identity_spec.facial_hair_type,
            "hair_color": (core.hair_color if core else None),
            "hair_length": (core.hair_length if core else None),
            "eye_color": (core.eye_color if core else None),
            "skin_tone": (core.skin_tone if core else None),
        }

    return JSONResponse({
        "character_id": character_id,
        "user_id": current_user.id,
        "spec_source": spec_source,
        "dna_id": dna_id,
        "identity_spec": spec_summary,
        "sketch_prompt": sketch_prompt,
        "sketch_prompt_length": len(sketch_prompt),
        "prompt_cap": 400,
        "style": style,
        "provider_mode": "text-to-image",
        "reference_image": None,
        "active_previous_sketch_count": len(previous_active),
        "previous_sketch_ids": [img.id for img in previous_active],
        "identity_anchor_sketch": anchor_sketch,
    })


# ── 4) POST /characters/{id}/images/generate ────────────────────────

@router.post(
    "/{character_id}/images/generate",
    response_model=CharacterImageRead,
    summary="Generate a moment image (post-lock)",
)
def generate_moment_image(
    character_id: int,
    body: MomentGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterImageRead:
    """Generate a single character moment image.

    Requires that the character is visually locked and has 3 active anchors.
    The generated image references the current anchor version.
    """
    character = _get_owned_character(character_id, current_user, db)

    if not character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This character's visual identity hasn't been locked yet. "
                "Please generate and accept an identity pack first."
            ),
        )

    # Verify anchors exist
    active_anchors = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind.in_([
                ImageKindEnum.ANCHOR_FRONT,
                ImageKindEnum.ANCHOR_THREE_QUARTER,
                ImageKindEnum.ANCHOR_TORSO,
                ImageKindEnum.ANCHOR_FULL_BODY,
            ]),
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )

    if len(active_anchors) < 4:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This character is missing anchor images. "
                "A complete set of 4 active anchors is required to generate moments."
            ),
        )

    dna = get_character_dna(db, character_id)
    anchor_version = dna.anchor_version if dna else 1

    # Build description from request fields
    desc_parts: list[str] = []
    for field in ("outfit", "mood", "environment", "hair", "facial_hair", "notes"):
        val = getattr(body, field, None)
        if val:
            desc_parts.append(f"{field}: {val}")
    description = " | ".join(desc_parts) if desc_parts else "moment capture"

    file_path = generate_placeholder_png(
        label=f"{character.name} — moment",
        sublabel=f"anchor v{anchor_version} · {description[:80]}",
        role="generated",
    )

    img = CharacterImage(
        character_id=character_id,
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="stub",
        prompt_summary=description[:200],
        metadata_json={
            "anchor_version": anchor_version,
            "request": body.model_dump(exclude_none=True),
        },
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    return CharacterImageRead.model_validate(img)
