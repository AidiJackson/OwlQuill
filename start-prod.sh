#!/bin/bash
# Ficshon Production Startup — used by Replit Deployments (Cloud Run target).
#
# This is the deployment-only counterpart to start-dev.sh. It exists so the
# developer workflow (start-dev.sh) is never affected by deployment concerns.
#
# Sprint 34: production no longer runs the Vite dev server. The deployment
# build step compiles the frontend (frontend/dist) and uvicorn serves it
# directly (SERVE_FRONTEND_DIST=true → SPA serving block in app/main.py).
# Why this matters:
#   * Vite dev mode keeps an HMR WebSocket open to every browser tab; when the
#     deployment proxy drops it, the Vite client force-reloads the page — the
#     observed five-minute production reload. Compiled assets have no HMR.
#   * One supervised process instead of two: no /api dev-proxy, no
#     ECONNREFUSED window where the frontend outlives a dead backend.
#   * SPA routing, /api/* routing, /static and auth behaviour are preserved —
#     FastAPI mirrors every route under /api and now serves dist with an SPA
#     fallback for client-side routes.
#
# Development mode is unchanged: start-dev.sh still runs Vite + uvicorn.

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Replit/Cloud Run injects $PORT for the externally-routed process. Fall back to
# 5000, which .replit maps to externalPort 80 for non-Autoscale targets.
PORT="${PORT:-5000}"

# Stream Python output line-by-line into the deployment logs (no buffering), so
# the backend's real exit reason / traceback is always visible.
export PYTHONUNBUFFERED=1

# Backend dependencies are installed into .deploy-python by the [deployment]
# build step in .replit, and must be on the path before uvicorn is invoked.
#
# They are NOT installed into .pythonlibs: that directory is dev-local, is
# excluded from the runtime image by .replitignore, and already exists at build
# time — so pip reports every requirement "already satisfied" there, installs
# nothing, and the runtime container ends up with no packages at all. An
# explicit, non-ignored directory is what makes build and runtime agree.
export PYTHONPATH="$ROOT/.deploy-python:${PYTHONPATH:-}"

# Fail fast, with a clear reason, if the deployment build step didn't produce
# a compiled frontend. app/main.py raises on this too; checking here puts the
# message at the very top of the deployment logs.
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
    echo "[launcher] FATAL: frontend/dist/index.html missing — the deployment" \
         "build step must run 'npm ci && npm run build' in frontend/."
    exit 1
fi

# Tell FastAPI to serve the compiled SPA (see app/main.py SPA serving block).
export SERVE_FRONTEND_DIST=true

echo "🦉 Starting Ficshon (production): uvicorn serving API + compiled frontend on :$PORT"

# exec replaces this shell: uvicorn is PID-visible to the platform, its exit
# status is the container's exit status, and signals are delivered directly.
cd "$ROOT/backend"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
