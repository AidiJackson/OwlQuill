# OwlQuill AI Services

This directory contains the AI abstraction layer for OwlQuill's AI-powered features.

## Structure

- **`base.py`** - Abstract base class defining the AI client interface
- **`fake.py`** - Fake AI provider for development/testing (no external API calls)
- **`openai_provider.py`** - OpenAI provider stub (implement when ready for real AI)
- **`factory.py`** - Factory function for instantiating the correct AI provider

## Quick Start

### Using the AI Client

```python
from app.services.ai import get_ai_client
from app.schemas.ai import CharacterBioRequest

# Get the configured AI client
ai_client = get_ai_client()

# Generate a character bio
request = CharacterBioRequest(
    name="Aria Shadowheart",
    species="vampire",
    role="assassin",
    tags=["gothic", "mysterious"]
)
response = ai_client.generate_character_bio(request)
print(response.short_bio)
```

## Provider Configuration

Set via environment variables in `.env`:

```bash
AI_ENABLED=true              # Master switch
AI_PROVIDER=fake             # Options: fake, openai, anthropic
AI_API_KEY=sk-...            # Required for real providers
OPENAI_MODEL=gpt-4           # Optional, default: gpt-4
```

## Adding New Providers

1. **Create Provider Class**
   ```python
   # anthropic_provider.py
   from app.services.ai.base import AIClient

   class AnthropicProvider(AIClient):
       def __init__(self, api_key: str, model: str = "claude-3-opus"):
           self.api_key = api_key
           self.model = model

       def generate_character_bio(self, request):
           # Implement using Anthropic API
           pass
   ```

2. **Update Factory**
   ```python
   # factory.py
   from app.services.ai.anthropic_provider import AnthropicProvider

   def get_ai_client():
       if settings.AI_PROVIDER == "anthropic":
           return AnthropicProvider(settings.AI_API_KEY)
   ```

3. **Update Config**
   ```python
   # app/core/config.py
   AI_PROVIDER: Literal["fake", "openai", "anthropic"] = "fake"
   ```

## Adding New AI Methods

1. **Add to Base Class**
   ```python
   # base.py
   @abstractmethod
   def new_feature(self, request: NewFeatureRequest) -> NewFeatureResponse:
       pass
   ```

2. **Implement in All Providers**
   ```python
   # fake.py
   def new_feature(self, request: NewFeatureRequest) -> NewFeatureResponse:
       return NewFeatureResponse(result="[FAKE_AI] ...")

   # openai_provider.py
   def new_feature(self, request: NewFeatureRequest) -> NewFeatureResponse:
       # Implement or raise NotImplementedError
       pass
   ```

3. **Create Endpoint**
   ```python
   # app/api/routes/ai.py
   @router.post("/new-feature", response_model=NewFeatureResponse)
   def new_feature(request: NewFeatureRequest, ...):
       ai_client = get_ai_client()
       return ai_client.new_feature(request)
   ```

## Testing

```bash
# Run AI tests
pytest tests/test_ai.py -v

# Test with fake provider (default)
AI_PROVIDER=fake pytest tests/test_ai.py

# Reset AI client in tests
from app.services.ai.factory import reset_ai_client
reset_ai_client()  # Clears singleton
```

## Best Practices

### Error Handling
- Always provide fallback behavior
- Log errors but don't crash
- Return helpful error messages to users

### Provider Implementation
- Keep providers independent (no shared state)
- Handle API errors gracefully
- Respect rate limits
- Use retries for transient failures

### Security
- Never log API keys
- Validate all input before sending to AI
- Sanitize AI responses before returning
- Consider cost implications of each request

### Performance
- Cache common requests where appropriate
- Use async where possible (future enhancement)
- Monitor API usage and costs
- Implement timeouts

## Troubleshooting

**Provider not found error**
- Check `AI_PROVIDER` matches a valid provider name
- Verify provider class is imported in factory

**API key not working**
- Ensure `AI_API_KEY` is set in `.env`
- Check key is valid and has correct permissions
- Verify no extra whitespace/quotes in `.env`

**Always getting fake responses**
- Check factory fallback logic
- Ensure provider is properly configured
- Review console warnings for fallback reasons

## Future Improvements

- [ ] Async support for AI calls
- [ ] Request caching layer
- [ ] Rate limiting per user
- [ ] Cost tracking and budgets
- [ ] A/B testing framework
- [ ] Response quality metrics
- [ ] Streaming responses for long content
