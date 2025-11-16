"""AI-powered content generation routes."""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.ai import (
    CharacterBioRequest,
    CharacterBioResponse,
    SceneRequest,
    SceneResponse
)
from app.services.ai_service import ai_client

router = APIRouter()


@router.post("/character-bio", response_model=CharacterBioResponse)
def generate_character_bio(
    request: CharacterBioRequest,
    current_user: User = Depends(get_current_user)
) -> CharacterBioResponse:
    """Generate AI character bio (MVP stub with fake data)."""
    return ai_client.generate_character_bio(request)


@router.post("/scene", response_model=SceneResponse)
def generate_scene(
    request: SceneRequest,
    current_user: User = Depends(get_current_user)
) -> SceneResponse:
    """Generate AI scene (MVP stub with fake data)."""
    return ai_client.generate_scene(request)
