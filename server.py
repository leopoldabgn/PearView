#!/usr/bin/env python3
"""
Serveur web léger pour l'application Chronoscope (visite virtuelle 360° temporelle).

- Sert les fichiers statiques du dossier courant (index.html, assets/, aframe.min.js...)
- Expose POST /api/save-config pour sauvegarder config.json depuis le mode éditeur
- Conserve un historique horodaté (max MAX_BACKUPS) dans backups/

Compatible auto-hébergement (Synology NAS / Docker) : aucune dépendance externe,
uniquement la bibliothèque standard Python 3.
"""

import json
import logging
import os
import shutil
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = int(os.environ.get("CHRONOSCOPE_PORT", 8000))
HOST = os.environ.get("CHRONOSCOPE_HOST", "0.0.0.0")
CONFIG_FILE = "config.json"
BACKUP_DIR = "backups"
MAX_BACKUPS = 20
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo, garde-fou contre les payloads absurdes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chronoscope")


class ConfigValidationError(Exception):
    """Levée quand le JSON reçu n'a pas la forme attendue."""


def validate_config_shape(data):
    """Vérifie superficiellement que le JSON reçu ressemble à une config valide,
    pour éviter d'écraser config.json avec des données corrompues."""
    if not isinstance(data, dict):
        raise ConfigValidationError("La racine doit être un objet JSON (lieux).")
    for lieu_key, lieu_val in data.items():
        if not isinstance(lieu_val, dict) or "positions" not in lieu_val:
            raise ConfigValidationError(f"Lieu '{lieu_key}' invalide : champ 'positions' manquant.")
        if not isinstance(lieu_val["positions"], dict):
            raise ConfigValidationError(f"Lieu '{lieu_key}' invalide : 'positions' doit être un objet.")


def prune_old_backups():
    all_backups = [
        os.path.join(BACKUP_DIR, f)
        for f in os.listdir(BACKUP_DIR)
        if f.startswith("config_") and f.endswith(".json")
    ]
    all_backups.sort(key=os.path.getmtime)
    while len(all_backups) > MAX_BACKUPS:
        oldest = all_backups.pop(0)
        os.remove(oldest)
        log.info("Purge de l'ancienne sauvegarde : %s", oldest)


def make_backup():
    """Copie l'actuel config.json vers backups/config_JJ-MM-AAAA[_N].json."""
    if not os.path.exists(CONFIG_FILE):
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)

    today_str = datetime.now().strftime("%d-%m-%Y")
    backup_filename = f"config_{today_str}.json"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    counter = 2
    while os.path.exists(backup_path):
        backup_filename = f"config_{today_str}_{counter}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        counter += 1

    shutil.copy2(CONFIG_FILE, backup_path)
    log.info("Backup créée : %s", backup_path)
    prune_old_backups()
    return backup_path


def save_with_backup(raw_bytes):
    """Valide, sauvegarde une backup puis écrit le nouveau config.json.
    Écriture atomique via fichier temporaire + remplacement, pour éviter
    de corrompre config.json en cas de coupure en cours d'écriture."""
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigValidationError(f"JSON invalide : {exc}") from exc

    validate_config_shape(data)
    make_backup()

    tmp_path = CONFIG_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONFIG_FILE)
    log.info("config.json mis à jour (%d lieu(x))", len(data))


class ChronoscopeHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/save-config":
            self._send_json(404, {"status": "error", "message": "Route inconnue."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json(400, {"status": "error", "message": "En-tête Content-Length invalide."})
            return

        if content_length <= 0:
            self._send_json(400, {"status": "error", "message": "Corps de requête vide."})
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(413, {"status": "error", "message": "Fichier trop volumineux."})
            return

        raw_bytes = self.rfile.read(content_length)

        try:
            save_with_backup(raw_bytes)
            self._send_json(200, {"status": "success"})
        except ConfigValidationError as exc:
            log.warning("Rejet de la sauvegarde : %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Erreur disque lors de la sauvegarde : %s", exc)
            self._send_json(500, {"status": "error", "message": "Erreur serveur lors de l'écriture du fichier."})


def main():
    try:
        server = HTTPServer((HOST, PORT), ChronoscopeHandler)
    except OSError as exc:
        log.error("Impossible de démarrer le serveur sur %s:%s (%s)", HOST, PORT, exc)
        sys.exit(1)

    log.info("Chronoscope actif : http://%s:%s (Ctrl+C pour arrêter)", HOST if HOST != "0.0.0.0" else "localhost", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Arrêt du serveur.")
        server.shutdown()


if __name__ == "__main__":
    main()