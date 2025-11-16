# Changelog

All notable changes to the OwlQuill project will be documented in this file.

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
