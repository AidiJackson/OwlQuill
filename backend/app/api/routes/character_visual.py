"""Character visual endpoints — DNA, identity pack, and moment generation."""
import logging
import uuid
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
from app.services.stub_image_generator import generate_placeholder_png
from app.services.image_provider import get_image_provider, ImageProvider

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Helpers ──────────────────────────────────────────────────────────

PACK_ROLES = ["anchor_front", "anchor_three_quarter", "anchor_torso"]

KIND_FOR_ROLE = {
    "anchor_front": ImageKindEnum.ANCHOR_FRONT,
    "anchor_three_quarter": ImageKindEnum.ANCHOR_THREE_QUARTER,
    "anchor_torso": ImageKindEnum.ANCHOR_TORSO,
}

ROLE_SHOT_DESCRIPTION = {
    "anchor_front": "front-facing head-and-shoulders portrait, centered, eye-level camera",
    "anchor_three_quarter": "three-quarter view, head turned about 45 degrees, angled shoulders, clearly not straight-on",
    "anchor_torso": "mid-torso framing, chest and shoulders visible, face smaller in frame, slight angle not portrait crop",
}

# Short pose-only prompts used with images.edit (reference_image_url = front anchor).
# These intentionally omit character identity — the reference image carries it.
ROLE_EDIT_PROMPT = {
    "anchor_three_quarter": "same person, 3/4 view, head turned 45\u00b0, angled shoulders, not straight-on",
    "anchor_torso": "same person, camera pulled back, mid-torso framing, chest clearly visible, more body than face, not a close portrait, natural stance, slight angle",
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
    """Generate 3 temporary preview images for the identity pack.

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

    # ── Appearance-spec rewrite pipeline ─────────────────────────
    raw_vibe = body.prompt_vibe or ""
    try:
        appearance_spec, spec_meta = build_appearance_spec(
            raw_vibe, request_id=pack_id,
        )
        appearance_spec_conservative, _ = build_appearance_spec(
            raw_vibe, conservative=True, request_id=pack_id,
        )
    except PromptBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.friendly_message,
        ) from None

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

    # Try OpenAI provider; fall back to stub if unavailable
    try:
        provider = get_image_provider()
        use_openai = True
    except (RuntimeError, ValueError):
        use_openai = False

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

        _FRIENDLY_RETRY_ERROR = (
            "We couldn't generate this look right now. "
            "Try removing explicit terms. Outfits like swimsuits "
            "and tight dresses are fine; nudity isn't supported."
        )

        def _generate_with_retry(
            *,
            prompt_normal: str,
            prompt_conservative: str,
            role: str,
            reference_image_url: str | None = None,
        ) -> bytes:
            """Try generation; on moderation block retry with conservative prompt."""
            try:
                return provider.generate_image(
                    prompt=prompt_normal,
                    reference_image_url=reference_image_url,
                )
            except (ValueError, RuntimeError) as exc:
                if not _is_moderation_block(exc):
                    raise
                logger.warning(
                    "moderation_block request_id=%s role=%s retrying_conservative",
                    pack_id, role,
                )
                try:
                    return provider.generate_image(
                        prompt=prompt_conservative,
                        reference_image_url=reference_image_url,
                    )
                except (ValueError, RuntimeError):
                    logger.warning(
                        "moderation_block request_id=%s role=%s retry_failed",
                        pack_id, role,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=_FRIENDLY_RETRY_ERROR,
                    ) from None

        # Step 1: Generate anchor_front via text-to-image
        front_prompt = build_generation_prompt(
            appearance_spec, char_traits,
            ROLE_SHOT_DESCRIPTION["anchor_front"],
        )
        front_prompt_conservative = build_generation_prompt(
            appearance_spec_conservative, char_traits,
            ROLE_SHOT_DESCRIPTION["anchor_front"],
        )

        try:
            front_bytes = _generate_with_retry(
                prompt_normal=front_prompt,
                prompt_conservative=front_prompt_conservative,
                role="anchor_front",
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=_FRIENDLY_RETRY_ERROR,
            ) from exc
        front_path = _save_png_bytes(front_bytes)
        _make_image_record("anchor_front", front_path, "openai")

        # Step 2: Generate 3/4 and torso via images.edit using front as reference
        base_url = settings.BACKEND_PUBLIC_URL.rstrip("/")
        front_url = f"{base_url}/{front_path}"

        for role in ("anchor_three_quarter", "anchor_torso"):
            # Edit prompts are pose-only; the reference image carries identity.
            # Do NOT add safety-context words here — they paradoxically
            # make the images.edit moderation more sensitive.
            edit_prompt = ROLE_EDIT_PROMPT[role]
            try:
                png_bytes = _generate_with_retry(
                    prompt_normal=edit_prompt,
                    prompt_conservative=edit_prompt,
                    role=role,
                    reference_image_url=front_url,
                )
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=_FRIENDLY_RETRY_ERROR,
                ) from exc
            file_path = _save_png_bytes(png_bytes)
            _make_image_record(role, file_path, "openai")
    else:
        # Stub fallback — 3 independent placeholders (unchanged)
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
    """Promote the 3 temporary pack images to anchors and lock the character.

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

    # Find the 3 temp images belonging to this pack_id
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

    # Validate we have exactly 3 with the right roles
    found_roles = {img.metadata_json["pack_role"] for img in matching}
    missing = set(PACK_ROLES) - found_roles

    if len(matching) != 3 or missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Could not find a complete identity pack for pack_id '{body.pack_id}'. "
                f"Expected 3 images (anchor_front, anchor_three_quarter, anchor_torso). "
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
            ]),
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )

    if len(active_anchors) < 3:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This character is missing anchor images. "
                "A complete set of 3 active anchors is required to generate moments."
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
