"""User routes."""
import io
import uuid
from pathlib import Path
from typing import List

from datetime import datetime

from PIL import Image as PILImage

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, computed_field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.admin_seed import auto_join_commons
from app.models.user import User as UserModel
from app.models.user_image import UserImage
from app.models.character import Character as CharacterModel, VisibilityEnum
from app.models.character_image import CharacterImage, ImageStatusEnum
from app.models.post import Post as PostModel
from app.models.scene import Scene as SceneModel, SceneVisibilityEnum
from app.models.realm import Realm as RealmModel, RealmMembership as RealmMembershipModel
from app.schemas.post import Post
from app.schemas.scene import SceneOut
from app.schemas.user import User, UserUpdate, PublicUserProfile
from app.schemas.character import CharacterSearchResult
from app.schemas.character_image import CharacterImageRead
from app.services.image_provider import get_image_provider

router = APIRouter()

# ── Cover presets ────────────────────────────────────────────────────

COVER_PRESETS = {
    "enchanted_library": (
        "Wide cinematic banner: an ancient enchanted library at golden hour, "
        "towering bookshelves with glowing runes, floating open books, "
        "warm candlelight, dust motes, fantasy atmosphere, 2048x720"
    ),
    "midnight_citadel": (
        "Wide cinematic banner: a gothic citadel under a starry midnight sky, "
        "moonlit stone towers, swirling aurora, dark fantasy atmosphere, "
        "dramatic lighting, mist rolling through battlements, 2048x720"
    ),
    "celestial_garden": (
        "Wide cinematic banner: an ethereal floating garden among clouds, "
        "bioluminescent flowers, crystal waterfalls, soft pastel sunrise, "
        "fantasy dreamscape, magical atmosphere, 2048x720"
    ),
}

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"


def _save_png_bytes(png_bytes: bytes) -> str:
    """Write PNG bytes to static/generated/<uuid>.png. Return relative file_path."""
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    (_GENERATED_DIR / filename).write_bytes(png_bytes)
    return f"static/generated/{filename}"


_COVER_SIZE = (2048, 720)
_AVATAR_SIZE = (512, 512)


def _crop_to_banner(png_bytes: bytes) -> bytes:
    """Center-crop and resize PNG bytes to the cover banner size (2048x720)."""
    img = PILImage.open(io.BytesIO(png_bytes))
    src_w, src_h = img.size
    target_ratio = _COVER_SIZE[0] / _COVER_SIZE[1]  # ~2.844
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider — crop width
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        # Source is taller — crop height
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))

    img = img.resize(_COVER_SIZE, PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _is_admin(user: UserModel) -> bool:
    return user.email.lower() in settings.get_admin_emails()


class CoverGenerateRequest(BaseModel):
    preset_name: str = Field(..., description="One of: enchanted_library, midnight_citadel, celestial_garden")


class CoverGenerateResponse(BaseModel):
    cover_url: str
    image_id: int


class UserImageRead(BaseModel):
    id: int
    user_id: int
    kind: str
    status: str
    provider: str | None = None
    prompt_summary: str | None = None
    metadata_json: dict | None = None
    file_path: str
    created_at: datetime

    @computed_field
    @property
    def url(self) -> str:
        path = self.file_path.lstrip("/")
        if not path.startswith("static/"):
            return f"/static/{path}"
        return f"/{path}"

    model_config = {"from_attributes": True}


@router.get("/me", response_model=User)
def get_current_user_info(current_user: UserModel = Depends(get_current_user)) -> User:
    """Get current user information."""
    return current_user


@router.patch("/me", response_model=User)
def update_current_user(
    user_update: UserUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """Update current user information."""
    if user_update.display_name is not None:
        current_user.display_name = user_update.display_name
    if user_update.bio is not None:
        current_user.bio = user_update.bio
    if user_update.avatar_url is not None:
        current_user.avatar_url = user_update.avatar_url
    if user_update.cover_url is not None:
        current_user.cover_url = user_update.cover_url

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/cover/generate", response_model=CoverGenerateResponse)
def generate_profile_cover(
    req: CoverGenerateRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoverGenerateResponse:
    """Generate a profile cover image from a preset (admin-only beta)."""
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cover generation is currently admin-only.",
        )

    prompt = COVER_PRESETS.get(req.preset_name)
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown preset. Choose from: {', '.join(COVER_PRESETS.keys())}",
        )

    try:
        provider = get_image_provider()
        png_bytes = provider.generate_image(prompt=prompt, size="1536x1024")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Image generation failed: {exc}",
        )

    banner_bytes = _crop_to_banner(png_bytes)
    file_path = _save_png_bytes(banner_bytes)
    cover_url = f"/{file_path}"

    # Store image record
    img = UserImage(
        user_id=current_user.id,
        kind="profile_cover",
        status="active",
        provider=settings.IMAGE_PROVIDER,
        prompt_summary=f"preset:{req.preset_name}",
        metadata_json={"preset_name": req.preset_name, "is_temp": False},
        file_path=file_path,
    )
    db.add(img)

    # Set as active cover
    current_user.cover_url = cover_url
    db.commit()
    db.refresh(img)

    return CoverGenerateResponse(cover_url=cover_url, image_id=img.id)


