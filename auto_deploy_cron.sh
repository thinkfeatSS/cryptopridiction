#!/usr/bin/env bash
# ==============================================================================
# Quant Edge V16 - Automatic Background Deployment Watchdog
# Checks GitHub origin/main for new commits every execution.
# If a new commit is detected, pulls cleanly and triggers zero-downtime deployment.
# ==============================================================================

set -e
PROJECT_DIR="${1:-/root/crypto}"

if [ ! -d "$PROJECT_DIR" ]; then
    exit 0
fi

cd "$PROJECT_DIR" || exit 1

# Prevent concurrent deployment collisions
LOCK_FILE="/tmp/crypto_autodeploy.lock"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    exit 0
fi

# Fetch remote changes quietly
git fetch origin main -q 2>/dev/null || exit 0

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    LOG_FILE="/var/log/crypto_autodeploy.log"
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] 🚀 New commit detected ($REMOTE vs local $LOCAL). Deploying..." >> "$LOG_FILE"
    git pull origin main >> "$LOG_FILE" 2>&1
    chmod +x deploy.sh
    ./deploy.sh >> "$LOG_FILE" 2>&1
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] ✅ Deployment to $REMOTE complete!" >> "$LOG_FILE"
fi

