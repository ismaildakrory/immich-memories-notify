#!/bin/sh
# Runs as the unprivileged app user: scheduler + dashboard.
cd /app

# Generate crontab (+ env snapshot for cron jobs) from config.yaml
python -c "from dashboard.crontab import generate_crontab; generate_crontab()"

# Scheduler: supercronic logs each job's output straight to the container log
supercronic -quiet "${CRONTAB_PATH:-/app/crontab}" &

# Forward signals to uvicorn for graceful shutdown
trap 'kill $UVICORN_PID 2>/dev/null; wait $UVICORN_PID' TERM INT

uvicorn dashboard.main:app --host 0.0.0.0 --port "${DASHBOARD_PORT:-5000}" &
UVICORN_PID=$!

# If uvicorn dies (or /api/restart/all asks for a restart) the container exits
wait $UVICORN_PID
