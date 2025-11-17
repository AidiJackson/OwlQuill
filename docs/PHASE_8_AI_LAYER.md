# Phase 8: AI Layer (Foundations)

## Overview

Phase 8 adds foundational AI capabilities to OwlQuill, enabling AI-assisted content generation for character bios, post suggestions, and scene summaries. The implementation prioritizes flexibility, safety, and user control.

### Key Principles

- **AI-assist, not AI-takeover**: AI suggests and drafts content, but users remain in full control
- **Fail-safe design**: The app functions perfectly without AI or when AI is disabled
- **Provider abstraction**: Easy to swap between fake, OpenAI, Anthropic, or other providers
- **No hard-coded credentials**: All API keys are configured via environment variables
- **Privacy-conscious**: AI features don't create new data storage beyond existing models

## Architecture

### Backend Components

```
backend/app/services/ai/
├── base.py              # AIClient abstract base class
├── fake.py              # FakeAIProvider (default, deterministic responses)
├── openai_provider.py   # OpenAIProvider (stub for real AI)
└── factory.py           # Provider factory and dependency injection
```

**AIClient Interface** (`base.py`)
- `generate_character_bio(request)` - Generate character biography
- `suggest_post_reply(request)` - Suggest in-character post replies
- `summarize_scene(request)` - Summarize scene posts for catch-up

**FakeAIProvider** (`fake.py`)
- Default provider for local development and testing
- Returns deterministic, realistic placeholder responses
- No external API calls, no dependencies
- Clearly marked with `[FAKE_AI_*]` prefixes for transparency

**OpenAIProvider** (`openai_provider.py`)
- Stub implementation for real AI integration
- Currently raises `NotImplementedError` with helpful messages
- Framework ready for OpenAI API integration (commented example included)
- Falls back to FakeAIProvider if API key is missing

**Factory Pattern** (`factory.py`)
- `get_ai_client()` - Returns singleton AI client based on config
- Handles provider selection, fallback logic, and error recovery
- `reset_ai_client()` - Test utility for resetting singleton

### API Endpoints

All endpoints require authentication and respect the `AI_ENABLED` flag.

**POST `/api/ai/character-bio`**
```json
Request:
{
  "name": "Aria Shadowheart",
  "species": "vampire",
  "role": "assassin",
  "era": "Victorian",
  "tags": ["gothic", "mysterious", "dangerous"]
}

Response:
{
  "short_bio": "2-3 sentence summary...",
  "long_bio": "3-4 paragraph detailed biography..."
}
```

**POST `/api/ai/posts/suggest`**
```json
Request:
{
  "realm_name": "Dark Castle",
  "character_name": "Aria",
  "recent_posts": ["post 1 content", "post 2 content"],
  "tone_hint": "dramatic"
}

Response:
{
  "suggested_text": "AI-generated post suggestion..."
}
```

**POST `/api/ai/scenes/summary`**
```json
Request:
{
  "realm_name": "Dark Castle",
  "posts": ["post 1", "post 2", "..."]
}

Response:
{
  "summary": "Concise scene summary..."
}
```

**POST `/api/ai/scene`** (Legacy)
- Kept for backward compatibility
- New code should use `/posts/suggest` or `/scenes/summary`

### Frontend Integration

**API Client** (`frontend/src/lib/apiClient.ts`)
- `generateCharacterBio(...)` - Generate character bio
- `suggestPostReply(data)` - Get AI post suggestion
- `summarizeScene(data)` - Get AI scene summary
- Consistent error handling across all AI methods

**UI Components**

1. **Character Creation** (`Characters.tsx`)
   - "✨ AI Suggest Bio" button
   - Populates bio fields without auto-submitting
   - Shows loading state during generation

2. **Realm Detail - Post Composer** (`RealmDetail.tsx`)
   - "✨ AI Suggest Reply" button in post form
   - Uses realm context, character, and recent posts
   - Inserts suggestion into editable textarea

