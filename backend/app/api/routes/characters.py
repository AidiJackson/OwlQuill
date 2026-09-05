"""Character routes."""
import io
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.entitlements import can_create_character
from app.core.storage import save_image, file_path_to_url
from app.models.user import User
from app.models.character import Character as CharacterModel, VisibilityEnum
from app.models.character_image import CharacterImage, ImageStatusEnum
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.user_image import UserImage
from app.schemas.character import Character, CharacterCreate, CharacterUpdate, CharacterSearchResult
from app.schemas.character_image import (
    PUBLIC_SURFACE_UNSAFE_MESSAGE,
    is_public_surface_safe,
)
from app.services.pack_version import compute_identity_health
from app.services.seeding import is_seeder_account

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"
_AVATAR_SIZE = (512, 512)
_COVER_SIZE = (2048, 720)


def _crop_to_banner(png_bytes: bytes) -> bytes:
    """Upper-biased crop and resize PNG bytes to 2048×720 cover banner.

    Faces and subjects appear in the upper portion of most generated images.
    We bias the vertical crop toward the top (15% down from the top of the
    excess) so faces are captured reliably.  Horizontal crops (wide images)
    are always centre-cropped — no horizontal bias is needed because the
    prompt instructs left-third subject placement at generation time.
    """
    img = PILImage.open(io.BytesIO(png_bytes))
    w, h = img.size
    target_ratio = _COVER_SIZE[0] / _COVER_SIZE[1]  # ~2.844

    if w / h > target_ratio:
        # Image is wider than target — crop horizontally (centre).
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        # Image is taller than target — crop vertically with upper bias.
        new_h = int(w / target_ratio)
        excess = h - new_h
        # Upper-biased at 15%: captures face/subject near top of frame.
        # When excess is 0 or negative, top=0 (no crop needed).
        top = max(0, min(int(excess * 0.15), excess))
        img = img.crop((0, top, w, top + new_h))

    img = img.resize(_COVER_SIZE, PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _crop_to_square(png_bytes: bytes) -> bytes:
    """Center-crop and resize PNG bytes to 512×512 square avatar."""
    img = PILImage.open(io.BytesIO(png_bytes))
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    img = img.resize(_AVATAR_SIZE, PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class SetCharacterAvatarRequest(BaseModel):
    image_type: str = Field(..., pattern=r"^(character|user)$")
    image_id: int


class SetCharacterAvatarResponse(BaseModel):
    avatar_url: str


class SetCharacterCoverRequest(BaseModel):
    image_type: str = Field(..., pattern=r"^(character|user)$")
    image_id: int
    cover_position_y: float = Field(default=0.5, ge=0.0, le=1.0)
    cover_position_x: float = Field(default=0.5, ge=0.0, le=1.0)


class SetCharacterCoverResponse(BaseModel):
    cover_url: str
    cover_position_y: float
    cover_position_x: float

router = APIRouter()
logger = logging.getLogger(__name__)

_COOLDOWN_HOURS = 24
# One character per (normal) account. Seeder/admin accounts are exempt via
# is_seeder_account() so founder/seeding accounts can hold multiple characters.
_CHARACTER_LIMIT = 1


@router.post("/", response_model=Character, status_code=status.HTTP_201_CREATED)
def create_character(
    character_data: CharacterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Character:
    """Create a new character.

    Two authoritative server-side gates, in order:

    1. **Writer entitlement.** A character may only be created by an account
       that holds the paid Writer Unlock (founder/admin/seeder accounts are
       exempt). A Wanderer is a complete permanent account type, not an
       unfinished Writer, so this endpoint refuses it outright — no UI path
       needs to exist for that refusal to hold.
    2. **One-character limit.** A normal account may own at most
       ``_CHARACTER_LIMIT`` (1) character; seeder/admin accounts are exempt so
       founder/seeding accounts can hold multiple characters.
    """
    if not can_create_character(db, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Creating a character requires the Writer Unlock. "
                "Your account is a Wanderer account."
            ),
        )

    is_exempt = is_seeder_account(current_user)

    # Enforce cooldown after character deletion (seeders/admins bypass)
    if current_user.next_character_allowed_at and not is_exempt:
        now = datetime.utcnow()
        if now < current_user.next_character_allowed_at:
            remaining = current_user.next_character_allowed_at - now
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Character creation is on cooldown. "
                    f"You can create a new character in {hours}h {minutes}m "
                    f"(after {current_user.next_character_allowed_at.isoformat()}Z)."
                ),
            )

    # Enforce one-character-per-account limit (seeders/admins bypass)
    if not is_exempt:
        existing_count = db.query(CharacterModel).filter(
            CharacterModel.owner_id == current_user.id
        ).count()
        if existing_count >= _CHARACTER_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Only {_CHARACTER_LIMIT} character per account. "
                    "Delete your existing character first."
                ),
            )
    else:
        logger.info(
            "[seeder-bypass] user=%s bypassing one-character limit (create)",
            current_user.email,
        )

    db_character = CharacterModel(
        **character_data.model_dump(),
        owner_id=current_user.id
    )
    db.add(db_character)
    db.commit()
    db.refresh(db_character)
    return db_character


