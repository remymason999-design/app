#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Persistence fix: a container-local mongod must NOT write to /tmp, which is
# wiped on every container recycle (sleep/wake, redeploy, crash) and takes all
# user data with it. We store the data under the persistent workspace instead.
#
# Atlas-ready: when MONGO_URL points at a managed/external cluster (e.g. MongoDB
# Atlas) we skip launching a local mongod entirely and connect straight to it.
# This is the production path — flip the MONGO_URL secret, no code change needed.
MONGO_DATA_DIR="/home/runner/workspace/.data/mongodb"

if echo "${MONGO_URL:-}" | grep -qE 'localhost|127\.0\.0\.1'; then
    mkdir -p "$MONGO_DATA_DIR"
    if ! pgrep -x mongod > /dev/null; then
        mongod --dbpath "$MONGO_DATA_DIR" --fork --logpath /tmp/mongodb.log --port 27017
        echo "MongoDB started (persistent dbpath: $MONGO_DATA_DIR)"
    else
        echo "MongoDB already running"
    fi
else
    echo "MONGO_URL is external (managed cluster) — skipping local mongod launch"
fi

# Start backend
cd /home/runner/workspace/backend
python3 -m uvicorn server:app --host localhost --port 8000 --reload &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID)"

# Start frontend
cd /home/runner/workspace/frontend
BROWSER=none PORT=5000 npm start &
FRONTEND_PID=$!
echo "Frontend started (PID $FRONTEND_PID)"

# Wait for any process to exit
wait -n $BACKEND_PID $FRONTEND_PID