3. **Realm Detail - Scene Summary** (`RealmDetail.tsx`)
   - "✨ AI Summarize Scene" button above posts
   - Displays summary in dismissible panel
   - Only shown when posts exist

## Configuration

### Backend Environment Variables

```bash
# Master switch for AI features
AI_ENABLED=true                    # Default: true

# Provider selection
AI_PROVIDER=fake                   # Options: fake, openai, anthropic
                                   # Default: fake

# API credentials (only needed for real providers)
AI_API_KEY=sk-...                  # Your AI provider API key
OPENAI_MODEL=gpt-4                 # Model to use (OpenAI specific)
                                   # Default: gpt-4
```

### Frontend Environment Variables

```bash
# API base URL (typically handled by Vite proxy)
VITE_API_BASE_URL=/api             # Default: /api
```

### .env Example

```bash
# backend/.env
AI_ENABLED=true
AI_PROVIDER=fake
# AI_API_KEY=sk-your-key-here      # Uncomment when using real provider
# OPENAI_MODEL=gpt-4               # Uncomment to override default
```

## Usage Guide

### Local Development

1. **Default Setup (Fake AI)**
   ```bash
   # No configuration needed - FakeAIProvider is default
   cd backend && uvicorn app.main:app --reload
   cd frontend && npm run dev
   ```

2. **Test AI Features**
   - Create a character → click "AI Suggest Bio"
   - Visit a realm → create post → click "AI Suggest Reply"
   - View posts → click "AI Summarize Scene"

### Using Real AI (OpenAI)

1. **Install OpenAI SDK** (when implementing)
   ```bash
   cd backend
   pip install openai
   ```

2. **Configure Environment**
   ```bash
   # backend/.env
   AI_ENABLED=true
   AI_PROVIDER=openai
   AI_API_KEY=sk-your-openai-key
   OPENAI_MODEL=gpt-4
   ```

3. **Implement OpenAI Methods**
   - See `backend/app/services/ai/openai_provider.py`
   - Uncommented example implementation is provided
   - Follow the pattern for character bio, extend to other methods

### Disabling AI

**Completely Disable**
```bash
# backend/.env
AI_ENABLED=false
```
- All AI endpoints return HTTP 503
- UI shows friendly error messages
- Core functionality unaffected

**Use Fake Provider Only**
```bash
# backend/.env
AI_ENABLED=true
AI_PROVIDER=fake
```
- AI features work with deterministic responses
- No external API calls
- Useful for demos and testing

## Testing

### Backend Tests

```bash
cd backend
pytest tests/test_ai.py -v
```

**Test Coverage**
- Character bio generation (full data, minimal data, unauthorized)
- Post suggestion (full context, minimal context)
- Scene summary (with posts, empty scene)
- Legacy scene generation endpoint
- AI disabled state (503 response)
- All tests use FakeAIProvider for speed and reliability

### Frontend Build

```bash
cd frontend
npm run build
```
- TypeScript compilation check
- Ensures all AI types are correct
- Verifies no unused imports or errors

## Feature Behavior

### Character Bio Generation

**What It Does:**
- Takes character details (name, species, role, era, tags)
- Generates short bio (2-3 sentences) for character cards
- Generates long bio (3-4 paragraphs) with depth and backstory

**User Flow:**
1. User fills in character name and optional details
2. Clicks "✨ AI Suggest Bio"
3. Bio fields populate with AI-generated text
4. User can edit freely before creating character
5. If AI fails, user writes bio manually (no blocking)

### Post Reply Suggestion

**What It Does:**
- Analyzes recent posts in the scene
- Considers character name and realm context
- Respects tone hints (IC/OOC/narration)
- Generates contextually appropriate reply

**User Flow:**
1. User opens post creation form in a realm
2. Selects character (optional) and post type
3. Clicks "✨ AI Suggest Reply"
4. Content field fills with suggestion
5. User edits and posts when ready
6. If AI fails, user writes manually

### Scene Summary

**What It Does:**
- Reads all posts in a scene
- Generates concise summary of events
- Highlights key themes, developments, and character dynamics

