# Changelog

All notable changes to the OwlQuill project will be documented in this file.

## [Phase 7] - 2025-11-17 - Profiles, Discovery & Mobile Readiness

### Added

#### Backend
- **Profile API**
  - New `/profile/users/{username}` endpoint for public user profiles
  - New `/profile/me` endpoint for current user's own profile
  - New `/profile/characters/{character_id}` endpoint for character profiles
  - Profile responses include stats (posts, realms, followers/following)
  - Profile responses include recent posts with full context (realm, character, author)

- **Discovery & Search**
  - New `/discovery/search` endpoint with universal search
  - Search supports filtering by type: all, user, character, realm
  - Case-insensitive ILIKE pattern matching across names and descriptions
  - Configurable result limits (1-50 results)
  - Discriminated union response types for different result categories

- **Analytics Events**
  - New `AnalyticsEvent` model for tracking user interactions
  - New `/analytics/events` endpoint for logging events
  - Whitelisted event types: profile_view, character_view, realm_view, post_view, search
  - Events support optional JSON payload for context
  - Non-authenticated event logging supported (user_id is nullable)

- **Database Migration**
  - Created Alembic migration `a1b2c3d4e5f6` for analytics_events table
  - Table includes indexed event_type and created_at columns for efficient querying

- **New Schemas**
  - `profile.py` schemas: UserProfile, CharacterProfile, PostSummary, etc.
  - `discovery.py` schemas: SearchResponse, UserSearchResult, CharacterSearchResult, RealmSearchResult
  - `analytics.py` schemas: AnalyticsEventCreate, AnalyticsEvent

- **Tests**
  - `test_profile.py`: User and character profile endpoint tests
  - `test_discovery.py`: Search and discovery tests across all resource types
  - `test_analytics.py`: Analytics event logging tests

#### Frontend
- **User Profile Pages** (`/u/:username`)
  - Display user avatar, display name, username, bio
  - Show stats: posts, realms joined, followers, following
  - Recent posts section with post cards
  - Responsive layout for mobile and desktop
  - Analytics event logging on page view

- **Character Profile Pages** (`/c/:characterId`)
  - Full character sheet with all attributes (species, role, era, age)
  - Short and long bio sections
  - Tags display with styled pills
  - Owner information with link to user profile
  - Character stats: posts count, realms count
  - Recent posts by character
  - Respects character privacy settings
  - Responsive mobile-friendly layout
  - Analytics event logging on page view

- **Discover Page** (`/discover`)
  - Universal search bar with query input
  - Filter pills for all/user/character/realm
  - Result cards with type-specific styling (purple for users, pink for characters, blue for realms)
  - Quick navigation to full profiles from results
  - Empty state messaging
  - Search analytics event logging
  - Fully responsive design

- **Navigation Enhancement**
  - Added "Discover" link to main navigation
  - Navigation now horizontally scrolls on mobile
  - Vertical sidebar layout maintained on desktop

- **Mobile Responsiveness**
  - Layout component updated with responsive flex direction (column on mobile, row on desktop)
  - All new pages use responsive padding (`p-4 md:p-8`)
  - Profile pages stack elements vertically on small screens
  - Typography adjusts with responsive text sizes
  - Touch-friendly button and link sizes

- **API Client Extensions**
  - New `getUserProfile(username)` method
  - New `getCurrentUserProfile()` method
  - New `getCharacterProfile(characterId)` method
  - New `search({ q, type, limit })` method
  - New `logEvent(eventType, payload)` method with silent failure handling

- **TypeScript Types**
  - Added Profile types: UserProfile, CharacterProfile, PostSummary, etc.
  - Added Discovery types: SearchResponse, SearchResult, UserSearchResult, etc.
  - Added Analytics types: AnalyticsEventCreate

### Changed
- Layout component now responsive with mobile-first design
- Navigation items now include whitespace-nowrap for better mobile UX
- User info section in nav hidden on mobile for cleaner layout

### Technical Improvements
- All profile and discovery endpoints use proper eager loading with `joinedload` to avoid N+1 queries
- Optional authentication support added with `get_current_user_optional` dependency
- Analytics events fail gracefully with console.debug() instead of breaking UI
- Search results limited and paginated to prevent performance issues

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
