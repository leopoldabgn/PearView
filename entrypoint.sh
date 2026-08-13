#!/bin/bash
set -e

cd /app

# Si config.json n'existe pas dans le volume monté, on en crée un vide
if [ ! -f /app/data/config.json ]; then
    echo "{}" > /app/data/config.json
fi

echo "[entrypoint] Scan initial de data/assets/ (generate_config.py)…"
python3 generate_config.py || true

echo "[entrypoint] Démarrage du cron (rescan toutes les 5 min)…"
cron

echo "[entrypoint] Démarrage du serveur PearView sur le port ${PEARVIEW_PORT:-1500}…"
# exec remplace le process bash par server.py : c'est lui le PID 1,
# ce qui permet à Docker de lui transmettre proprement les signaux (Ctrl+C, docker stop…).
exec python3 server.py