#!/usr/bin/bash
set -Eeuo pipefail

# Configuration - Update these variables for your setup
SERVER_HOST="192.168.8.233"
SERVER_USER="jacob"
REMOTE_PROJECT_DIR="/home/jacob/automation"
LOCAL_PROJECT_DIR="$(pwd)"
APP_HOST="0.0.0.0"
APP_PORT="8000"
SSH_OPTS=(
  -o ControlMaster=auto
  -o "ControlPath=$HOME/.ssh/cm-%r@%h:%p"
  -o ControlPersist=10m
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting deployment...${NC}"

# Prime a master connection so subsequent SSH/rsync hops reuse auth
ssh "${SSH_OPTS[@]}" -fN "$SERVER_USER@$SERVER_HOST" 2>/dev/null || true

# Function to run commands on remote server with proper environment
# -n closes stdin; -T disables pseudo-tty, both help avoid SSH hangs
run_remote() {
    ssh "${SSH_OPTS[@]}" -n -T "$SERVER_USER@$SERVER_HOST" \
      "source ~/.bashrc 2>/dev/null || true; source ~/.profile 2>/dev/null || true; $1"
}

# Step 1: Sync local files to server
echo -e "${YELLOW}Syncing files to server...${NC}"
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'uvicorn.log' \
    -e "ssh ${SSH_OPTS[*]}" \
    "$LOCAL_PROJECT_DIR/" "$SERVER_USER@$SERVER_HOST:$REMOTE_PROJECT_DIR/"

echo -e "${GREEN}Files synced successfully${NC}"

# Step 2: Find uv and install/update dependencies
echo -e "${YELLOW}Finding uv installation...${NC}"
UV_PATH=$(run_remote "command -v uv 2>/dev/null || find /home -type f -name uv 2>/dev/null | head -1 || echo '/usr/local/bin/uv'")
echo -e "${YELLOW}Using uv at: $UV_PATH${NC}"

echo -e "${YELLOW}Running uv sync on server...${NC}"
run_remote "cd $REMOTE_PROJECT_DIR && \"$UV_PATH\" sync"
echo -e "${GREEN}Dependencies synced successfully${NC}"

# Step 3: Stop existing application via PID file (fallback to pkill)
echo -e "${YELLOW}Stopping existing application...${NC}"
if ! run_remote "
  cd \"$REMOTE_PROJECT_DIR\" 2>/dev/null || true
  if [ -f app.pid ]; then
    PID=\$(cat app.pid 2>/dev/null || true)
    if [ -n \"\$PID\" ]; then kill \"\$PID\" 2>/dev/null || true; fi
    rm -f app.pid || true
  fi
  pkill -f 'uvicorn' 2>/dev/null || true
  true
"; then
  echo -e \"${YELLOW}Warning: stop step returned non-zero, continuing...${NC}\"
fi
echo -e "${GREEN}Application stopped${NC}"

# Step 4: Start the application (fully detached) and record PID
echo -e "${YELLOW}Starting application...${NC}"
run_remote "
  set -Eeuo pipefail
  cd \"$REMOTE_PROJECT_DIR\" || exit 1
  # rotate old log (keep one backup)
  [ -f uvicorn.log ] && mv -f uvicorn.log uvicorn.log.1 || true
  # Start detached: close STDIN, redirect STDOUT/ERR to log, background
  nohup \"$UV_PATH\" run uvicorn app:app --host \"$APP_HOST\" --port \"$APP_PORT\" \
    > uvicorn.log 2>&1 < /dev/null &
  echo \$! > app.pid

  # Simple readiness check: wait up to ~10s for the port to listen
  for i in \$(seq 1 20); do
    ss -ltn 2>/dev/null | grep -q \":$APP_PORT\" && exit 0
    sleep 0.5
  done
  echo 'App did not start listening in time' >&2
  exit 1
"

echo -e "${YELLOW}Running health check...${NC}"
run_remote "
  for i in \$(seq 1 20); do
    if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 http://localhost:$APP_PORT/health >/dev/null; then
      exit 0
    fi
    sleep 0.5
  done
  echo 'Health check failed' >&2
  exit 1
"

echo -e "${GREEN}Deployment completed successfully!${NC}"
echo -e "${YELLOW}Useful commands:${NC}"
echo -e "  View logs: ssh $SERVER_USER@$SERVER_HOST 'tail -f $REMOTE_PROJECT_DIR/uvicorn.log'"
echo -e "  Stop app:  ssh $SERVER_USER@$SERVER_HOST 'cd $REMOTE_PROJECT_DIR && xargs kill < app.pid 2>/dev/null || pkill -f \"uvicorn\"'"