def _canon_generated_ids(db: Session, character_ids: List[int]) -> set:
    """Return the subset of character_ids whose identity canon has a generated
    face (a non-empty face_front_image_url).

    This distinguishes a real, generated canon from an empty draft canon row,
    which the creation flow creates early (before any image exists). Only the
    former should count as an existing character for routing purposes (S24AR).
    """
    if not character_ids:
        return set()
    rows = (
        db.query(
            CharacterIdentityCanon.character_id,
            CharacterIdentityCanon.face_canon_json,
        )
        .filter(CharacterIdentityCanon.character_id.in_(character_ids))
        .all()
    )
    ready = set()
    for cid, face_json in rows:
        if not face_json:
            continue
        try:
            face = json.loads(face_json)
        except (ValueError, TypeError):
            continue
        url = (face or {}).get("face_front_image_url")
        if isinstance(url, str) and url.strip():
            ready.add(cid)
    return ready


@router.get("/", response_model=List[Character])
def list_my_characters(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Character]:
    """List current user's characters."""
    characters = db.query(CharacterModel).filter(
        CharacterModel.owner_id == current_user.id
    ).all()
    canon_ids = _canon_generated_ids(db, [c.id for c in characters])
    for c in characters:
        c.has_identity_canon = c.id in canon_ids
    return characters


