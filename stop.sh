#!/bin/bash
# Trading Station - Stop All Services
# Usage: ./stop.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Stopping Trading Station...${NC}"

# Stop by PID files
if [ -f ".pids/api.pid" ]; then
    kill $(cat .pids/api.pid) 2>/dev/null && echo -e "${GREEN}✓ API stopped${NC}"
    rm .pids/api.pid
fi

if [ -f ".pids/feeds.pid" ]; then
    kill $(cat .pids/feeds.pid) 2>/dev/null && echo -e "${GREEN}✓ Feeds stopped${NC}"
    rm .pids/feeds.pid
fi

if [ -f ".pids/dashboard.pid" ]; then
    kill $(cat .pids/dashboard.pid) 2>/dev/null && echo -e "${GREEN}✓ Dashboard stopped${NC}"
    rm .pids/dashboard.pid
fi

# Also kill by process name as backup
pkill -f "python.*api.py" 2>/dev/null || true
pkill -f "python.*multi_feed.py" 2>/dev/null || true
pkill -f "node.*vite" 2>/dev/null || true

echo -e "${GREEN}All services stopped.${NC}"
