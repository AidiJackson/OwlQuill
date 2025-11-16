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

# Wait for backend to be ready
echo "Waiting for backend to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend is ready!${NC}"
        break
    fi
    sleep 1
done

# Start frontend
echo -e "${GREEN}Starting Vite frontend on port 5173...${NC}"
cd ../frontend
npm run dev -- --host 0.0.0.0 &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}🎉 OwlQuill is running!${NC}"
echo ""
echo -e "  ${BLUE}Frontend:${NC} http://localhost:5173"
echo -e "  ${BLUE}Backend API:${NC} http://localhost:8000"
echo -e "  ${BLUE}API Docs:${NC} http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for both processes
wait
