# OwlQuill Development Workflow

This document describes the recommended workflow for developing OwlQuill using GitHub, Claude Code, and Replit.

## Overview

The OwlQuill project uses a distributed development workflow:

1. **GitHub** - Source of truth and version control
2. **Claude Code (Local/CLI)** - For scaffolding and major development
3. **Replit** - For quick edits, testing, and iteration

## Workflow Steps

### Step 1: Initial Setup (One-time)

1. **GitHub Repository**
   - Repository: `https://github.com/AidiJackson/OwlQuill.git`
   - Clone locally or connect to Replit

2. **Local Development with Claude Code**
   - Clone the repository:
     ```bash
     git clone https://github.com/AidiJackson/OwlQuill.git
     cd OwlQuill
     ```
   - Use Claude Code to scaffold features, create boilerplate, and handle complex tasks

3. **Replit Import**
   - Import the GitHub repository into Replit
   - Replit will automatically detect the project structure
   - Configure Replit to run both backend and frontend

### Step 2: Development Workflow

#### For Major Features (Use Claude Code)

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Use Claude Code to:**
   - Generate new models, schemas, and API endpoints
   - Create new frontend pages and components
   - Write tests
   - Handle complex refactoring

3. **Commit and push to GitHub**
   ```bash
   git add .
   git commit -m "feat: describe your feature"
   git push -u origin feature/your-feature-name
   ```

4. **Create a Pull Request on GitHub**
   - Review the changes
   - Merge to main when ready

#### For Small Changes (Use Replit)

1. **Pull latest changes in Replit**
   - Replit automatically syncs with GitHub
   - Or manually: `git pull origin main`

2. **Make small edits**
   - Fix bugs
   - Adjust styling
   - Update copy/text
   - Test features

3. **Test in Replit**
   - Run backend: `cd backend && uvicorn app.main:app --reload --port 8000`
   - Run frontend: `cd frontend && npm run dev`
   - Replit provides a live preview

4. **Commit and push from Replit**
   ```bash
   git add .
   git commit -m "fix: describe your fix"
   git push origin main
   ```

### Step 3: Using Claude Code in Replit Shell

You can also use Claude Code directly in Replit's shell for quick tasks:

1. Open Replit Shell
2. Run Claude Code commands:
   ```bash
   # Example: Ask Claude to add a new field to a model
   claude "Add an 'avatar_url' field to the User model"
   ```

## Recommended Task Distribution

### Use Claude Code For:
- Creating new backend models and schemas
- Generating API endpoints
- Writing database migrations
- Creating new frontend pages/components
- Complex state management
- Writing tests
- Major refactoring

### Use Replit For:
- Quick bug fixes
- Styling adjustments
- Text/copy updates
- Testing new features
- Running migrations
- Database inspection
- Log viewing

## Tips for Efficient Development

### 1. Keep Dependencies in Sync
- After Claude Code adds new backend dependencies, run in Replit:
  ```bash
  cd backend
  pip install -r requirements.txt
  ```
- After frontend dependency changes:
  ```bash
  cd frontend
  npm install
  ```

### 2. Database Migrations
- Create migration (Claude Code):
  ```bash
  cd backend
  alembic revision --autogenerate -m "description"
  ```
- Run migration (Replit or Claude Code):
  ```bash
  cd backend
  alembic upgrade head
  ```

### 3. Environment Variables
- Update `.env` files in both local and Replit environments
- Never commit `.env` files to Git
- Use `.env.example` as a template

### 4. Git Branch Strategy
- `main` - Production-ready code
- `develop` - Integration branch (optional)
- `feature/*` - New features
- `fix/*` - Bug fixes
- `chore/*` - Maintenance tasks

### 5. Testing Before Deployment
Always test in Replit before merging to main:
1. Run backend tests: `cd backend && pytest`
2. Build frontend: `cd frontend && npm run build`
3. Manual testing in Replit preview

## Replit Configuration

### Backend (Python)
Create a `.replit` file:
```toml
run = "cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000"
language = "python3"

[nix]
channel = "stable-23_11"

[deployment]
run = ["sh", "-c", "cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

### Frontend (Node.js)
In a separate Repl or use a process manager to run both:
```bash
# Install concurrently
npm install -g concurrently

# Run both
concurrently "cd backend && uvicorn app.main:app --reload" "cd frontend && npm run dev"
```

## Common Issues & Solutions

### Issue: Port conflicts
**Solution**: Ensure backend runs on port 8000 and frontend on 5173

### Issue: CORS errors
**Solution**: Check `BACKEND_CORS_ORIGINS` in backend/.env includes your Replit URL

### Issue: Database not found
**Solution**: Run `alembic upgrade head` in backend directory

### Issue: Module not found
**Solution**:
- Backend: `pip install -r requirements.txt`
- Frontend: `npm install`

## Summary

This workflow allows you to:
- Use Claude Code for heavy lifting and scaffolding
- Use Replit for quick iterations and testing
- Maintain GitHub as the single source of truth
- Move seamlessly between development environments

Keep your workflow simple, commit often, and test in Replit before pushing to main.
