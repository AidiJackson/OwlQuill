# OwlQuill Development Guide

## Project Structure

```
OwlQuill/
├── backend/           # FastAPI backend
│   ├── alembic/       # Database migrations
│   ├── app/
│   │   ├── api/       # API routes
│   │   ├── core/      # Config, database, dependencies
│   │   ├── models/    # SQLAlchemy models
│   │   ├── schemas/   # Pydantic schemas
│   │   └── services/  # Business logic
│   └── tests/         # Backend tests
├── frontend/          # React + TypeScript frontend
│   ├── src/
│   │   ├── components/ # Reusable components
│   │   ├── pages/      # Page components
│   │   └── lib/        # Utilities, API client
│   └── public/         # Static assets
└── docs/              # Documentation
```

## Setup Instructions

### Prerequisites
- Python 3.11+
- Node.js 18+
- Git

### Backend Setup

1. **Navigate to backend directory**:
   ```bash
   cd backend
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Create environment file**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set your configuration values.

5. **Run database migrations**:
   ```bash
   alembic upgrade head
   ```

6. **Start the backend**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

The API will be available at `http://localhost:8000`
API documentation at `http://localhost:8000/docs`

### Frontend Setup

1. **Navigate to frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Start the development server**:
   ```bash
   npm run dev
   ```

The frontend will be available at `http://localhost:5173`

### Quick Start (Replit)

If using Replit, simply run:
```bash
./start-dev.sh
```

This script starts both backend and frontend concurrently.

## Database Migrations

### Creating a New Migration

```bash
cd backend
alembic revision -m "description of changes"
```

Edit the generated file in `alembic/versions/` to define the upgrade and downgrade logic.

### Applying Migrations

```bash
alembic upgrade head
```

### Rolling Back

```bash
alembic downgrade -1  # Rollback one migration
alembic downgrade <revision>  # Rollback to specific revision
```

## Running Tests

### Backend Tests

```bash
cd backend
pytest
```

Run specific test file:
```bash
pytest tests/test_auth.py
```

Run with coverage:
```bash
pytest --cov=app tests/
```

### Frontend Tests

```bash
cd frontend
npm test
```

## Code Style

### Backend (Python)
- Follow PEP 8
- Use type hints
- Document functions with docstrings
- Maximum line length: 100 characters

### Frontend (TypeScript/React)
- Use TypeScript strict mode
- Follow Airbnb style guide
- Use functional components with hooks
- Use Tailwind CSS for styling

## Architecture Notes

### Backend Architecture

**Models**: SQLAlchemy ORM models in `app/models/`
- Define database schema
- Include relationships between models
- Handle cascading deletes

**Schemas**: Pydantic models in `app/schemas/`
- Define request/response formats
- Provide validation
- Separate Create/Update/Response schemas

**Routes**: FastAPI routers in `app/api/routes/`
- Handle HTTP requests
- Validate input using schemas
- Call service layer for business logic
- Return responses

**Services**: Business logic in `app/services/`
- AI stub service for bio/scene generation
- Extensible for additional services

### Frontend Architecture

**Pages**: Top-level route components in `src/pages/`
- Handle routing and layout
- Fetch data from API
- Manage local state

**Components**: Reusable UI components in `src/components/`
- Layout component for navigation
- Potential for more shared components

**API Client**: Centralized API communication in `src/lib/apiClient.ts`
- Type-safe API calls
- Authentication token management
- Error handling

**Types**: TypeScript interfaces in `src/lib/types.ts`
- Match backend schemas
- Ensure type safety across frontend

**State**: Zustand store in `src/lib/store.ts`
- Global auth state
- User information

## Data Model Hierarchy

```
User
├── Characters (owns)
├── Realms (owns)
└── RealmMemberships (member of)

Realm
├── Scenes
│   └── Posts
├── Members (RealmMemberships)
└── Owner (User)

Scene
├── Posts
├── Realm (belongs to)
└── Creator (User)

Post
├── Scene (belongs to)
├── Realm (denormalized for performance)
├── Author (User)
├── Character (optional)
├── Comments
└── Reactions
```

### Important: Post Denormalization

Posts have both `scene_id` and `realm_id`. The `realm_id` is denormalized for query performance, particularly for the feed endpoint. When creating a post, the backend automatically sets `realm_id` to match the scene's realm.

## API Conventions

- Use plural nouns for collections: `/realms/`, `/scenes/`
- Nest resources logically: `/scenes/realms/{realm_id}/scenes`
- Use HTTP methods correctly:
  - GET: Retrieve
  - POST: Create
  - PATCH: Partial update
  - DELETE: Remove
- Return appropriate status codes:
  - 200: OK
  - 201: Created
  - 204: No Content
  - 400: Bad Request
  - 401: Unauthorized
  - 403: Forbidden
  - 404: Not Found

## Environment Variables

### Backend (.env)
```
DATABASE_URL=sqlite:///./owlquill.db
SECRET_KEY=your-secret-key-here
DEBUG=true
```

### Frontend (.env)
```
VITE_API_BASE_URL=/api
```

## Deployment

### Backend Deployment
1. Set production environment variables
2. Run database migrations
3. Use a production ASGI server (e.g., Gunicorn with Uvicorn workers)
4. Set up reverse proxy (e.g., Nginx)

### Frontend Deployment
1. Build the production bundle:
   ```bash
   npm run build
   ```
2. Serve the `dist/` directory with a static file server
3. Configure API proxy if needed

## Contributing

1. **Branch Naming**: Use descriptive names like `feature/scene-system` or `fix/auth-bug`
2. **Commit Messages**: Follow conventional commits format
3. **Pull Requests**: Include description, testing notes, and screenshots if applicable
4. **Tests**: Add tests for new features and bug fixes
5. **Documentation**: Update docs when changing APIs or features

## Troubleshooting

### Database Issues
- Delete `owlquill.db` and run migrations again for a fresh start
- Check alembic version: `alembic current`

### CORS Errors
- Verify `BACKEND_CORS_ORIGINS` in backend config
- Check frontend API_BASE_URL configuration

### Module Import Errors
- Ensure virtual environment is activated (backend)
- Run `npm install` if packages are missing (frontend)

### Port Already in Use
- Change ports in run commands
- Kill existing processes on the port

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [TypeScript Documentation](https://www.typescriptlang.org/docs/)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)

## Support

- GitHub Issues: Report bugs and request features
- Discussions: Ask questions and share ideas
- Pull Requests: Contribute code improvements

Happy coding! 🦉💻
