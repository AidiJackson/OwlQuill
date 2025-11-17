"""AI-powered content generation routes."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.ai import (
    CharacterBioRequest,
    CharacterBioResponse,
    PostSuggestionRequest,
    PostSuggestionResponse,
    SceneSummaryRequest,
    SceneSummaryResponse,
    SceneRequest,
    SceneResponse,
)
from app.services.ai import get_ai_client

router = APIRouter()


def check_ai_enabled():
    """Dependency to check if AI features are enabled."""
    if not settings.AI_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI features are currently disabled"
        )


@router.post("/character-bio", response_model=CharacterBioResponse)
def generate_character_bio(
    request: CharacterBioRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(check_ai_enabled)
) -> CharacterBioResponse:
    """Generate AI character biography based on character details.

    This endpoint uses AI to create both a short and long biography
    for a character based on their name, species, role, era, and tags.
    """
    ai_client = get_ai_client()
    return ai_client.generate_character_bio(request)


@router.post("/posts/suggest", response_model=PostSuggestionResponse)
def suggest_post_reply(
    request: PostSuggestionRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(check_ai_enabled)
) -> PostSuggestionResponse:
    """Suggest an AI-generated reply for a character in a scene.

    This endpoint analyzes recent posts in a scene and suggests
    an appropriate in-character response. The suggestion is editable
    and should not be automatically posted.
    """
    ai_client = get_ai_client()
    return ai_client.suggest_post_reply(request)


@router.post("/scenes/summary", response_model=SceneSummaryResponse)
def summarize_scene(
    request: SceneSummaryRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(check_ai_enabled)
) -> SceneSummaryResponse:
    """Generate an AI summary of a scene's posts.

    This endpoint creates a concise summary of all posts in a scene,
    useful for quickly catching up on what has happened.
    """
    ai_client = get_ai_client()
    return ai_client.summarize_scene(request)


# Legacy endpoint - kept for backward compatibility
@router.post("/scene", response_model=SceneResponse)
def generate_scene(
    request: SceneRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(check_ai_enabled)
) -> SceneResponse:
    """Generate AI scene (legacy endpoint - kept for backward compatibility).

    Note: This is a legacy endpoint. New applications should use
    the /scenes/summary or /posts/suggest endpoints instead.
    """
    # Legacy implementation - create a simple scene based on the request
    characters_str = " and ".join(request.characters)
    mood = request.mood or "tense"
    setting = request.setting

    scene = (
        f"The {mood} atmosphere hung heavy in the {setting}. "
        f"{characters_str} found themselves at a pivotal moment. "
        f"The air crackled with unspoken words and possibilities. "
        f"What happens next will change everything..."
    )

    dialogue = (
        f'"{request.prompt}," one of them said, breaking the silence. '
        f"The words hung in the air between them, pregnant with meaning."
    )

    return SceneResponse(scene=scene, dialogue=dialogue)
