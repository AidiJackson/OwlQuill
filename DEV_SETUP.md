# Ficshon Development Setup

## Running in Replit (Recommended) 🚀

### Branch
Make sure you're on the correct branch:
```bash
git checkout claude/owlquill-mvp-scaffold-01-01LsA63K16RBXUq5vjjnqBcf
```

### One-Time Setup (First Time Only)

When you first open the project in Replit, you need to install dependencies:

1. **Install Backend Dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Install Frontend Dependencies:**
   ```bash
   cd frontend
   npm install
   ```

3. **Run Database Migrations:**
   ```bash
   cd backend
   alembic upgrade head
   ```

### Daily Development

**That's it! Just click the "Run" button in Replit.**

The unified dev script will:
- Start the FastAPI backend on port 8000
- Start the React/Vite frontend on port 5173
- Wait for the backend to be healthy before starting frontend
- Show you both services running

**The Replit preview will automatically show the React frontend.**

### What's Running

- **Frontend (React + Vite)**: Port 5173 (this is what you see in the preview)
- **Backend (FastAPI)**: Port 8000
- **API Documentation**: Available at `/docs` on the backend port

### How It Works

- The frontend uses a Vite proxy to forward all `/api/*` requests to the backend
- The backend has CORS enabled for development
- Both services run in parallel via the `start-dev.sh` script

### Stopping the Services

Press `Ctrl+C` in the shell to stop both services.

---

## Running Locally (Alternative)

If you're developing on your local machine instead of Replit:

### Prerequisites
- Python 3.11+
- Node.js 18+
- npm

### Setup

1. **Clone and checkout the branch:**
   ```bash
   git clone <repo-url>
   cd ficshon
   git checkout claude/owlquill-mvp-scaffold-01-01LsA63K16RBXUq5vjjnqBcf
   ```

2. **Backend Setup:**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   alembic upgrade head
   ```

3. **Frontend Setup:**
   ```bash
   cd frontend
   npm install
   ```

### Running (Two Options)

**Option 1: Unified Script (Recommended)**
```bash
./start-dev.sh
```

**Option 2: Separate Terminals**

Terminal 1 (Backend):
```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

Then open: http://localhost:5173

---

## Troubleshooting

### "Module not found" errors
Run the install commands again:
```bash
cd backend && pip install -r requirements.txt
cd ../frontend && npm install
```

### Database errors
Run migrations:
```bash
cd backend
alembic upgrade head
```

## Database access

`DATABASE_URL` is the canonical connection for both the application and Alembic.
Everything derives from it: `backend/app/core/database.py`,
`backend/alembic/env.py`, and every script that goes through
`app.core.database.SessionLocal`.

**For a DEV database shell, use the wrapper — not a bare `psql`:**

```bash
./scripts/devdb                      # interactive psql on the DEV database
./scripts/devdb -c 'SELECT 1'        # extra arguments pass through to psql
./scripts/devdb pg_dump -t users     # pg_dump instead of psql
./scripts/devdb --check              # validate the target, connect to nothing
```

`scripts/devdb` connects using `DATABASE_URL`, refuses to launch anything unless
the destination classifies as the known DEV database, and strips ambient
`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE` from the client's
environment. A bare `psql` does none of that: when those variables are set, it
silently connects to whatever they name.

**Writing a maintenance or data-touching script?** Assert the target first:

```python
from assert_dev_db import assert_dev_database   # scripts/assert_dev_db.py

assert_dev_database(purpose="to backfill image URLs")
```

It raises rather than returning a URL for anything it cannot positively identify
as DEV, and its errors never contain connection details.

**Do not set `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` or `PGDATABASE` in this
workspace.** Nothing in the repository reads them, and ambient values pointing
at non-DEV infrastructure are how a routine local command reaches the wrong
database. If an integration re-provisions them, remove them again.

**Production database access is deliberate and separate.** It is never something
ambient workspace variables should make possible, and there is no path to it
through `scripts/devdb`.

### Port already in use
Kill the processes using ports 8000 or 5173:
```bash
# On Linux/Mac
lsof -ti:8000 | xargs kill
lsof -ti:5173 | xargs kill
```

### Frontend can't reach backend
Make sure both services are running and check the console for errors.

---

## Project Structure

```
Ficshon/
├── backend/          # FastAPI backend
│   ├── app/
│   │   ├── api/      # API routes
│   │   ├── core/     # Config, database, security
│   │   ├── models/   # SQLAlchemy models
│   │   ├── schemas/  # Pydantic schemas
│   │   └── services/ # Business logic
│   └── alembic/      # Database migrations
├── frontend/         # React + TypeScript frontend
│   └── src/
│       ├── components/
│       ├── pages/
│       └── lib/      # API client, types, state
└── start-dev.sh      # Unified dev runner
```

## Next Steps

Once you have the app running:

1. **Register a user** at `/register`
2. **Create a character** at `/characters`
3. **Join or create a realm** at `/realms`
4. **Start posting!** 🦉✨
