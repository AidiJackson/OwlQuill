#!/bin/bash
# OwlQuill Unified Dev Server
# Starts both backend (FastAPI) and frontend (Vite) for development

set -e

echo "🦉 Starting OwlQuill Dev Environment..."

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to cleanup background processes on exit
cleanup() {
    echo -e "\n${BLUE}Shutting down services...${NC}"
    kill 0
}
trap cleanup EXIT

# Start backend
echo -e "${GREEN}Starting FastAPI backend on port 8000...${NC}"
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait for backend to be ready (fail fast if it doesn't start)
echo "Waiting for backend to be ready..."
BACKEND_READY=false
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend is ready!${NC}"
        BACKEND_READY=true
        break
    fi
    sleep 1
done

if [ "$BACKEND_READY" = false ]; then
    echo -e "\033[0;31m✗ ERROR: Backend failed to start within 30 seconds!${NC}"
    echo -e "\033[0;31m  Check the logs above for errors (database connection, missing env vars, etc.)${NC}"
    echo -e "\033[0;31m  Backend health check failed: http://127.0.0.1:8000/health${NC}"
    exit 1
fi

# Start frontend
echo -e "${GREEN}Starting Vite frontend on port 5000...${NC}"
cd ../frontend
npm run dev -- --host 0.0.0.0 --port 5000 &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}🎉 OwlQuill is running!${NC}"
echo ""
echo -e "  ${BLUE}Frontend:${NC} http://localhost:5000"
echo -e "  ${BLUE}Backend API:${NC} http://localhost:8000"
echo -e "  ${BLUE}API Docs:${NC} http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for both processes
wait