**User Flow:**
1. User viewing realm with posts
2. Clicks "✨ AI Summarize Scene"
3. Summary appears in dismissible panel
4. User can read, copy, or dismiss
5. If AI fails, user reads posts manually

## Error Handling

**AI Service Unavailable (503)**
- Backend: Check `AI_ENABLED` flag
- Frontend: Shows alert "AI features are currently disabled"
- User can continue without AI

**Provider Error**
- Backend: Falls back to FakeAIProvider with console warning
- Frontend: Receives response (may be fake data)
- Logged for debugging

**Network/API Error**
- Frontend: Catches exception, shows friendly message
- User workflow uninterrupted
- Can retry or proceed manually

## Future Enhancements (Phase 9+)

### Short-term
1. **Additional Providers**
   - Anthropic Claude integration
   - Azure OpenAI support
   - Local LLM options (Ollama, etc.)

2. **Enhanced Context**
   - Include character profiles in suggestions
   - Use realm lore and rules
   - Remember conversation history

3. **DM Summarization**
   - Once DM system exists (Phase 7+)
   - Summarize private conversations
   - Catch up on long threads

### Medium-term
4. **AI NPCs**
   - AI-controlled characters for solo play
   - Automated responses in quiet scenes
   - DM assistance tools

5. **Collaborative Planning**
   - Scene planning suggestions
   - Plot arc development
   - Character arc suggestions

6. **Content Moderation**
   - AI-assisted content flagging
   - Tone analysis and warnings
   - Safety tools for community management

### Long-term
7. **Personalization**
   - Learn user writing style
   - Character voice consistency
   - Adaptive suggestions

8. **Analytics**
   - Scene engagement metrics
   - Character development tracking
   - Realm health insights

9. **Multi-modal AI**
   - Image generation for characters/scenes
   - Voice synthesis for dramatic readings
   - Music/ambiance suggestions

## Troubleshooting

### "AI features are currently disabled"
- Check `AI_ENABLED=true` in backend `.env`
- Restart backend server after config changes

### "Failed to get AI suggestion"
- Verify `AI_PROVIDER` is set correctly
- If using OpenAI, check `AI_API_KEY` is valid
- Check backend logs for detailed errors
- Try falling back to `AI_PROVIDER=fake`

### Backend won't start
- Ensure all dependencies installed: `pip install -r requirements.txt`
- Check for syntax errors in AI service files
- Verify `.env` file format (no extra quotes)

### Frontend TypeScript errors
- Run `npm install` in frontend directory
- Check all imports are correct
- Verify API client types match backend schemas

### Tests failing
- Install test dependencies: `pip install pytest httpx`
- Reset AI client between tests (automatic with fixture)
- Check database is writable for test.db

## Security Considerations

### API Key Safety
- ✅ Never commit `.env` files to git
- ✅ Use `.env.example` for templates only
- ✅ Rotate keys if accidentally exposed
- ✅ Use separate keys for dev/prod environments

### User Privacy
- ✅ AI requests include only necessary context
- ✅ No persistent logs of AI interactions (Phase 8)
- ✅ Users control what data is sent (opt-in via clicking)
- ✅ Future: Add user preference for AI features on/off

### Rate Limiting
- ⚠️ Phase 8: No rate limiting implemented
- 🔜 Phase 9: Add per-user rate limits
- 🔜 Phase 9: Implement caching for common requests
- 🔜 Phase 9: Add cost tracking for real AI providers

## Support and Feedback

For issues or questions about Phase 8 AI features:
1. Check this documentation first
2. Review error messages in browser console and backend logs
3. Try with `AI_PROVIDER=fake` to isolate provider issues
4. Create GitHub issue with:
   - Steps to reproduce
   - Error messages
   - Environment config (sanitized, no API keys!)

---

**Phase 8 Complete** ✓
- Backend AI abstraction layer
- Three AI endpoints (bio, suggestion, summary)
- Frontend UI integration
- Comprehensive tests
- Full documentation

**Next: Phase 9** - AI Enhancements & Additional Providers
