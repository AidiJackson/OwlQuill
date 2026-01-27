# OwlQuill

## Overview

OwlQuill is a roleplay-first social network for creative storytellers and character enthusiasts. It functions as a "Facebook for role-players" where users create original characters (OCs), join themed roleplay worlds (Realms), and collaboratively write stories through in-character posts, comments, and reactions.

The application follows a standard full-stack architecture with a Python/FastAPI backend and React/TypeScript frontend, designed to run together in Replit with a unified development workflow.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Architecture

**Framework**: FastAPI with Python 3.11
- RESTful API design with automatic OpenAPI documentation at `/docs`
- Pydantic v2 for request/response validation and schemas
- JWT-based authentication using python-jose with bcrypt password hashing
- Rate limiting on auth endpoints via slowapi

**Database Layer**:
- SQLAlchemy 2.x ORM with declarative models
- Alembic for database migrations
- SQLite for development (configured via `DATABASE_URL` environment variable)
- PostgreSQL-ready (psycopg2-binary included in dependencies)

**Domain Models**:
- `User`: Authentication, profile (username, display_name, bio, avatar)
- `Character`: RP characters with name, species, role, era, bios, visibility settings
- `Realm`: Roleplay worlds/groups with slug, tagline, genre, banner
- `RealmMembership`: User-to-Realm relationships with roles (owner/admin/member)
- `Post`: Story content with content types (IC/OOC/narration), optional character attribution
- `Comment`: Threaded discussions on posts
- `Reaction`: Post reactions (like, heart, star)
- `Notification`: User notification system (stub)

**API Structure**:
- `/auth` - Register, login (supports JSON body)
- `/users` - Profile management (`/me` endpoint)
- `/characters` - CRUD for user's characters
- `/realms` - CRUD for realms, membership management
- `/posts` - Create posts in realms, feed endpoint
- `/comments` - Comment on posts
- `/reactions` - React to posts
- `/ai` - AI-powered bio and scene generation (stub implementation)

**AI Service**:
- Stubbed AI client generating template-based character bios and scenes
- Designed for future integration with OpenAI/Anthropic APIs
- Configuration via `AI_PROVIDER` environment variable

### Frontend Architecture

**Framework**: React 18 with TypeScript and Vite
- Path aliases configured (`@/` maps to `./src/`)
- Vite proxy configuration routes `/api` to backend at port 8000

**State Management**: Zustand for global auth state
- Handles user session, login/logout, token persistence in localStorage

**Styling**: Tailwind CSS with custom theme
- Custom `owl` color palette (purple/indigo brand colors)
- Dark mode by default (gray-950 background)
- Component classes defined in `index.css` (btn, card, input, textarea)

**Routing**: React Router v6
- Protected routes wrap authenticated pages
- Public routes: `/login`, `/register`
- Protected routes: `/` (Home/Feed), `/realms`, `/realms/:realmId`, `/characters`, `/profile`

**API Client**: Centralized fetch wrapper in `lib/apiClient.ts`
- Automatic token injection
- Error handling with JSON error extraction
- Type-safe methods matching backend endpoints

### Development Workflow

**Running the Application**:
- Backend runs on port 8000 (FastAPI/Uvicorn)
- Frontend runs on port 5173 (Vite dev server)
- Frontend proxies `/api` requests to backend
- Use Replit's Run button for unified startup

**Database Setup**:
- Run `alembic upgrade head` in backend directory for migrations
- SQLite database file created at `./owlquill.db`

**Testing**: pytest with httpx TestClient
- Test fixtures create isolated SQLite database per test
- Rate limiting disabled during tests

## External Dependencies

### Backend Dependencies
- **FastAPI/Uvicorn**: Web framework and ASGI server
- **SQLAlchemy/Alembic**: ORM and migrations
- **psycopg2-binary**: PostgreSQL adapter (for production)
- **python-jose**: JWT token handling
- **passlib[bcrypt]**: Password hashing
- **slowapi**: Rate limiting
- **redis**: Configured but not actively used (future async tasks)
- **pydantic-settings**: Environment configuration via `.env` file

### Frontend Dependencies
- **React/React-DOM**: UI framework
- **react-router-dom**: Client-side routing
- **zustand**: State management
- **Tailwind CSS/PostCSS/Autoprefixer**: Styling pipeline

### Environment Configuration
Key environment variables (set in `.env` or Replit Secrets):
- `DATABASE_URL`: Database connection string
- `SECRET_KEY`: JWT signing key (required in production)
- `DEBUG`: Enable debug mode (defaults to false)
- `BACKEND_CORS_ORIGINS`: Comma-separated allowed origins
- `AI_PROVIDER`: AI service selection (fake/openai/anthropic)
- `AI_API_KEY`: API key for AI service