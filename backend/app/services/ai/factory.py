"""AI client factory for selecting the appropriate provider."""
from typing import Optional

from app.core.config import settings
from app.services.ai.base import AIClient
from app.services.ai.fake import FakeAIProvider
from app.services.ai.openai_provider import OpenAIProvider


_ai_client_instance: Optional[AIClient] = None


def get_ai_client() -> AIClient:
    """Get the configured AI client instance.

    This function returns a singleton AI client based on the application settings.
    The client is determined by the AI_PROVIDER setting:

    - "fake" (default): Returns FakeAIProvider for development/testing
    - "openai": Returns OpenAIProvider if API key is configured

    If AI_PROVIDER is set to a real provider but no API key is configured,
    it falls back to FakeAIProvider with a warning.

    Returns:
        AIClient instance (singleton)
    """
    global _ai_client_instance

    if _ai_client_instance is not None:
        return _ai_client_instance

    provider = settings.AI_PROVIDER.lower()

    if provider == "fake":
        _ai_client_instance = FakeAIProvider()
        return _ai_client_instance

    if provider == "openai":
        if not settings.AI_API_KEY:
            print(
                "WARNING: AI_PROVIDER is set to 'openai' but no AI_API_KEY is configured. "
                "Falling back to FakeAIProvider. Set AI_API_KEY in your .env file."
            )
            _ai_client_instance = FakeAIProvider()
            return _ai_client_instance

        try:
            _ai_client_instance = OpenAIProvider(
                api_key=settings.AI_API_KEY,
                model=getattr(settings, "OPENAI_MODEL", "gpt-4")
            )
            return _ai_client_instance
        except Exception as e:
            print(
                f"WARNING: Failed to initialize OpenAI provider: {e}. "
                f"Falling back to FakeAIProvider."
            )
            _ai_client_instance = FakeAIProvider()
            return _ai_client_instance

    # Unknown provider - fall back to fake
    print(
        f"WARNING: Unknown AI_PROVIDER '{provider}'. "
        f"Supported: fake, openai. Falling back to FakeAIProvider."
    )
    _ai_client_instance = FakeAIProvider()
    return _ai_client_instance


def reset_ai_client() -> None:
    """Reset the AI client singleton.

    This is primarily useful for testing to reset the client between tests.
    """
    global _ai_client_instance
    _ai_client_instance = None
