# OwlQuill MVP Scope

This document outlines what has been implemented in the OwlQuill MVP (Phase 1) and what is planned for future releases.

## Implemented in MVP (Phase 1)

### Backend Domain Models

#### 1. User
- ✅ Email-based authentication
- ✅ Unique username/handle (e.g., @moonquill)
- ✅ Password hashing with bcrypt
- ✅ Profile fields: display_name, bio, avatar_url
- ✅ Timestamps (created_at, updated_at)

#### 2. Character
- ✅ Character creation and management
- ✅ Fields: name, alias, age, species
- ✅ Bios: short_bio, long_bio
- ✅ Tags (stored as comma-separated)
- ✅ Visibility levels: public, friends, private
- ✅ Avatar URL support
- ✅ Owner relationship to User

#### 3. Realm (RP Groups/Worlds)
- ✅ Realm creation with unique slug
- ✅ Description and genre categorization
- ✅ Public/private visibility
- ✅ Owner relationship
- ✅ Membership management

#### 4. RealmMembership
- ✅ User-to-Realm relationships
- ✅ Role-based access: owner, admin, member
- ✅ Join/leave functionality

#### 5. Post (Story Snippets/Scenes)
- ✅ Create posts within realms
- ✅ Optional title
- ✅ Rich text content
- ✅ Content types: IC (in-character), OOC (out-of-character), narration
- ✅ Character attribution
- ✅ Author tracking

#### 6. Comment
- ✅ Comment on posts
- ✅ Optional character attribution
- ✅ Threaded discussions

#### 7. Reaction
- ✅ React to posts with different types (like, heart, star, etc.)
- ✅ One reaction per user per post per type

#### 8. Notification (Stub)
- ✅ Basic structure implemented
- ✅ Types: new_comment, new_post_in_realm
- ✅ Read/unread status
- ⚠️ Not actively used in UI yet

### Backend API Endpoints

#### Authentication (`/auth`)
- ✅ `POST /auth/register` - Create new user account
- ✅ `POST /auth/login` - Login with email/password, receive JWT
- ✅ `GET /auth/me` - Get current authenticated user

#### Users (`/users`)
- ✅ `GET /users/me` - Get current user profile
- ✅ `PATCH /users/me` - Update display name, bio, avatar

#### Characters (`/characters`)
- ✅ `POST /characters/` - Create new character
- ✅ `GET /characters/` - List user's characters
- ✅ `GET /characters/{id}` - Get specific character
- ✅ `PATCH /characters/{id}` - Update character
- ✅ `DELETE /characters/{id}` - Delete character

#### Realms (`/realms`)
- ✅ `POST /realms/` - Create new realm
- ✅ `GET /realms/` - List realms (with search and filters)
- ✅ `GET /realms/{id}` - Get realm details
- ✅ `POST /realms/{id}/join` - Join a public realm
- ✅ `GET /realms/{id}/members` - List realm members

#### Posts (`/posts`)
- ✅ `POST /posts/realms/{realm_id}/posts` - Create post in realm
- ✅ `GET /posts/realms/{realm_id}/posts` - List posts (paginated)
- ✅ `GET /posts/{id}` - Get single post
- ✅ `DELETE /posts/{id}` - Delete post (author only)

#### Comments (`/comments`)
- ✅ `POST /comments/posts/{post_id}/comments` - Add comment
- ✅ `GET /comments/posts/{post_id}/comments` - List comments

#### Reactions (`/reactions`)
- ✅ `POST /reactions/posts/{post_id}/reactions` - Add reaction
- ✅ `DELETE /reactions/{id}` - Remove reaction

#### AI Helpers (`/ai`)
- ✅ `POST /ai/character-bio` - Generate character bio (fake/stub)
- ✅ `POST /ai/scene` - Generate scene snippet (fake/stub)
- ⚠️ Uses FakeAIClient, not connected to real AI APIs

#### Health
- ✅ `GET /health` - Health check endpoint
- ✅ `GET /` - Root endpoint with API info

### Backend Infrastructure
- ✅ FastAPI application with CORS configuration
- ✅ SQLAlchemy 2.x models with relationships
- ✅ Pydantic v2 schemas for validation
- ✅ Alembic migrations setup
- ✅ JWT-based authentication with secure password hashing
- ✅ Database session management
- ✅ SQLite support (dev) with PostgreSQL-ready configuration
- ✅ Modular router structure
- ✅ Environment-based configuration
- ✅ Basic pytest test suite

### Frontend Pages

#### Authentication
- ✅ Login page with email/password
- ✅ Registration page
- ✅ Automatic redirect when authenticated
- ✅ JWT storage in localStorage

#### Main Application Layout
- ✅ Sidebar navigation
- ✅ Protected routes
- ✅ User info display
- ✅ Logout functionality

#### Home Feed (`/`)
- ✅ Display recent posts from joined realms
- ✅ Post cards with content and metadata
- ✅ Empty state for new users

#### Realms (`/realms`)
- ✅ List all public realms
- ✅ Create new realm form
- ✅ Join realm functionality
- ✅ Realm cards with genre tags

