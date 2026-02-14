"""Character visual endpoints — DNA, identity pack, and moment generation."""
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
from app.services.stub_image_generator import generate_placeholder_png
from app.services.image_provider import get_image_provider, ImageProvider

router = APIRouter()

# ── Helpers ──────────────────────────────────────────────────────────

PACK_ROLES = ["anchor_front", "anchor_three_quarter", "anchor_torso"]

KIND_FOR_ROLE = {
    "anchor_front": ImageKindEnum.ANCHOR_FRONT,
    "anchor_three_quarter": ImageKindEnum.ANCHOR_THREE_QUARTER,
    "anchor_torso": ImageKindEnum.ANCHOR_TORSO,
}

ROLE_SHOT_DESCRIPTION = {
    "anchor_front": "front-facing head-and-shoulders portrait, neutral expression",
    "anchor_three_quarter": "three-quarter view portrait, same person",
    "anchor_torso": "waist-up torso view, same person",
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
    tweaks_parts: list[str] = []
    if body.tweaks:
        for field, value in body.tweaks.model_dump(exclude_none=True).items():
            tweaks_parts.append(f"{field}: {value}")
    if body.prompt_vibe:
        tweaks_parts.append(f"vibe: {body.prompt_vibe}")
    sublabel = " | ".join(tweaks_parts) if tweaks_parts else "default style"

    # Fetch DNA for prompt enrichment
    dna = get_character_dna(db, character_id)

    # Try OpenAI provider; fall back to stub if unavailable
    try:
        provider = get_image_provider()
        use_openai = True
    except (RuntimeError, ValueError):
        use_openai = False

    images: list[CharacterImage] = []
    for role in PACK_ROLES:
        if use_openai:
            prompt = _build_pack_prompt(
                character, dna, role, body.prompt_vibe,
                sublabel if sublabel != "default style" else None,
            )
            try:
                png_bytes = provider.generate_image(prompt=prompt)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Image generation failed for {role}: {exc}",
                ) from exc
            file_path = _save_png_bytes(png_bytes)
            provider_name = "openai"
        else:
            file_path = generate_placeholder_png(
                label=f"{character.name} — {role.replace('_', ' ')}",
                sublabel=sublabel,
                role=role,
            )
            provider_name = "stub"

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
