# OwlQuill

> A roleplay-first social network for creative storytellers and character enthusiasts

OwlQuill is a full-stack web application designed for role-players, fanfic writers, and creative communities. Think "Facebook for role-players" — a beautiful, premium platform where users create original characters, join immersive realms (RP groups), and collaboratively build ongoing storylines with AI-enhanced tools.

## Features

### Phase 2 - Playable Social MVP (Current)
- **User Profiles with Avatars**: Display and edit user avatars
- **Enhanced Characters**: Create RP sheets with role, era, and character portraits
- **Rich Realms**: Worlds with taglines, banners, and visual identity
- **Post Type System**: In-Character (IC), Out-of-Character (OOC), and Narration posting
- **Personalized Feed**: Home feed showing posts from your joined realms
- **Realm Detail Pages**: View realm info, browse posts, and create content in-world
- **Enhanced AI**: Character bio generation uses role and era for contextual descriptions

### Core Features
- **User Authentication**: Secure JWT-based registration and login
- **Character Creation**: Build detailed OC/RP characters with AI-assisted bio generation
- **Realms**: Create and join roleplay worlds/groups organized by genre and theme
- **In-Character Posting**: Share story snippets, scenes, and threads with post type badges
- **Community Interaction**: Comment, react, and build ongoing narratives with others
- **AI Assistance**: Generate character bios using name, species, role, era, and tags (stub implementation)

## Tech Stack

### Backend
- **Python 3.11** with **FastAPI**
- **PostgreSQL** / **SQLite** (dev) with **SQLAlchemy 2.x**
- **Alembic** for database migrations
- **JWT** authentication with secure password hashing
- **Pydantic v2** for data validation
- **pytest** for testing

### Frontend
- **React 18** with **TypeScript**
- **Vite** for fast development and building
- **Tailwind CSS** for styling
- **Zustand** for state management
- **React Router** for navigation

## Project Structure

```
OwlQuill/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # API endpoints
│   │   ├── core/             # Config, database, security
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── services/         # Business logic
│   │   └── main.py           # FastAPI app
│   ├── alembic/              # Database migrations
│   ├── tests/                # Backend tests
│   ├── requirements.txt
│   └── Makefile
├── frontend/
│   ├── src/
│   │   ├── components/       # React components
│   │   ├── pages/            # Page components
│   │   ├── lib/              # API client, store, types
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
└── docs/                     # Documentation
```

## Getting Started

> **🚀 Quick Start with Replit**: See [DEV_SETUP.md](./DEV_SETUP.md) for one-button setup in Replit!

### Prerequisites

- Python 3.11+
- Node.js 18+
- npm or yarn

### Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file (optional, defaults will work for development):
   ```bash
   cp .env.example .env
   ```

5. Run database migrations:
   ```bash
   alembic upgrade head
   ```

6. Start the development server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

   Or use the Makefile:
   ```bash
   make migrate
   make run
   ```

7. Access the API docs at: `http://localhost:8000/docs`

### Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Create a `.env` file (optional):
   ```bash
   cp .env.example .env
   ```

4. Start the development server:
   ```bash
   npm run dev
   ```

5. Access the app at: `http://localhost:5173`

### Quick Start (Both Services)

**Option 1: Unified Script (Recommended)**
```bash
# One-time setup
cd backend && pip install -r requirements.txt && alembic upgrade head
cd ../frontend && npm install
cd ..

# Run both services with one command
./start-dev.sh
```

**Option 2: Separate Terminals**

Backend (Terminal 1):
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend (Terminal 2):
```bash
cd frontend
npm install
npm run dev
```

## Development

### Backend Commands

```bash
make install      # Install dependencies
make migrate      # Run migrations
make test         # Run tests
make run          # Start dev server
make clean        # Clean cache files
```

### Frontend Commands

```bash
npm run dev       # Start dev server
npm run build     # Build for production
npm run preview   # Preview production build
npm run lint      # Run ESLint
```

## Testing

Run backend tests:
```bash
cd backend
pytest
```

Run frontend build test:
```bash
cd frontend
npm run build
```

## API Documentation

Once the backend is running, visit `http://localhost:8000/docs` for interactive API documentation (Swagger UI).

### Key Endpoints

**Authentication**
- `POST /auth/register` - Create new user
- `POST /auth/login` - Login and get JWT token
- `GET /auth/me` - Get current user

**Users**
- `PATCH /users/me` - Update user profile (display name, bio, avatar)

**Characters**
- `GET /characters/` - List user's characters
- `POST /characters/` - Create character with role, era, and portrait
- `PATCH /characters/{id}` - Update character
- `DELETE /characters/{id}` - Delete character

**Realms**
- `GET /realms/` - List realms
- `GET /realms/{id}` - Get realm details
- `POST /realms/` - Create realm with tagline and banner
- `POST /realms/{id}/join` - Join realm

**Posts**
- `GET /posts/feed` - Get personalized feed from joined realms (NEW in Phase 2)
- `GET /posts/realms/{id}/posts` - Get posts in a specific realm
- `POST /posts/realms/{id}/posts` - Create post in realm with IC/OOC/Narration type
- `DELETE /posts/{id}` - Delete post

**AI**
- `POST /ai/character-bio` - Generate character bio using role, era, and tags (stub)

## Deployment

This MVP is configured for local development. For production deployment:

1. Set `DEBUG=False` in backend settings
2. Configure a production database (PostgreSQL recommended)
3. Set a strong `SECRET_KEY`
4. Configure CORS origins appropriately
5. Build the frontend: `npm run build`
6. Serve frontend static files
7. Use a production ASGI server (e.g., Gunicorn with Uvicorn workers)

## Contributing

This is an MVP scaffold. Future enhancements may include:

- Real AI integration (OpenAI, Anthropic)
- Direct messaging between users
- Advanced notifications
- Image uploads and avatars
- Realm moderation tools
- Search and discovery features
- Mobile app

## License

MIT

## Support

For issues or questions, please open a GitHub issue at the repository.
