"""Base AI client interface for OwlQuill."""
from abc import ABC, abstractmethod
from typing import Optional

from app.schemas.ai import (
    CharacterBioRequest,
    CharacterBioResponse,
    PostSuggestionRequest,
    PostSuggestionResponse,
    SceneSummaryRequest,
    SceneSummaryResponse,
)


class AIClient(ABC):
    """Abstract base class for AI clients."""

    @abstractmethod
    def generate_character_bio(self, request: CharacterBioRequest) -> CharacterBioResponse:
        """Generate a character biography based on character details.

        Args:
            request: Character bio generation request with name, species, role, era, tags

        Returns:
            CharacterBioResponse with short_bio and long_bio
        """
        pass

    @abstractmethod
    def suggest_post_reply(self, request: PostSuggestionRequest) -> PostSuggestionResponse:
        """Suggest a reply for a character in a scene/realm.

        Args:
            request: Post suggestion request with scene context, character info, recent posts

        Returns:
            PostSuggestionResponse with suggested_text
        """
        pass

    @abstractmethod
    def summarize_scene(self, request: SceneSummaryRequest) -> SceneSummaryResponse:
        """Summarize a scene's posts for quick catch-up.

        Args:
            request: Scene summary request with realm name and posts

        Returns:
            SceneSummaryResponse with summary text
        """
        pass
