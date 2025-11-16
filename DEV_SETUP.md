# OwlQuill Development Setup

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
   cd OwlQuill
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
OwlQuill/
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