#### Characters (`/characters`)
- ✅ List user's characters
- ✅ Create character form
- ✅ AI bio generation button
- ✅ Character cards with tags
- ✅ Species and bio display

#### Profile (`/me`)
- ✅ View user profile
- ✅ Edit display name, bio, avatar URL
- ✅ Save/cancel functionality

### Frontend Infrastructure
- ✅ React 18 with TypeScript
- ✅ Vite for fast development
- ✅ Tailwind CSS with custom theme
- ✅ Zustand for auth state management
- ✅ React Router for navigation
- ✅ Typed API client with fetch
- ✅ Token-based authentication
- ✅ Protected route wrapper
- ✅ Custom form components
- ✅ Dark theme (owl/purple accent colors)

### Development Tools
- ✅ Backend Makefile for common tasks
- ✅ Pytest configuration and test fixtures
- ✅ ESLint configuration
- ✅ Environment variable templates (.env.example)
- ✅ Clean project structure
- ✅ TypeScript strict mode

## Not Yet Implemented (Future Phases)

### Phase 2: Enhanced Features
- ⏳ Real AI integration (OpenAI, Anthropic)
- ⏳ Direct messaging between users
- ⏳ Active notification system
- ⏳ Image uploads for avatars and posts
- ⏳ Rich text editor for posts
- ⏳ Post editing
- ⏳ Realm moderation tools
- ⏳ Realm invite system for private realms
- ⏳ User blocking/reporting

### Phase 3: Discovery & Search
- ⏳ Advanced search (characters, realms, posts)
- ⏳ Tag-based discovery
- ⏳ Trending realms/posts
- ⏳ User recommendations
- ⏳ Character showcases

### Phase 4: Social Features
- ⏳ User following system
- ⏳ Activity feed
- ⏳ Mentions and tags
- ⏳ Share posts to other realms
- ⏳ Bookmarks/saved posts
- ⏳ Like counts and engagement metrics

### Phase 5: Advanced RP Tools
- ⏳ Dice rolling for tabletop RP
- ⏳ Character sheets/stats
- ⏳ Timelines and lore wikis
- ⏳ Session planning tools
- ⏳ World-building templates
- ⏳ Character relationship maps

### Phase 6: Content & Media
- ⏳ Audio/video support for posts
- ⏳ Gallery/portfolio mode
- ⏳ Story collections/anthologies
- ⏳ Export stories to PDF/ePub
- ⏳ Collaboration tools

### Phase 7: Platform
- ⏳ Mobile app (React Native or native)
- ⏳ Desktop app (Electron)
- ⏳ Browser extensions
- ⏳ API webhooks
- ⏳ Third-party integrations

### Phase 8: Monetization
- ⏳ Premium memberships
- ⏳ Realm subscriptions
- ⏳ Commission marketplace
- ⏳ Tipping/support for creators
- ⏳ Ad-free options

## Known Limitations in MVP

1. **AI Features**: Use fake/stub responses, not real AI
2. **Notifications**: Structure exists but not actively displayed in UI
3. **Image Uploads**: Only URL references supported, no file uploads
4. **Realm Privacy**: Join only works for public realms
5. **Moderation**: No admin tools for content moderation
6. **Search**: Basic filtering only, no full-text search
7. **Pagination**: Backend supports it, frontend doesn't implement infinite scroll
8. **Real-time**: No WebSocket support for live updates
9. **Email**: No email verification or password reset
10. **Performance**: No caching, query optimization needed for scale

## Testing Coverage

### Backend Tests
- ✅ Authentication (register, login, get current user)
- ✅ Character creation and listing
- ⚠️ Realms (basic coverage)
- ⚠️ Posts (basic coverage)
- ⏳ Comments, reactions, AI endpoints (not tested)

### Frontend Tests
- ⏳ Unit tests not implemented
- ⏳ Integration tests not implemented
- ⏳ E2E tests not implemented

## Migration Path

To upgrade from MVP to future phases:

1. **Database**: Use Alembic migrations for schema changes
2. **API**: Add new endpoints without breaking existing ones
3. **Frontend**: Add new pages/components incrementally
4. **AI**: Replace FakeAIClient with real implementation
5. **Auth**: Add OAuth, email verification as enhancements

## Success Metrics for MVP

- ✅ User can register and login
- ✅ User can create characters
- ✅ User can create and join realms
- ✅ User can post in realms
- ✅ User can comment and react
- ✅ AI stub generates bio text
- ✅ All core pages are accessible
- ✅ Backend tests pass
- ✅ Frontend builds successfully

## Next Steps After MVP

1. Deploy to a staging environment
2. User testing and feedback collection
3. Prioritize Phase 2 features based on feedback
4. Implement real AI integration
5. Add image upload functionality
6. Build notification UI
7. Create mobile-responsive improvements
8. Performance optimization and caching

---

**MVP Status**: ✅ Complete and ready for development/testing
**Version**: 0.1.0
**Last Updated**: 2025-11-16