@router.get("/search", response_model=List[CharacterSearchResult])
def search_characters(
    q: str = Query("", min_length=0, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CharacterSearchResult]:
    """Search characters by name or tags.

    Returns public characters and the current user's own characters.
    """
    if len(q.strip()) < 2:
        return []

    pattern = f"%{q.strip()}%"
    results = (
        db.query(CharacterModel)
        .filter(
            or_(
                CharacterModel.visibility == VisibilityEnum.PUBLIC,
                CharacterModel.owner_id == current_user.id,
            ),
            or_(
                CharacterModel.name.ilike(pattern),
                CharacterModel.tags.ilike(pattern),
            ),
        )
        .order_by(CharacterModel.name)
        .limit(20)
        .all()
    )
    return results


@router.get("/directory", response_model=List[CharacterSearchResult])
def character_directory(
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CharacterSearchResult]:
    """Public character directory — the Wanderer browse surface.

    Lists PUBLIC characters only, newest first. The response schema carries no
    owner fields, so the directory cannot be used to cluster characters by
    account (identity-first policy).
    """
    return (
        db.query(CharacterModel)
        .filter(CharacterModel.visibility == VisibilityEnum.PUBLIC)
        .order_by(CharacterModel.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{character_id}", response_model=Character)
def get_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Character:
    """Get a character by ID.

    S24D FIX 4: requires authentication and enforces visibility server-side — a
    character is returned only when it is PUBLIC or owned by the caller. Private
    characters of other users return 404 (indistinguishable from non-existent),
    closing the unauthenticated ID-iteration scrape.
    """
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )
    if (
        character.visibility != VisibilityEnum.PUBLIC
        and character.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )
    # Owner link is shown to the owner only (permanent, character-first policy):
    # omit owner_username for non-owner viewers so a public character cannot be
    # traced back to the account that owns it.
    is_owner = character.owner_id == current_user.id
    character.owner_username = (
        character.owner.username if (is_owner and character.owner) else None
    )
    character.identity_health = compute_identity_health(character)
    character.has_identity_canon = character.id in _canon_generated_ids(db, [character.id])
    return character


def _get_visible_character(
    db: Session, character_id: int, current_user: User
) -> CharacterModel:
    """Fetch a character enforcing the standard visibility rule: PUBLIC or
    owned by the caller, else 404 (indistinguishable from nonexistent)."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character or (
        character.visibility != VisibilityEnum.PUBLIC
        and character.owner_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    return character


@router.get("/{character_id}/posts")
def get_character_posts(
    character_id: int,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A character's public timeline: posts authored BY this character only,
    restricted to realms the viewer can see. Account identity is stripped by
    the serializer for non-authors (identity-first policy)."""
    from app.core.admin_seed import auto_join_commons
    from app.models.post import Post as PostModel
    from app.models.realm import (
        Realm as RealmModel,
        RealmMembership as RealmMembershipModel,
    )
    from app.services.seeding import post_media_resolution, serialize_post_for_viewer

    _get_visible_character(db, character_id, current_user)

    # Ensure viewer is in The Commons (idempotent, same as the user timeline)
    auto_join_commons(current_user.id, db)

    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.user_id == current_user.id
    ).all()
    viewer_realm_ids = {m.realm_id for m in memberships}
    if not viewer_realm_ids:
        return []

    rows = (
        db.query(PostModel, RealmModel.name)
        .join(RealmModel, PostModel.realm_id == RealmModel.id)
        .filter(
            PostModel.character_id == character_id,
            PostModel.realm_id.in_(viewer_realm_ids),
        )
        .order_by(PostModel.created_at.desc())
        .limit(limit)
        .all()
    )
    post_media = post_media_resolution(db, [p for p, _ in rows])
    return [
        {
            "type": "post",
            "created_at": post.created_at,
            "realm_id": post.realm_id,
            "realm_name": realm_name,
            "payload": serialize_post_for_viewer(
                post, current_user, db, resolved_media=post_media
            ).model_dump(),
        }
        for post, realm_name in rows
    ]


@router.get("/{character_id}/mentions")
def get_character_mentions(
    character_id: int,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Posts that @mention this character, restricted to realms the viewer can
    see. Account identity is stripped by the serializer for non-authors
    (identity-first policy), mirroring the character timeline."""
    from app.core.admin_seed import auto_join_commons
    from app.models.post import Post as PostModel
    from app.models.post_mention import PostMention as PostMentionModel
    from app.models.realm import (
        Realm as RealmModel,
        RealmMembership as RealmMembershipModel,
    )
    from app.services.seeding import post_media_resolution, serialize_post_for_viewer

    _get_visible_character(db, character_id, current_user)

    # Ensure viewer is in The Commons (idempotent, same as the timeline)
    auto_join_commons(current_user.id, db)

    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.user_id == current_user.id
    ).all()
    viewer_realm_ids = {m.realm_id for m in memberships}
    if not viewer_realm_ids:
        return []

    rows = (
        db.query(PostModel, RealmModel.name)
        .join(PostMentionModel, PostMentionModel.post_id == PostModel.id)
        .join(RealmModel, PostModel.realm_id == RealmModel.id)
        .filter(
            PostMentionModel.mentioned_character_id == character_id,
            PostModel.realm_id.in_(viewer_realm_ids),
        )
        .order_by(PostModel.created_at.desc())
        .limit(limit)
        .all()
    )
    post_media = post_media_resolution(db, [p for p, _ in rows])
    return [
        {
            "type": "post",
            "created_at": post.created_at,
            "realm_id": post.realm_id,
            "realm_name": realm_name,
            "payload": serialize_post_for_viewer(
                post, current_user, db, resolved_media=post_media
            ).model_dump(),
        }
        for post, realm_name in rows
    ]


# NOTE: the character media library endpoint (GET /characters/{id}/images)
# lives in character_visual.py — it already serves a PUBLIC character's active
# non-temp images to any viewer, which is the Part F "media" surface.


@router.patch("/{character_id}", response_model=Character)
def update_character(
    character_id: int,
    character_update: CharacterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Character:
    """Update a character."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this character"
        )

    for field, value in character_update.model_dump(exclude_unset=True).items():
        setattr(character, field, value)

    db.commit()
    db.refresh(character)
    return character


@router.post("/{character_id}/avatar", response_model=SetCharacterAvatarResponse)
def set_character_avatar(
    character_id: int,
    req: SetCharacterAvatarRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SetCharacterAvatarResponse:
    """Set a character's avatar from an existing character image or user image."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if req.image_type == "character":
        img = db.query(CharacterImage).filter(CharacterImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        src_char = db.query(CharacterModel).filter(CharacterModel.id == img.character_id).first()
        if not src_char or src_char.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != ImageStatusEnum.ACTIVE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")
    else:
        img = db.query(UserImage).filter(UserImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        if img.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")

    # An avatar is shown wherever the character is — including to anonymous
    # visitors — so it answers to the public-surface rule even though the image
    # itself is the owner's and stays in their library untouched.
    if not is_public_surface_safe(img):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PUBLIC_SURFACE_UNSAFE_MESSAGE,
        )

    if img.file_path.startswith(("http://", "https://")):
        # R2-hosted image: use the URL directly, no local disk read needed.
        avatar_url = img.file_path
    else:
        source_path = Path(__file__).resolve().parent.parent.parent.parent / img.file_path.lstrip("/")
        if not source_path.exists():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source image file not found on disk")
        raw_bytes = source_path.read_bytes()
        avatar_bytes = _crop_to_square(raw_bytes)
        file_path = save_image(avatar_bytes)
        avatar_url = file_path_to_url(file_path)

    character.avatar_url = avatar_url
    db.commit()

    return SetCharacterAvatarResponse(avatar_url=avatar_url)


@router.post("/{character_id}/cover", response_model=SetCharacterCoverResponse)
def set_character_cover(
    character_id: int,
    req: SetCharacterCoverRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SetCharacterCoverResponse:
    """Set a character's cover/banner from an existing character image or user image."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if req.image_type == "character":
        img = db.query(CharacterImage).filter(CharacterImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        src_char = db.query(CharacterModel).filter(CharacterModel.id == img.character_id).first()
        if not src_char or src_char.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != ImageStatusEnum.ACTIVE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")
    else:
        from app.models.user_image import UserImage
        img = db.query(UserImage).filter(UserImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        if img.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
        if img.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
        if (img.metadata_json or {}).get("is_temp", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")

    # A cover is the character's most public surface of all — the hero image on
    # the profile. Same rule as the avatar.
    if not is_public_surface_safe(img):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PUBLIC_SURFACE_UNSAFE_MESSAGE,
        )

    # Use the original image directly as the cover URL.
    # CSS object-fit:cover + object-position handles all positioning at render time.
    cover_url = file_path_to_url(img.file_path)

    character.cover_url = cover_url
    character.cover_position_y = req.cover_position_y
    character.cover_position_x = req.cover_position_x
    db.commit()

    return SetCharacterCoverResponse(
        cover_url=cover_url,
        cover_position_y=req.cover_position_y,
        cover_position_x=req.cover_position_x,
    )


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Delete a character and enforce a 24-hour creation cooldown."""
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found"
        )
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this character"
        )

    db.delete(character)

    # Clear the active-character selection if it pointed at this character
    # (explicit, in addition to the FK's ON DELETE SET NULL).
    if current_user.active_character_id == character_id:
        current_user.active_character_id = None

    # Set 24h cooldown on the user (seeders/admins bypass)
    if not is_seeder_account(current_user):
        current_user.next_character_allowed_at = datetime.utcnow() + timedelta(hours=_COOLDOWN_HOURS)
    else:
        logger.info(
            "[seeder-bypass] user=%s bypassing delete cooldown (character_id=%s)",
            current_user.email,
            character_id,
        )

    db.commit()
