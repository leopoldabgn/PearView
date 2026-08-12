#!/usr/bin/env python3
"""
Serveur web léger pour l'application PearView (visite virtuelle 360° temporelle).

- Sert les fichiers statiques du dossier courant (index.html, assets/, aframe.min.js...)
- Expose POST /api/save-config pour sauvegarder config.json depuis le mode éditeur
- Expose POST /api/upload-photo pour importer une nouvelle photo (= nouvelle
  position, ou nouvelle date pour une position existante), avec création
  automatique des dossiers assets/LIEU/POSITION nécessaires
- Expose POST /api/delete-position et POST /api/delete-lieu pour supprimer,
  depuis le mode éditeur, une position (et ses photos) ou un lieu entier
- Conserve un historique horodaté (max MAX_BACKUPS) dans backups/

Compatible auto-hébergement (Synology NAS / Docker) : aucune dépendance externe,
uniquement la bibliothèque standard Python 3.
"""

import base64
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

import generate_config

PORT = int(os.environ.get("PEARVIEW_PORT", 1500))
HOST = os.environ.get("PEARVIEW_HOST", "0.0.0.0")
CONFIG_FILE = "config.json"
BACKUP_DIR = "backups"
MAX_BACKUPS = 20
# 130 Mo : garde-fou contre les payloads absurdes. Les photos importées sont
# envoyées encodées en base64 (+/- 33% de volume) à l'intérieur d'un JSON,
# donc la limite doit rester généreuse par rapport à la taille réelle du fichier.
MAX_UPLOAD_BYTES = 130 * 1024 * 1024

FILENAME_RE = re.compile(r"^(.+)_(\d{2})-(\d{4})\.(jpe?g|png)$", re.IGNORECASE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pearview")


class ConfigValidationError(Exception):
    """Levée quand le JSON/les paramètres reçus n'ont pas la forme attendue."""


# =============================================================================
# UTILITAIRES COMMUNS
# =============================================================================

def is_safe_path_component(name):
    """Un nom de lieu/position ne doit jamais permettre de sortir de assets/."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name and "\x00" not in name


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


def write_config(config):
    """Écriture atomique via fichier temporaire + remplacement, pour éviter
    de corrompre config.json en cas de coupure en cours d'écriture."""
    tmp_path = CONFIG_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONFIG_FILE)


def save_with_backup(raw_bytes):
    """Valide, sauvegarde une backup puis écrit le nouveau config.json."""
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigValidationError(f"JSON invalide : {exc}") from exc

    validate_config_shape(data)
    make_backup()
    write_config(data)
    log.info("config.json mis à jour (%d lieu(x))", len(data))


def prune_dangling_arrows(config, dead_lieu, dead_position):
    """Retire, dans TOUTES les positions de TOUS les lieux, les flèches qui
    pointaient vers la position qu'on vient de supprimer."""
    for lieu_val in config.values():
        for pos_val in lieu_val.get("positions", {}).values():
            pos_val["arrows"] = [
                a for a in pos_val.get("arrows", [])
                if not (a.get("targetLieu") == dead_lieu and a.get("targetPos") == dead_position)
            ]


def prune_dangling_lieu(config, dead_lieu):
    """Retire, dans TOUTES les positions de TOUS les lieux, les flèches qui
    pointaient vers le lieu qu'on vient de supprimer entièrement."""
    for lieu_val in config.values():
        for pos_val in lieu_val.get("positions", {}).values():
            pos_val["arrows"] = [a for a in pos_val.get("arrows", []) if a.get("targetLieu") != dead_lieu]


# =============================================================================
# IMPORT DE PHOTO (= nouvelle position, ou nouvelle date pour une position
# existante)
# =============================================================================

