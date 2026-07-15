#!/bin/bash
# Ficshon Production Startup — used by Replit Deployments (Cloud Run target).
#
# This is the deployment-only counterpart to start-dev.sh. It exists so the
# developer workflow (start-dev.sh) is never affected by deployment concerns.
#
# Differences from start-dev.sh, and why each matters for deployment:
#   * uvicorn runs WITHOUT --reload — the WatchFiles reloader is a dev-only
#     convenience and is unreliable/pointless inside a Cloud Run container.
#   * The frontend binds $PORT — Replit/Cloud Run injects the port that external
#     traffic is routed to; the externally-facing process MUST listen on it.
#   * No `set -e` + `trap 'kill 0'` self-destruct — under start-dev.sh a brief
#     backend delay tripped `exit 1`, whose EXIT trap ran `kill 0` and tore the
#     WHOLE process group (including the frontend) down, leaving nothing on the
#     port and producing the HTTP 500 at / that was observed on deploy.
#   * The backend readiness wait is best-effort and NON-fatal.
#
# Application behaviour, API routes, the /api proxy, and the frontend are all
# unchanged — only how the two processes are launched for deployment differs.

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Replit/Cloud Run injects $PORT for the externally-routed process. Fall back to
# 5000, which .replit maps to externalPort 80 for non-Autoscale targets.
PORT="${PORT:-5000}"

# Internal API port. Must match the frontend proxy target in
# frontend/vite.config.ts (http://localhost:8000). Overridable for local
# verification only; production leaves it at the default.
BACKEND_PORT="${BACKEND_PORT:-8000}"

echo "🦉 Starting Ficshon (production): frontend :$PORT  ->  backend :$BACKEND_PORT"

BACKEND_PID=""
cleanup() {
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

# --- Backend (FastAPI): production mode, NO --reload ---
cd "$ROOT/backend"
uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!

# --- Best-effort readiness wait (non-fatal: never kills the container) ---
echo "Waiting for backend to become ready..."
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
        echo "✓ Backend ready"
        break
    fi
    sleep 1
done

# --- Frontend: bind the platform port. Preserves the existing /api proxy
#     (vite.config.ts proxies /api and /static to http://localhost:8000). ---
cd "$ROOT/frontend"
npm run dev -- --host 0.0.0.0 --port "$PORT" &
FRONTEND_PID=$!

echo "🎉 Ficshon (production) is up. External process on :$PORT"

# Tie the container lifetime to the externally-routed frontend process. If it
# exits, this script exits (Cloud Run restarts the container) and the EXIT trap
# reaps the backend. No `kill 0`, so a backend hiccup never nukes the frontend.
wait "$FRONTEND_PID"
