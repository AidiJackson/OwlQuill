"""Character visual endpoints — DNA, identity pack, and moment generation."""
import io
import json as _json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, get_current_user_optional
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
)
from app.services.character_visual import upsert_character_dna, get_character_dna
from app.services.appearance_spec import (
    build_appearance_spec,
    build_generation_prompt,
    PromptBlockedError,
)
from app.services.identity_compiler import (
    compile_identity_prompt,
    compile_identity_lock_string,
    identity_prompt_hash,
)
from app.services.stub_image_generator import generate_placeholder_png
from app.services.image_provider import (
    get_identity_image_provider,
    get_fallback_provider,
    ImageProvider,
    _OpenAIImageProvider,
)

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


def _save_png_bytes(png_bytes: bytes) -> str:
    """Write PNG bytes to static/generated/<uuid>.png. Return relative file_path."""
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    (_GENERATED_DIR / filename).write_bytes(png_bytes)
    return f"static/generated/{filename}"


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

    # Derive the servable URL (same logic as CharacterImageRead.url)
    path = image.file_path.lstrip("/")
    avatar_url = f"/{path}" if path.startswith("static/") else f"/static/{path}"

    character.avatar_url = avatar_url
    db.commit()
    db.refresh(image)

    return CharacterImageRead.model_validate(image)


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IdentityPackGenerateResponse:
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

    # Normalize empty/missing style before compilation or storage
    if identity_spec and (
        not identity_spec.style
        or not identity_spec.style.strip()
    ):
        identity_spec.style = "realistic"

    if use_structured_spec:
        # Store the identity spec on the character for future use
        character.identity_spec_json = _json.dumps(identity_spec.model_dump())
        character.identity_spec_version = (character.identity_spec_version or 0) + 1
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

    # Try identity image provider; fall back to stub only on missing credentials.
    # If the provider lacks image guidance support, fail loudly (ValueError).
    try:
        provider = get_identity_image_provider()
        identity_provider_name = (settings.IDENTITY_IMAGE_PROVIDER or settings.IMAGE_PROVIDER).lower()
        logger.info("image_provider provider=%s context=identity_pack", identity_provider_name)
        use_openai = True
    except RuntimeError:
        # API key not configured — degrade to stub
        use_openai = False
        identity_provider_name = "stub"
    except ValueError as exc:
        # Provider does not support image guidance — refuse clearly
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Tier tracking — populated during generation
    tier_used: str = "stub"
    blocked_roles: list[str] = []

    images: list[CharacterImage] = []

    def _make_image_record(role: str, file_path: str, provider_name: str) -> CharacterImage:
        img = CharacterImage(
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
            },
            file_path=file_path,
        )
        db.add(img)
        images.append(img)
        return img

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
            return f"{base}. {SINGLE_FRAME_ENFORCEMENT}"

        def _generate_pack_tier_ab(
            spec: str,
            tier: str,
        ) -> list[CharacterImage] | None:
            """Attempt to generate the full 4-image pack.

            Tier A uses the normal spec with images.edit for 3/4, torso, and full_body.
            Tier B uses the conservative spec with images.edit for 3/4, torso, and full_body.
            Returns None if any role is blocked by moderation.
            """
            tier_images: list[CharacterImage] = []

            # Step 1: front via text-to-image — this is the identity seed
            front_prompt = _build_prompt_for_role(spec, "anchor_front")
            try:
                front_bytes = provider.generate_image(prompt=front_prompt)
            except (ValueError, RuntimeError) as exc:
                if _is_moderation_block(exc):
                    logger.warning(
                        "moderation_block request_id=%s tier=%s role=anchor_front",
                        pack_id, tier,
                    )
                    blocked_roles.append(f"{tier}:anchor_front")
                    return None
                raise
            seed_provider_name = identity_provider_name
            if identity_provider_name == "google":
                try:
                    front_bytes = _enforce_single_frame(
                        front_bytes,
                        retry_fn=lambda: provider.generate_image(
                            prompt=front_prompt + _STRIP_RETRY_SUFFIX
                        ),
                        role="anchor_front",
                        pack_id=pack_id,
                    )
                except RuntimeError:
                    logger.warning(
                        "identity_pack_seed_fallback provider_from=google provider_to=openai "
                        "reason=strip_retry_exhausted request_id=%s",
                        pack_id,
                    )
                    try:
                        _openai = _OpenAIImageProvider()
                        front_bytes = _openai.generate_image(prompt=front_prompt)
                        seed_provider_name = "openai"
                    except (RuntimeError, ValueError) as openai_exc:
                        raise RuntimeError(
                            f"Front seed fallback to OpenAI also failed: {openai_exc}"
                        ) from openai_exc
            front_path = _save_png_bytes(front_bytes)
            logger.info(
                "identity_pack_seed_generated provider=%s bytes=%d request_id=%s",
                seed_provider_name, len(front_bytes), pack_id,
            )
            tier_images.append(_make_image_record("anchor_front", front_path, seed_provider_name))

            # Step 2: remaining angles grounded by seed bytes (preserves identity)
            for role in ("anchor_three_quarter", "anchor_torso", "anchor_full_body"):
                # Append enforcement suffix so every angle prompt requests one frame.
                edit_prompt = ROLE_EDIT_PROMPT[role] + ". " + SINGLE_FRAME_ENFORCEMENT
                try:
                    png_bytes = provider.generate_grounded_image(
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
                    raise
                if identity_provider_name == "google":
                    _ep = edit_prompt  # capture for lambda closure
                    _fb = front_bytes  # capture for lambda closure
                    png_bytes = _enforce_single_frame(
                        png_bytes,
                        retry_fn=lambda: provider.generate_grounded_image(
                            prompt=_ep + _STRIP_RETRY_SUFFIX,
                            reference_image_bytes=_fb,
                        ),
                        role=role,
                        pack_id=pack_id,
                    )
                file_path = _save_png_bytes(png_bytes)
                logger.info(
                    "identity_pack_angle_generated provider=%s grounded=true angle=%s request_id=%s",
                    identity_provider_name, role, pack_id,
                )
                tier_images.append(_make_image_record(role, file_path, identity_provider_name))

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
                prompt = _build_prompt_for_role(spec, role, failsafe=True)

                # Try primary provider (text-to-image, no reference)
                try:
                    png_bytes = provider.generate_image(prompt=prompt)
                    file_path = _save_png_bytes(png_bytes)
                    tier_images.append(_make_image_record(role, file_path, identity_provider_name))
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
                        file_path = _save_png_bytes(png_bytes)
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
        result_images = _generate_pack_tier_ab(appearance_spec, "A")
        if result_images is not None:
            tier_used = "A"

        if result_images is None:
            # Tier A blocked — clear partial images from this attempt
            images.clear()
            logger.info(
                "tier_escalation request_id=%s from=A to=B", pack_id,
            )
            result_images = _generate_pack_tier_ab(appearance_spec_conservative, "B")
            if result_images is not None:
                tier_used = "B"

        if result_images is None:
            # Tier B blocked — clear partial images, use failsafe
            images.clear()
            logger.info(
                "tier_escalation request_id=%s from=B to=C", pack_id,
            )
            result_images = _generate_pack_tier_c(appearance_spec_failsafe)
            tier_used = "C"

        # result_images is guaranteed non-None from tier C
    else:
        # Stub fallback — 4 independent placeholders (unchanged)
        for role in PACK_ROLES:
            file_path = generate_placeholder_png(
                label=f"{character.name} — {role.replace('_', ' ')}",
                sublabel=sublabel,
                role=role,
            )
            _make_image_record(role, file_path, "stub")

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
        path = img.file_path.lstrip("/")
        url = f"/{path}" if path.startswith("static/") else f"/static/{path}"
        anchors_dict[short_key] = {"id": img.id, "url": url}

    # Derive identity lock/hash from stored spec if available
    _lock_string = None
    _prompt_hash = None
    _style = "realistic"
    if character.identity_spec_json:
        try:
            from app.schemas.character_visual import CharacterIdentitySpec
            spec_obj = CharacterIdentitySpec(**_json.loads(character.identity_spec_json))
            _lock_string = compile_identity_lock_string(spec_obj)
            _prompt_hash = identity_prompt_hash(spec_obj)
            _style = spec_obj.style
        except Exception:
            pass  # graceful fallback — lock/hash stay null

    character.identity_anchor_json = _json.dumps({
        "version": 1,
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "style": _style,
        "identity_prompt_hash": _prompt_hash,
        "identity_lock_string": _lock_string,
        "anchors": anchors_dict,
    })

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
