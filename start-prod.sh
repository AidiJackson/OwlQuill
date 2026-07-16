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
#   * FastAPI binds internally to 8000 so the existing Vite /api proxy works.
#
# Process management (the point of this revision):
#   * Backend stdout/stderr are inherited by this script (→ deployment logs) and
#     PYTHONUNBUFFERED=1 forces immediate flushing so a crash traceback is never
#     lost to buffering.
#   * BOTH children are monitored. If EITHER exits, the launcher logs which one
#     and why, tears the other down, and exits NON-ZERO — so Replit restarts /
#     marks the deployment failed instead of serving a frontend whose /api proxy
#     hits a dead backend (the ECONNREFUSED 127.0.0.1:8000 symptom).
#
# Application behaviour, API routes, the /api proxy, and the frontend are all
# unchanged — only how the two processes are launched/supervised differs.

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Replit/Cloud Run injects $PORT for the externally-routed process. Fall back to
# 5000, which .replit maps to externalPort 80 for non-Autoscale targets.
PORT="${PORT:-5000}"

# Internal API port. Must match the frontend proxy target in
# frontend/vite.config.ts (http://localhost:8000). Overridable for local
# verification only; production leaves it at the default.
BACKEND_PORT="${BACKEND_PORT:-8000}"

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

echo "🦉 Starting Ficshon (production): frontend :$PORT  ->  backend :$BACKEND_PORT"

BACKEND_PID=""
FRONTEND_PID=""

# Kill a process and all of its descendants (leaves first). `npm run dev` spawns
# vite/esbuild as grandchildren, so killing only the wrapper PID would orphan the
# process that actually holds the port — this walks the whole tree.
_kill_tree() {
    local pid="$1" child
    [ -z "$pid" ] && return 0
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        _kill_tree "$child"
    done
    kill "$pid" 2>/dev/null || true
}

cleanup() {
    # Disarm the trap so we don't re-enter on our own kills.
    trap - EXIT INT TERM
    _kill_tree "$FRONTEND_PID"
    _kill_tree "$BACKEND_PID"
}
trap cleanup EXIT INT TERM

# --- Backend (FastAPI): production mode, NO --reload. stdout/stderr inherited
#     → visible in Replit deployment logs. ---
cd "$ROOT/backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!
echo "[launcher] backend (uvicorn) started, pid=$BACKEND_PID"

# --- Readiness wait. Fails FAST if the backend exits during startup so the
#     deployment surfaces the reason instead of hanging for 30s. ---
echo "[launcher] waiting for backend to become ready on :$BACKEND_PORT ..."
for i in $(seq 1 30); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        wait "$BACKEND_PID"; bexit=$?
        echo "[launcher] FATAL: backend exited during startup (status $bexit). See the uvicorn traceback above."
        exit 1
    fi
    if curl -s "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
        echo "[launcher] ✓ backend ready"
        break
    fi
    sleep 1
done

# --- Frontend: bind the platform port. Preserves the existing /api proxy
#     (vite.config.ts proxies /api and /static to http://localhost:8000). ---
cd "$ROOT/frontend"
npm run dev -- --host 0.0.0.0 --port "$PORT" &
FRONTEND_PID=$!
echo "[launcher] frontend (vite) started, pid=$FRONTEND_PID"
echo "🎉 Ficshon (production) is up. External process on :$PORT"

# --- Supervise BOTH children. Return as soon as either one exits. ---
wait -n "$BACKEND_PID" "$FRONTEND_PID"
FIRST_EXIT=$?

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[launcher] FATAL: backend (uvicorn) exited (status $FIRST_EXIT). Shutting down frontend and failing the deployment."
    # A dead backend must always fail the container, even on a 0 exit code.
    [ "$FIRST_EXIT" -eq 0 ] && FIRST_EXIT=1
else
    echo "[launcher] FATAL: frontend (vite) exited (status $FIRST_EXIT). Shutting down backend and failing the deployment."
    [ "$FIRST_EXIT" -eq 0 ] && FIRST_EXIT=1
fi

# cleanup() runs via the EXIT trap and reaps the surviving child.
exit "$FIRST_EXIT"
