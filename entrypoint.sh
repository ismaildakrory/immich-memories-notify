#!/bin/sh
# Stop old standalone scheduler if still running (v2.4.x migration)
if docker inspect --format '{{.State.Running}}' immich-memories-scheduler 2>/dev/null | grep -q true; then
    echo "[migration] Stopping old scheduler container (now embedded in dashboard)..."
    docker stop immich-memories-scheduler 2>/dev/null || true
fi

# Generate crontab from config
python -c "from dashboard.crontab import generate_crontab; generate_crontab()"

# Start crond in background
crond -l 2

# Forward signals to uvicorn for graceful shutdown
trap 'kill $UVICORN_PID; wait $UVICORN_PID' TERM INT

# Start uvicorn in background so shell stays PID 1 (reaps zombies)
uvicorn dashboard.main:app --host 0.0.0.0 --port ${DASHBOARD_PORT:-5000} &
UVICORN_PID=$!

# Wait for uvicorn — if it dies, container exits
wait $UVICORN_PID
