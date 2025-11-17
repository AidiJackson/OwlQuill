"""Media upload routes."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.character import Character
from app.models.post import Post
from app.models.media import MediaKind
from app.schemas.media import MediaOut
from app.services.media import media_service

router = APIRouter()


@router.post("/avatar/user", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def upload_user_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MediaOut:
    """Upload avatar for current user."""
    # Upload file
    media = await media_service.upload_media(
        file=file,
        owner=current_user,
        kind=MediaKind.USER_AVATAR,
        db=db
    )

    # Update user's avatar_media_id
    current_user.avatar_media_id = media.id
    db.commit()
    db.refresh(current_user)

    return media


@router.post("/avatar/character/{character_id}", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def upload_character_avatar(
    character_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MediaOut:
    """Upload avatar for a character."""
    # Get character
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # Check ownership
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this character")

    # Upload file
    media = await media_service.upload_media(
        file=file,
        owner=current_user,
        kind=MediaKind.CHARACTER_AVATAR,
        db=db
    )

    # Update character's avatar_media_id
    character.avatar_media_id = media.id
    db.commit()
    db.refresh(character)

    return media


@router.post("/post/{post_id}/image", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def upload_post_image(
    post_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MediaOut:
    """Upload image for a post."""
    # Get post
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Check ownership
    if post.author_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this post")

    # Upload file
    media = await media_service.upload_media(
        file=file,
        owner=current_user,
        kind=MediaKind.POST_IMAGE,
        db=db
    )

    # Update post's image_media_id
    post.image_media_id = media.id
    db.commit()
    db.refresh(post)

    return media
