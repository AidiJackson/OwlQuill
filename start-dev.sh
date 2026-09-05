#!/bin/bash
# Ficshon Unified Dev Server
# Starts both backend (FastAPI) and frontend (Vite) for development.
#
# THE TWO SERVICES START IN PARALLEL, and that ordering is the point.
#
# This script used to start uvicorn, poll /health for up to 30 seconds, and only
# then launch Vite. That made port 5000 — the port Replit's webview attaches to
# (.replit maps localPort 5000 to externalPort 80, and the workflow declares
# waitForPort = 5000) — unavailable until the entire backend had imported,
# migrated its seeds and answered a request. Importing app.main alone measures
# ~15s, so the observed gap before Vite was even launched ran from 5s to 13s and
# the loop permitted 30s. For that whole window nothing was listening on 5000,
# and the embedded Preview reported "We couldn't reach this app. Make sure this
# app has a port open and is ready to receive HTTP traffic." The external URL
# looked fine because it was opened by hand a moment later, once 5000 was up.
#
# Vite does not need the backend in order to serve the app shell. Its /api proxy
# simply fails while FastAPI is still booting, which is a few seconds of failed
# XHRs in an environment that is about to work — a far smaller problem than a
# Preview that never attaches. So the health check is still performed, but only
# to REPORT readiness in the log; it gates nothing.

# `set -e` is restored, but the shutdown path below must opt out of it explicitly.
# Three things there return non-zero as a matter of course: the `[ -n "$pid" ]`
# guard when a service never started, `kill` against a process group that has
# already gone, and `wait`, which reports the child's own status (143 after a
# SIGTERM). Under an unguarded `set -e` the first of those aborts cleanup
# mid-loop and the remaining service is never signalled — the orphaned-Vite bug
# this script exists to prevent. So each is suffixed with `|| true`, and every
# other command stays fatal. That is what `set -e` is here for: a failed
# `cd "$ROOT/backend"` must stop the script, not launch uvicorn from whatever
# directory happened to be current.
set -eu

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

BACKEND_PID=""
FRONTEND_PID=""

# Shut down exactly what this script started, and nothing else.
#
# Each service is launched under `setsid`, so it leads its own process group and
# `kill -TERM -PID` reaches it AND its descendants — npm in particular spawns
# `sh -c vite`, which spawns node, and killing only the recorded npm pid leaves
# the real Vite process orphaned holding port 5000. That orphan is exactly what
# made a later `Run` fail with "address already in use".
#
# Targeting is by recorded pid, never by name pattern: a `pkill -f vite` would
# match any unrelated process on the machine whose command line happened to
# contain that word.
cleanup() {
    trap - EXIT INT TERM
    echo -e "\n${BLUE}Shutting down services...${NC}"
    for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
        [ -n "$pid" ] && kill -TERM -"$pid" 2>/dev/null || true
    done
    # Give them a moment to close listeners before the script's own exit.
    for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
        [ -n "$pid" ] && wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🦉 Starting Ficshon Dev Environment..."

# --- Backend: FastAPI on 8000 ------------------------------------------------
echo -e "${GREEN}Starting FastAPI backend on port 8000...${NC}"
cd "$ROOT/backend"
setsid uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# --- Frontend: Vite on 5000, immediately -------------------------------------
# Launched without waiting for the backend, so port 5000 opens as soon as Vite
# itself is ready and Replit's waitForPort = 5000 is satisfied in about a second.
echo -e "${GREEN}Starting Vite frontend on port 5000...${NC}"
cd "$ROOT/frontend"
setsid npm run dev -- --host 0.0.0.0 --port 5000 &
FRONTEND_PID=$!

# --- Backend readiness: reported, never gating -------------------------------
# A bounded background probe. It exists so the log still says when the API came
# up (and warns clearly if it never does), which is the only part of the old
# health gate that was worth keeping. It exits either way and supervises
# nothing, so it cannot become a second long-running process.
(
    for _ in $(seq 1 60); do
        if curl -s -o /dev/null "http://127.0.0.1:8000/health" 2>/dev/null; then
            echo -e "${GREEN}✓ Backend is ready (API requests will now succeed).${NC}"
            exit 0
        fi
        sleep 1
    done
    echo -e "${RED}✗ Backend did not become healthy within 60s.${NC}"
    echo -e "${RED}  The frontend is still served; /api requests will fail until it does.${NC}"
    echo -e "${RED}  Check the traceback above: http://127.0.0.1:8000/health${NC}"
) &

echo ""
echo -e "${GREEN}🎉 Ficshon is starting!${NC}"
echo ""
echo -e "  ${BLUE}Frontend:${NC} http://localhost:5000"
echo -e "  ${BLUE}Backend API:${NC} http://localhost:8000"
echo -e "  ${BLUE}API Docs:${NC} http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"

# Return as soon as EITHER service exits, so a backend that dies on startup
# surfaces immediately instead of leaving a half-running environment. The
# readiness probe above is deliberately NOT in this list — it is meant to exit.
wait -n "$BACKEND_PID" "$FRONTEND_PID" || true
echo -e "${RED}A service exited; shutting the other one down.${NC}"
