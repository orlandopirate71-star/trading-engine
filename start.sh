#!/bin/bash
# Trading Station - Start All Services
# Usage: ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}   Trading Station Startup${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# Check if Redis is running
if ! redis-cli ping > /dev/null 2>&1; then
    echo -e "${YELLOW}Starting Redis...${NC}"
    if command -v systemctl &> /dev/null; then
        sudo systemctl start redis-server 2>/dev/null || sudo systemctl start redis 2>/dev/null || true
    fi
    # Check again
    if ! redis-cli ping > /dev/null 2>&1; then
        echo -e "${RED}✗ Redis not running. Please start Redis manually:${NC}"
        echo -e "  sudo systemctl start redis-server"
        echo -e "  or: sudo apt install redis-server"
        exit 1
    fi
fi
echo -e "${GREEN}✓ Redis running${NC}"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Kill any existing processes on our ports
echo -e "${YELLOW}Cleaning up old processes...${NC}"
pkill -f "python.*api.py" 2>/dev/null || true
pkill -f "python.*multi_feed.py" 2>/dev/null || true
pkill -f "node.*vite" 2>/dev/null || true
sleep 1

# Start API server (includes trading engine)
echo -e "${YELLOW}Starting API server...${NC}"
PYTHONUNBUFFERED=1 python api.py > logs/api.log 2>&1 &
API_PID=$!
sleep 2

if kill -0 $API_PID 2>/dev/null; then
    echo -e "${GREEN}✓ API server running (PID: $API_PID)${NC}"
else
    echo -e "${RED}✗ API server failed to start. Check logs/api.log${NC}"
    exit 1
fi

# Start data feeds
echo -e "${YELLOW}Starting data feeds...${NC}"
source venv/bin/activate
PYTHONUNBUFFERED=1 python multi_feed.py > logs/feeds.log 2>&1 &
FEED_PID=$!
sleep 2

if kill -0 $FEED_PID 2>/dev/null; then
    echo -e "${GREEN}✓ Data feeds running (PID: $FEED_PID)${NC}"
else
    echo -e "${YELLOW}! Data feeds may have issues. Check logs/feeds.log${NC}"
fi

# Start dashboard (Vite dev server with proxy)
echo -e "${YELLOW}Starting dashboard...${NC}"
cd dashboard
npm run dev > ../logs/dashboard.log 2>&1 &
DASH_PID=$!
cd ..
sleep 3

if kill -0 $DASH_PID 2>/dev/null; then
    echo -e "${GREEN}✓ Dashboard running (PID: $DASH_PID)${NC}"
else
    echo -e "${YELLOW}! Dashboard may have issues. Check logs/dashboard.log${NC}"
fi

# Launch dashboard in dedicated browser window
echo -e "${YELLOW}Opening dashboard in Chromium...${NC}"
chromium-browser --app=http://localhost:3000 \
    --window-size=1920,1080 \
    --disable-extensions \
    --disable-dev-tools \
    --user-data-dir=/tmp/chromium-trading \
    > /dev/null 2>&1 &
BROWSER_PID=$!
sleep 1
if kill -0 $BROWSER_PID 2>/dev/null; then
    echo -e "${GREEN}✓ Dashboard opened in Chromium (PID: $BROWSER_PID)${NC}"
else
    echo -e "${YELLOW}! Failed to open Chromium. Dashboard still available at http://localhost:3000${NC}"
fi

# Save PIDs for stop script
echo "$API_PID" > .pids/api.pid
echo "$FEED_PID" > .pids/feeds.pid
echo "$DASH_PID" > .pids/dashboard.pid

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}   All Services Started!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo -e "Dashboard:  ${BLUE}http://localhost:3000${NC}"
echo -e "API:        ${BLUE}http://localhost:8000${NC}"
echo ""
echo -e "Logs:       logs/api.log, logs/feeds.log, logs/dashboard.log"
echo -e "Stop:       ${YELLOW}./stop.sh${NC}"
echo ""