@router.post("/me/images/{image_id}/set-cover", response_model=CoverGenerateResponse)
def set_profile_cover(
    image_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoverGenerateResponse:
    """Set an existing UserImage as the active profile cover."""
    img = db.query(UserImage).filter(UserImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    if img.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your image")
    if img.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not active")
    if img.kind != "profile_cover":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is not a profile cover")
    if (img.metadata_json or {}).get("is_temp", False):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot use a temporary image")

    # Derive servable URL (same logic as UserImageRead.url)
    path = img.file_path.lstrip("/")
    cover_url = f"/static/{path}" if not path.startswith("static/") else f"/{path}"

    current_user.cover_url = cover_url
    db.commit()

    return CoverGenerateResponse(cover_url=cover_url, image_id=img.id)


def _crop_to_square(png_bytes: bytes) -> bytes:
    """Center-crop and resize PNG bytes to 512x512 square avatar."""
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


class SetAvatarRequest(BaseModel):
    image_type: str = Field(..., pattern=r"^(character|user)$", description="'character' or 'user'")
    image_id: int


class SetAvatarResponse(BaseModel):
    avatar_url: str


@router.post("/me/avatar", response_model=SetAvatarResponse)
def set_avatar(
    req: SetAvatarRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SetAvatarResponse:
    """Set user avatar from an existing character image or user image."""

    if req.image_type == "character":
        img = db.query(CharacterImage).filter(CharacterImage.id == req.image_id).first()
        if not img:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        # Verify ownership via character
        char = db.query(CharacterModel).filter(CharacterModel.id == img.character_id).first()
        if not char or char.owner_id != current_user.id:
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

    # Load source image and crop to square
    source_path = Path(__file__).resolve().parent.parent.parent.parent / img.file_path.lstrip("/")
    if not source_path.exists():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source image file not found on disk")

    raw_bytes = source_path.read_bytes()
    avatar_bytes = _crop_to_square(raw_bytes)
    file_path = _save_png_bytes(avatar_bytes)
    avatar_url = f"/{file_path}"

    current_user.avatar_url = avatar_url
    db.commit()

    return SetAvatarResponse(avatar_url=avatar_url)


@router.get("/me/character-images", response_model=List[CharacterImageRead])
def list_my_character_images(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    """List all character images owned by the current user (ACTIVE, non-temp)."""
    images = (
        db.query(CharacterImage)
        .join(CharacterModel, CharacterImage.character_id == CharacterModel.id)
        .filter(
            CharacterModel.owner_id == current_user.id,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .order_by(CharacterImage.created_at.desc())
        .all()
    )
    # Filter out temp images (metadata_json.is_temp == true)
    return [
        img for img in images
        if not (img.metadata_json or {}).get("is_temp", False)
    ]


@router.get("/me/images", response_model=List[UserImageRead])
def list_my_images(
    kind: str | None = Query(None, description="Filter by kind, e.g. profile_cover"),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    """List the current user's images (UserImage table)."""
    query = db.query(UserImage).filter(
        UserImage.user_id == current_user.id,
        UserImage.status == "active",
    )
    if kind:
        query = query.filter(UserImage.kind == kind)
    return query.order_by(UserImage.created_at.desc()).all()


@router.get("/{username}", response_model=PublicUserProfile)
def get_user_profile(
    username: str,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PublicUserProfile:
    """Get a public-facing user profile by username (no email)."""
    user = db.query(UserModel).filter(UserModel.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{username}/characters", response_model=List[CharacterSearchResult])
def get_user_characters(
    username: str,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a user's characters. Returns only public characters unless the requester is the same user."""
    target = db.query(UserModel).filter(UserModel.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    query = db.query(CharacterModel).filter(CharacterModel.owner_id == target.id)

    # Only show public characters to other users
    if current_user.id != target.id:
        query = query.filter(CharacterModel.visibility == VisibilityEnum.PUBLIC)

    return query.order_by(CharacterModel.created_at.desc()).all()


@router.get("/{username}/timeline")
def get_user_timeline(
    username: str,
    limit: int = 20,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a user's profile timeline (posts + scenes), access-safe."""
    # Ensure viewer is in The Commons (idempotent)
    auto_join_commons(current_user.id, db)

    # Resolve target user
    target = db.query(UserModel).filter(UserModel.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Viewer realm memberships
    memberships = db.query(RealmMembershipModel).filter(
        RealmMembershipModel.user_id == current_user.id
    ).all()
    viewer_realm_ids = {m.realm_id for m in memberships}
    if not viewer_realm_ids:
        return []

    items = []

    # Posts authored by target user (only in realms viewer can see)
    posts = (
        db.query(PostModel, RealmModel.name)
        .join(RealmModel, PostModel.realm_id == RealmModel.id)
        .filter(
            PostModel.author_user_id == target.id,
            PostModel.realm_id.in_(viewer_realm_ids),
        )
        .order_by(PostModel.created_at.desc())
        .limit(limit)
        .all()
    )
    for post, realm_name in posts:
        items.append({
            "type": "post",
            "created_at": post.created_at,
            "realm_id": post.realm_id,
            "realm_name": realm_name,
            "payload": Post.model_validate(post).model_dump(),
        })

    # Scenes created by target user (only in realms viewer can see)
    scenes = (
        db.query(SceneModel, RealmModel.name)
        .join(RealmModel, SceneModel.realm_id == RealmModel.id)
        .filter(
            SceneModel.created_by_user_id == target.id,
            SceneModel.realm_id.in_(viewer_realm_ids),
        )
        .order_by(SceneModel.created_at.desc())
        .limit(limit)
        .all()
    )
    for scene, realm_name in scenes:
        if scene.visibility == SceneVisibilityEnum.PRIVATE and scene.created_by_user_id != current_user.id:
            continue
        items.append({
            "type": "scene",
            "created_at": scene.created_at,
            "realm_id": scene.realm_id,
            "realm_name": realm_name,
            "payload": SceneOut.model_validate(scene).model_dump(),
        })

    # Merge + sort
    items.sort(key=lambda i: i["created_at"], reverse=True)
    return items[:limit]
