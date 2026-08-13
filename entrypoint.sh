#!/bin/bash
set -e

cd /app

# If config.json does not exist in the mounted volume, create an empty one
if [ ! -f /app/data/config.json ]; then
    echo "{}" > /app/data/config.json
fi

echo "[entrypoint] Initial scan of data/assets/ (generate_config.py)…"
python3 generate_config.py || true

echo "[entrypoint] Starting cron (rescan every 5 min)…"
cron

echo "[entrypoint] Starting PearView server on port ${PEARVIEW_PORT:-1500}…"
# exec replaces the bash process with server.py: it becomes PID 1,
# allowing Docker to cleanly forward signals (Ctrl+C, docker stop…).
exec python3 server.py