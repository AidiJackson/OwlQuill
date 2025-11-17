"""OpenAI provider for AI features (stub implementation)."""
from typing import Optional

from app.schemas.ai import (
    CharacterBioRequest,
    CharacterBioResponse,
    PostSuggestionRequest,
    PostSuggestionResponse,
    SceneSummaryRequest,
    SceneSummaryResponse,
)
from app.services.ai.base import AIClient


class OpenAIProvider(AIClient):
    """OpenAI provider for real AI functionality.

    This is a stub implementation. To fully implement:
    1. Install openai package: pip install openai
    2. Implement the methods below using openai.ChatCompletion.create()
    3. Handle errors, rate limits, and retries appropriately

    For now, this raises NotImplementedError to encourage using FakeAIProvider
    or completing the implementation when ready.
    """

    def __init__(self, api_key: str, model: str = "gpt-4"):
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
            model: Model to use (default: gpt-4)
        """
        self.api_key = api_key
        self.model = model
        # Uncomment when ready to implement:
        # import openai
        # self.client = openai.OpenAI(api_key=api_key)

    def generate_character_bio(self, request: CharacterBioRequest) -> CharacterBioResponse:
        """Generate character bio using OpenAI.

        TODO: Implement using OpenAI API.
        """
        raise NotImplementedError(
            "OpenAI provider is not fully implemented. "
            "Use AI_PROVIDER=fake or implement this method."
        )

    def suggest_post_reply(self, request: PostSuggestionRequest) -> PostSuggestionResponse:
        """Suggest post reply using OpenAI.

        TODO: Implement using OpenAI API.
        """
        raise NotImplementedError(
            "OpenAI provider is not fully implemented. "
            "Use AI_PROVIDER=fake or implement this method."
        )

    def summarize_scene(self, request: SceneSummaryRequest) -> SceneSummaryResponse:
        """Summarize scene using OpenAI.

        TODO: Implement using OpenAI API.
        """
        raise NotImplementedError(
            "OpenAI provider is not fully implemented. "
            "Use AI_PROVIDER=fake or implement this method."
        )


# Example implementation for generate_character_bio (commented out):
"""
def generate_character_bio(self, request: CharacterBioRequest) -> CharacterBioResponse:
    prompt = f'''Generate a character biography for a role-play character with these details:

    Name: {request.name}
    Species: {request.species or "not specified"}
    Role: {request.role or "not specified"}
    Era: {request.era or "not specified"}
    Tags: {", ".join(request.tags) if request.tags else "none"}

    Please provide:
    1. A short bio (2-3 sentences) suitable for character cards
    2. A long bio (3-4 paragraphs) with depth, backstory, and personality

    Format as JSON: {{"short_bio": "...", "long_bio": "..."}}
    '''

    response = self.client.chat.completions.create(
        model=self.model,
        messages=[
            {"role": "system", "content": "You are a creative writer helping to develop role-play characters."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
    )

    result = json.loads(response.choices[0].message.content)
    return CharacterBioResponse(
        short_bio=result["short_bio"],
        long_bio=result["long_bio"]
    )
"""
