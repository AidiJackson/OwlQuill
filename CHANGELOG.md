# Changelog

All notable changes to the OwlQuill project will be documented in this file.

## [Phase 8] - 2025-11-17 - AI Layer (Foundations)

### Added

#### Backend
- **AI Abstraction Layer**
  - Created `AIClient` abstract base class in `app/services/ai/base.py`
  - Implemented `FakeAIProvider` for local development with deterministic responses
  - Added `OpenAIProvider` stub for future real AI integration
  - Created AI provider factory pattern in `app/services/ai/factory.py`
  - Singleton AI client management with `get_ai_client()` and `reset_ai_client()`

- **AI Endpoints**
  - Enhanced `/api/ai/character-bio` with new abstraction layer
  - New `/api/ai/posts/suggest` for AI-powered post reply suggestions
  - New `/api/ai/scenes/summary` for scene summarization
  - Legacy `/api/ai/scene` endpoint maintained for backward compatibility
  - All endpoints check `AI_ENABLED` flag and return HTTP 503 when disabled

- **Configuration**
  - Added `AI_ENABLED` boolean setting (default: true)
  - Added `OPENAI_MODEL` setting for OpenAI model selection (default: gpt-4)
  - Enhanced `AI_PROVIDER` with better typing and validation
  - Comprehensive environment variable support via Pydantic Settings

- **Schemas**
  - Created `PostSuggestionRequest` and `PostSuggestionResponse` schemas
  - Created `SceneSummaryRequest` and `SceneSummaryResponse` schemas
  - Enhanced existing character bio schemas with better documentation
  - All schemas use Pydantic Field with descriptions

- **Tests**
  - Created comprehensive test suite in `tests/test_ai.py`
  - Tests for character bio generation (full, minimal, unauthorized)
  - Tests for post suggestions and scene summaries
  - Test for AI disabled state (503 responses)
  - AI client reset fixture for test isolation

#### Frontend
- **API Client Enhancements**
  - Added `suggestPostReply(data)` method to API client
  - Added `summarizeScene(data)` method to API client
  - Consistent error handling and TypeScript types for all AI methods

- **Realm Detail Page AI Features**
  - "✨ AI Suggest Reply" button in post composer
  - Integrates realm name, character, and recent posts for context
  - AI suggestions populate content field for user editing
  - "✨ AI Summarize Scene" button above posts list
  - Scene summary displayed in dismissible panel
  - Loading states and error handling for all AI features

- **Character Creation AI Enhancement**
  - Existing "✨ AI Suggest Bio" feature maintained and enhanced
  - Updated to use new backend abstraction layer
  - Better error handling and user feedback

#### Documentation
- **Comprehensive Phase 8 Docs** (`docs/PHASE_8_AI_LAYER.md`)
  - Complete architecture overview
  - API endpoint documentation with examples
  - Configuration guide with environment variables
  - Usage guide for development and production
  - Testing instructions
  - Future enhancement roadmap
  - Troubleshooting guide
  - Security considerations

- **AI Services README** (`backend/app/services/ai/README.md`)
  - Quick start guide for developers
  - Provider configuration instructions
  - Guide for adding new providers
  - Guide for adding new AI methods
  - Best practices and troubleshooting

### Changed
- Migrated from monolithic `ai_service.py` to modular AI services architecture
- AI features now fail gracefully when disabled or unavailable
- Enhanced error messages with actionable guidance
- Improved type safety across AI-related code

### Technical Details
- Provider abstraction allows easy swapping between AI backends
- FakeAIProvider requires no external dependencies or API keys
- All AI features work without real AI configured (development-friendly)
- Clean separation between AI interface, implementation, and routing
- Dependency injection pattern for AI client in FastAPI routes
- Comprehensive error handling prevents AI issues from breaking core features

### Security & Privacy
- No API keys hard-coded anywhere in codebase
- All credentials configured via environment variables
- AI features opt-in via user clicks (no automatic AI use)
- No new data storage for AI interactions (Phase 8)
- Clear labeling of AI-generated content with ✨ emoji

### Future (Phase 9+)
- Implement OpenAI provider methods
- Add Anthropic Claude provider
- DM conversation summarization
- AI NPCs and auto-responses
- Collaborative scene planning
- Content moderation tools
- User preference for AI on/off
- Rate limiting and cost tracking

## [Phase 2] - 2025-11-16 - Playable Social MVP

### Added

#### Backend
- **Character Enhancements**
  - Added `role` field to Character model for character roles (e.g., "assassin", "healer")
  - Added `era` field to Character model for time periods (e.g., "modern", "medieval")
  - Added `portrait_url` field to Character model for character portrait images

- **Realm Enhancements**
  - Added `tagline` field to Realm model for short catchy descriptions
  - Added `banner_url` field to Realm model for header/banner images

- **Feed System**
  - New `/posts/feed` endpoint that returns posts from realms the user is a member of
  - Feed is sorted by creation date (newest first)
  - Supports pagination with `skip` and `limit` parameters

- **AI Service Enhancement**
  - Enhanced AI stub to generate richer character bios using role and era fields
  - Bio generation now incorporates character's role and era for more contextual descriptions

- **Database Migration**
  - Created Alembic migration `8b18cfce864f` to add Phase 2 fields to database
  - Migration safely adds nullable columns to existing tables

#### Frontend
- **Profile Page**
  - User avatar display with circular avatar component
  - Avatar preview in edit mode
  - Fallback to user initials when no avatar is set
  - Improved profile layout with avatar header section

- **Character Creation**
  - Added Role and Era input fields in creation form
  - Added Portrait URL input field
  - Enhanced AI bio generation to include role and era
  - Updated character display cards to show portraits
  - Character cards now display "species • role • era" subtitle
  - Image error handling with fallback display

- **Realms**
  - Added Tagline and Banner URL fields to realm creation form
  - Realm cards now display banner images with gradient fallback
  - Tagline displayed in italic with accent color
  - Realm detail page with full realm information
  - Ability to create posts directly from realm detail page
  - Post type selection (IC/OOC/Narration) in post composer

- **Home Feed**
  - Replaced manual post loading with `/feed` endpoint
  - Added post type badges (IC/OOC/NARRATION) with color coding
  - Display character name and realm name for each post
  - Improved post metadata display

- **Routing**
  - Added `/realms/:realmId` route for realm detail pages
  - Realm cards in listing page now link to detail pages

- **TypeScript**
  - Created `vite-env.d.ts` for proper Vite environment types
  - Fixed TypeScript compilation errors in API client

### Changed
- Updated Character schema to include role, era, and portrait_url
- Updated Realm schema to include tagline and banner_url
- Enhanced AI character bio request schema to accept role and era
- Updated frontend types to match new backend schemas
- Improved error handling for image loading across all components

### Technical Details
- All new fields are nullable/optional to maintain backward compatibility
- Database migration can be run on existing data without issues
- Frontend build process now properly handles Vite environment variables
- API client uses proper TypeScript types for headers

## [Phase 1] - Initial MVP Scaffold

### Added
- User authentication system with JWT
- Character creation and management
- Realm creation and joining
- Post creation with IC/OOC/Narration types
- Comment and reaction systems
- AI stub service for bio generation
- Full-stack setup with FastAPI backend and React frontend
- Database models and migrations with Alembic
- RESTful API with Swagger documentation
- React Router navigation
- Tailwind CSS styling
- Zustand state management