def handle_upload_photo(payload):
    lieu = (payload.get("lieu") or "").strip()
    filename = (payload.get("filename") or "").strip()
    image_b64 = payload.get("imageBase64") or ""
    overwrite = bool(payload.get("overwrite", False))

    if not lieu or not filename or not image_b64:
        raise ConfigValidationError("Champs manquants (lieu, filename, imageBase64).")
    if not is_safe_path_component(lieu):
        raise ConfigValidationError("Nom de lieu invalide.")

    match = FILENAME_RE.match(filename)
    if not match:
        raise ConfigValidationError(
            "Nom de fichier invalide. Format attendu : POSITION_MM-AAAA.jpg "
            "(ex : jardin_08-2026.jpg)."
        )
    position, month_str, year_str, _ext = match.groups()
    month = int(month_str)
    if not (1 <= month <= 12):
        raise ConfigValidationError(f"Mois invalide dans le nom de fichier : {month_str}.")
    if not is_safe_path_component(position):
        raise ConfigValidationError("Nom de position invalide.")

    pos_dir = os.path.join(generate_config.ASSETS_DIR, lieu, position)
    target_path = os.path.join(pos_dir, filename)

    if os.path.exists(target_path) and not overwrite:
        return {
            "status": "conflict",
            "message": f"La photo « {filename} » existe déjà pour {lieu} / {position}.",
        }

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception as exc:  # binascii.Error et autres
        raise ConfigValidationError(f"Image invalide (décodage base64 impossible) : {exc}") from exc

    if not raw:
        raise ConfigValidationError("Image vide.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ConfigValidationError("Image trop volumineuse.")

    os.makedirs(pos_dir, exist_ok=True)
    tmp_path = target_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(raw)
    os.replace(tmp_path, target_path)
    log.info("Photo enregistrée : %s (%.1f Ko)", target_path, len(raw) / 1024)

    # On régénère systématiquement config.json en rescannant assets/ : cela
    # ajoute/actualise la position sans jamais toucher aux flèches et points
    # d'information déjà configurés ailleurs (voir generate_config.scan_assets).
    make_backup()
    config = generate_config.build_config()
    write_config(config)

    return {"status": "success", "lieu": lieu, "position": position, "config": config}


# =============================================================================
# SUPPRESSION D'UNE POSITION / D'UN LIEU
# =============================================================================

def handle_delete_position(payload):
    lieu = (payload.get("lieu") or "").strip()
    position = (payload.get("position") or "").strip()
    if not lieu or not position:
        raise ConfigValidationError("Champs 'lieu' et 'position' requis.")

    config = generate_config.load_existing_config()
    if lieu not in config or position not in config.get(lieu, {}).get("positions", {}):
        raise ConfigValidationError("Lieu ou position introuvable dans la configuration.")

    make_backup()

    pos_dir = os.path.join(generate_config.ASSETS_DIR, lieu, position)
    if os.path.isdir(pos_dir):
        shutil.rmtree(pos_dir)
        log.info("Dossier position supprimé : %s", pos_dir)

    del config[lieu]["positions"][position]
    prune_dangling_arrows(config, lieu, position)

    lieu_removed = False
    if not config[lieu]["positions"]:
        # Plus aucune position dans ce lieu : on le supprime entièrement,
        # sinon il resterait un lieu "fantôme" sans defaultPosition valide.
        lieu_dir = os.path.join(generate_config.ASSETS_DIR, lieu)
        if os.path.isdir(lieu_dir):
            shutil.rmtree(lieu_dir)
            log.info("Dossier lieu (vide) supprimé : %s", lieu_dir)
        del config[lieu]
        prune_dangling_lieu(config, lieu)
        lieu_removed = True
    elif config[lieu].get("defaultPosition") == position:
        config[lieu]["defaultPosition"] = next(iter(config[lieu]["positions"]))

    write_config(config)
    log.info(
        "Position supprimée : %s/%s%s",
        lieu, position, " (lieu également supprimé, plus aucune position)" if lieu_removed else "",
    )
    return {"status": "success", "config": config, "lieuRemoved": lieu_removed}


def handle_delete_lieu(payload):
    lieu = (payload.get("lieu") or "").strip()
    if not lieu:
        raise ConfigValidationError("Champ 'lieu' requis.")

    config = generate_config.load_existing_config()
    if lieu not in config:
        raise ConfigValidationError("Lieu introuvable dans la configuration.")

    make_backup()

    lieu_dir = os.path.join(generate_config.ASSETS_DIR, lieu)
    if os.path.isdir(lieu_dir):
        shutil.rmtree(lieu_dir)
        log.info("Dossier lieu supprimé : %s", lieu_dir)

    del config[lieu]
    prune_dangling_lieu(config, lieu)

    write_config(config)
    log.info("Lieu supprimé : %s", lieu)
    return {"status": "success", "config": config}


# =============================================================================
# SERVEUR HTTP
# =============================================================================

class PearViewHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_raw_body(self):
        """Lit le corps de la requête en respectant Content-Length, avec
        garde-fous. Retourne None (et répond déjà au client) en cas d'erreur."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json(400, {"status": "error", "message": "En-tête Content-Length invalide."})
            return None

        if content_length <= 0:
            self._send_json(400, {"status": "error", "message": "Corps de requête vide."})
            return None
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(413, {"status": "error", "message": "Fichier trop volumineux."})
            return None

        return self.rfile.read(content_length)

    def _read_json_body(self):
        raw = self._read_raw_body()
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"status": "error", "message": f"JSON invalide : {exc}"})
            return None

    def do_POST(self):
        routes = {
            "/api/save-config": self._handle_save_config,
            "/api/upload-photo": self._handle_upload_photo,
            "/api/delete-position": self._handle_delete_position,
            "/api/delete-lieu": self._handle_delete_lieu,
        }
        handler = routes.get(self.path)
        if handler is None:
            self._send_json(404, {"status": "error", "message": "Route inconnue."})
            return
        handler()

    def _handle_save_config(self):
        raw = self._read_raw_body()
        if raw is None:
            return
        try:
            save_with_backup(raw)
            self._send_json(200, {"status": "success"})
        except ConfigValidationError as exc:
            log.warning("Rejet de la sauvegarde : %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Erreur disque lors de la sauvegarde : %s", exc)
            self._send_json(500, {"status": "error", "message": "Erreur serveur lors de l'écriture du fichier."})

    def _handle_upload_photo(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_upload_photo(payload)
            status_code = 200 if result.get("status") == "success" else 409
            self._send_json(status_code, result)
        except ConfigValidationError as exc:
            log.warning("Rejet de l'import : %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Erreur disque lors de l'import : %s", exc)
            self._send_json(500, {"status": "error", "message": "Erreur serveur lors de l'écriture du fichier."})

    def _handle_delete_position(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_delete_position(payload)
            self._send_json(200, result)
        except ConfigValidationError as exc:
            log.warning("Rejet de la suppression : %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Erreur disque lors de la suppression : %s", exc)
            self._send_json(500, {"status": "error", "message": "Erreur serveur lors de la suppression."})

    def _handle_delete_lieu(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_delete_lieu(payload)
            self._send_json(200, result)
        except ConfigValidationError as exc:
            log.warning("Rejet de la suppression : %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Erreur disque lors de la suppression : %s", exc)
            self._send_json(500, {"status": "error", "message": "Erreur serveur lors de la suppression."})


def main():
    try:
        server = HTTPServer((HOST, PORT), PearViewHandler)
    except OSError as exc:
        log.error("Impossible de démarrer le serveur sur %s:%s (%s)", HOST, PORT, exc)
        sys.exit(1)

    log.info("PearView actif : http://%s:%s (Ctrl+C pour arrêter)", HOST if HOST != "0.0.0.0" else "localhost", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Arrêt du serveur.")
        server.shutdown()


if __name__ == "__main__":
    main()