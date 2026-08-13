#!/usr/bin/env python3
"""
Lightweight web server for the PearView application (temporal 360° virtual tour).

- Serves static files from the current folder (index.html, assets/, aframe.min.js...)
- Exposes POST /api/save-config to save config.json from editor mode
- Exposes POST /api/upload-photo to import a new photo (= a new position, or a
  new date for an existing position), with automatic creation of the
  assets/PLACE/POSITION folders needed
- Exposes POST /api/delete-position and POST /api/delete-place to delete,
  from editor mode, a position (and its photos) or an entire place
- Exposes POST /api/rescan to trigger a rescan of assets/ without importing
- Exposes POST /api/rename-place and POST /api/rename-position to rename
  a place or a position (disk folder + config.json + arrows pointing to it)
- Keeps a timestamped history (max MAX_BACKUPS) in backups/

Self-hosting friendly (Synology NAS / Docker): no external dependency,
Python 3 standard library only.
"""

import base64
import hashlib
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
CONFIG_FILE = "data/config.json"
BACKUP_DIR = "data/backups"
MAX_BACKUPS = 20
# 130 MB: safety guard against absurd payloads. Imported photos are sent
# base64-encoded (+/- 33% size overhead) inside a JSON body, so the limit
# needs to stay generous relative to the actual file size.
MAX_UPLOAD_BYTES = 130 * 1024 * 1024

FILENAME_RE = re.compile(r"^(.+)_(\d{2})-(\d{4})\.(jpe?g|png)$", re.IGNORECASE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pearview")


class ConfigValidationError(Exception):
    """Raised when the received JSON/parameters don't have the expected shape."""


# =============================================================================
# SHARED UTILITIES
# =============================================================================

def is_safe_path_component(name):
    """A place/position name must never allow escaping out of assets/."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name and "\x00" not in name


def validate_config_shape(data):
    """Superficially checks that the received JSON looks like a valid config,
    to avoid overwriting config.json with corrupted data."""
    if not isinstance(data, dict):
        raise ConfigValidationError("The root must be a JSON object (places).")
    for place_key, place_val in data.items():
        if not isinstance(place_val, dict) or "positions" not in place_val:
            raise ConfigValidationError(f"Invalid place '{place_key}': missing 'positions' field.")
        if not isinstance(place_val["positions"], dict):
            raise ConfigValidationError(f"Invalid place '{place_key}': 'positions' must be an object.")


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
        log.info("Removed old backup: %s", oldest)


def make_backup():
    """Copies the current config.json to backups/config_DD-MM-YYYY[_N].json."""
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
    log.info("Backup created: %s", backup_path)
    prune_old_backups()
    return backup_path


def write_config(config):
    """Atomic write via a temp file + replace, to avoid corrupting config.json
    if the process is interrupted mid-write."""
    tmp_path = CONFIG_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONFIG_FILE)


def save_with_backup(raw_bytes):
    """Validates, creates a backup, then writes the new config.json."""
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigValidationError(f"Invalid JSON: {exc}") from exc

    validate_config_shape(data)
    make_backup()
    write_config(data)
    log.info("config.json updated (%d place(s))", len(data))


def prune_dangling_arrows(config, dead_place, dead_position):
    """Removes, across ALL positions of ALL places, any arrows that pointed
    to the position that was just deleted."""
    for place_val in config.values():
        for pos_val in place_val.get("positions", {}).values():
            pos_val["arrows"] = [
                a for a in pos_val.get("arrows", [])
                if not (a.get("targetPlace") == dead_place and a.get("targetPos") == dead_position)
            ]


def compute_file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_duplicate_photo(raw_bytes):
    """Looks for an image with strictly identical content that already
    exists somewhere in assets/ (across all places/positions), regardless
    of its filename. Returns the relative path of the first duplicate found,
    or None. Useful when the same photo gets re-imported by mistake under a
    different filename (hence a different date)."""
    target_hash = hashlib.sha256(raw_bytes).hexdigest()
    assets_dir = generate_config.ASSETS_DIR
    if not os.path.isdir(assets_dir):
        return None
    for root, _dirs, files in os.walk(assets_dir):
        for fname in files:
            if not fname.lower().endswith(generate_config.VALID_EXTENSIONS):
                continue
            fpath = os.path.join(root, fname)
            try:
                if compute_file_hash(fpath) == target_hash:
                    return fpath.replace("\\", "/")
            except OSError:
                continue
    return None


def prune_dangling_place(config, dead_place):
    """Removes, across ALL positions of ALL places, any arrows that pointed
    to the place that was just deleted entirely."""
    for place_val in config.values():
        for pos_val in place_val.get("positions", {}).values():
            pos_val["arrows"] = [a for a in pos_val.get("arrows", []) if a.get("targetPlace") != dead_place]


# =============================================================================
# PHOTO IMPORT (= new position, or new date for an existing position)
# =============================================================================

def handle_upload_photo(payload):
    place = (payload.get("place") or "").strip()
    filename = (payload.get("filename") or "").strip()
    image_b64 = payload.get("imageBase64") or ""
    overwrite = bool(payload.get("overwrite", False))
    allow_duplicate = bool(payload.get("allowDuplicate", False))

    if not place or not filename or not image_b64:
        raise ConfigValidationError("Missing fields (place, filename, imageBase64).")
    if not is_safe_path_component(place):
        raise ConfigValidationError("Invalid place name.")

    match = FILENAME_RE.match(filename)
    if not match:
        raise ConfigValidationError(
            "Invalid file name. Expected format: POSITION_MM-YYYY.jpg "
            "(e.g. garden_08-2026.jpg)."
        )
    position, month_str, year_str, _ext = match.groups()
    month = int(month_str)
    if not (1 <= month <= 12):
        raise ConfigValidationError(f"Invalid month in file name: {month_str}.")
    if not is_safe_path_component(position):
        raise ConfigValidationError("Invalid position name.")

    pos_dir = os.path.join(generate_config.ASSETS_DIR, place, position)
    target_path = os.path.join(pos_dir, filename)

    if os.path.exists(target_path) and not overwrite:
        return {
            "status": "conflict",
            "message": f"The photo \u00ab {filename} \u00bb already exists for {place} / {position}.",
        }

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception as exc:  # binascii.Error and others
        raise ConfigValidationError(f"Invalid image (base64 decoding failed): {exc}") from exc

    if not raw:
        raise ConfigValidationError("Empty image.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ConfigValidationError("Image too large.")

    if not allow_duplicate:
        dup_path = find_duplicate_photo(raw)
        target_rel = target_path.replace("\\", "/")
        if dup_path and dup_path != target_rel:
            return {
                "status": "duplicate",
                "message": f"An image with identical content already exists: {dup_path}",
                "existingPath": dup_path,
            }

    os.makedirs(pos_dir, exist_ok=True)
    tmp_path = target_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(raw)
    os.replace(tmp_path, target_path)
    log.info("Photo saved: %s (%.1f KB)", target_path, len(raw) / 1024)

    # We always regenerate config.json by rescanning assets/: this adds or
    # refreshes the position without ever touching the arrows and info
    # points already configured elsewhere (see generate_config.scan_assets).
    make_backup()
    config = generate_config.build_config()
    write_config(config)

    return {"status": "success", "place": place, "position": position, "config": config}


# =============================================================================
# MANUAL RESCAN (no import) - re-runs generate_config on assets/
# =============================================================================

def handle_rescan():
    """Runs a full scan of assets/ and regenerates config.json accordingly
    (adds/refreshes the places, positions and photos found, without ever
    removing an existing entry - for deletions, see handle_delete_position /
    handle_delete_place)."""
    make_backup()
    config = generate_config.build_config()
    write_config(config)
    log.info("Manual rescan done (%d place(s))", len(config))
    return {"status": "success", "config": config}


# =============================================================================
# RENAMING A PLACE / A POSITION
# =============================================================================

def handle_rename_place(payload):
    old_place = (payload.get("place") or "").strip()
    new_key = (payload.get("newKey") or "").strip()
    new_label = payload.get("newLabel")
    if not old_place:
        raise ConfigValidationError("'place' field required.")

    config = generate_config.load_existing_config()
    if old_place not in config:
        raise ConfigValidationError("Place not found in the configuration.")

    rename_key = bool(new_key) and new_key != old_place
    if rename_key:
        if not is_safe_path_component(new_key):
            raise ConfigValidationError("Invalid new place name.")
        if new_key in config:
            raise ConfigValidationError(f"A place \u00ab {new_key} \u00bb already exists.")
        new_dir = os.path.join(generate_config.ASSETS_DIR, new_key)
        if os.path.exists(new_dir):
            raise ConfigValidationError(f"The folder '{new_dir}' already exists on disk.")

    make_backup()

    working_place = old_place
    if rename_key:
        old_dir = os.path.join(generate_config.ASSETS_DIR, old_place)
        new_dir = os.path.join(generate_config.ASSETS_DIR, new_key)
        if os.path.isdir(old_dir):
            os.rename(old_dir, new_dir)
            log.info("Place folder renamed: %s -> %s", old_dir, new_dir)

        config[new_key] = config.pop(old_place)
        # Propagates the rename to every arrow that pointed to this place.
        for place_val in config.values():
            for pos_val in place_val.get("positions", {}).values():
                for arrow in pos_val.get("arrows", []):
                    if arrow.get("targetPlace") == old_place:
                        arrow["targetPlace"] = new_key
        working_place = new_key

    if new_label is not None and str(new_label).strip():
        config[working_place]["label"] = str(new_label).strip()

    write_config(config)
    log.info("Place renamed/updated: %s -> %s", old_place, working_place)
    return {"status": "success", "config": config, "place": working_place}


def handle_rename_position(payload):
    place = (payload.get("place") or "").strip()
    old_position = (payload.get("position") or "").strip()
    new_key = (payload.get("newKey") or "").strip()

    if not place or not old_position:
        raise ConfigValidationError("'place' and 'position' fields required.")
    if not new_key:
        raise ConfigValidationError("The new position name is required.")
    if not is_safe_path_component(new_key):
        raise ConfigValidationError("Invalid new position name.")

    config = generate_config.load_existing_config()
    if place not in config or old_position not in config.get(place, {}).get("positions", {}):
        raise ConfigValidationError("Place or position not found in the configuration.")

    if new_key == old_position:
        return {"status": "success", "config": config, "place": place, "position": old_position}
    if new_key in config[place]["positions"]:
        raise ConfigValidationError(f"A position \u00ab {new_key} \u00bb already exists in this place.")

    new_dir = os.path.join(generate_config.ASSETS_DIR, place, new_key)
    if os.path.exists(new_dir):
        raise ConfigValidationError(f"The folder '{new_dir}' already exists on disk.")

    make_backup()

    old_dir = os.path.join(generate_config.ASSETS_DIR, place, old_position)
    if os.path.isdir(old_dir):
        os.rename(old_dir, new_dir)
        log.info("Position folder renamed: %s -> %s", old_dir, new_dir)

    config[place]["positions"][new_key] = config[place]["positions"].pop(old_position)
    if config[place].get("defaultPosition") == old_position:
        config[place]["defaultPosition"] = new_key

    # Propagates the rename to every arrow (from any place) that pointed to
    # this position.
    for place_val in config.values():
        for pos_val in place_val.get("positions", {}).values():
            for arrow in pos_val.get("arrows", []):
                if arrow.get("targetPlace") == place and arrow.get("targetPos") == old_position:
                    arrow["targetPos"] = new_key

    write_config(config)
    log.info("Position renamed: %s/%s -> %s", place, old_position, new_key)
    return {"status": "success", "config": config, "place": place, "position": new_key}


# =============================================================================
# DELETING A POSITION / A PLACE
# =============================================================================

def handle_delete_position(payload):
    place = (payload.get("place") or "").strip()
    position = (payload.get("position") or "").strip()
    if not place or not position:
        raise ConfigValidationError("'place' and 'position' fields required.")

    config = generate_config.load_existing_config()
    if place not in config or position not in config.get(place, {}).get("positions", {}):
        raise ConfigValidationError("Place or position not found in the configuration.")

    make_backup()

    pos_dir = os.path.join(generate_config.ASSETS_DIR, place, position)
    if os.path.isdir(pos_dir):
        shutil.rmtree(pos_dir)
        log.info("Position folder deleted: %s", pos_dir)

    del config[place]["positions"][position]
    prune_dangling_arrows(config, place, position)

    place_removed = False
    if not config[place]["positions"]:
        # No positions left in this place: delete it entirely, otherwise it
        # would remain a "ghost" place with no valid defaultPosition.
        place_dir = os.path.join(generate_config.ASSETS_DIR, place)
        if os.path.isdir(place_dir):
            shutil.rmtree(place_dir)
            log.info("Empty place folder deleted: %s", place_dir)
        del config[place]
        prune_dangling_place(config, place)
        place_removed = True
    elif config[place].get("defaultPosition") == position:
        config[place]["defaultPosition"] = next(iter(config[place]["positions"]))

    write_config(config)
    log.info(
        "Position deleted: %s/%s%s",
        place, position, " (place also deleted, no positions left)" if place_removed else "",
    )
    return {"status": "success", "config": config, "placeRemoved": place_removed}


def handle_delete_place(payload):
    place = (payload.get("place") or "").strip()
    if not place:
        raise ConfigValidationError("'place' field required.")

    config = generate_config.load_existing_config()
    if place not in config:
        raise ConfigValidationError("Place not found in the configuration.")

    make_backup()

    place_dir = os.path.join(generate_config.ASSETS_DIR, place)
    if os.path.isdir(place_dir):
        shutil.rmtree(place_dir)
        log.info("Place folder deleted: %s", place_dir)

    del config[place]
    prune_dangling_place(config, place)

    write_config(config)
    log.info("Place deleted: %s", place)
    return {"status": "success", "config": config}


# =============================================================================
# HTTP SERVER
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
        """Reads the request body respecting Content-Length, with safety
        guards. Returns None (and already responds to the client) on error."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json(400, {"status": "error", "message": "Invalid Content-Length header."})
            return None

        if content_length <= 0:
            self._send_json(400, {"status": "error", "message": "Empty request body."})
            return None
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json(413, {"status": "error", "message": "File too large."})
            return None

        return self.rfile.read(content_length)

    def _read_json_body(self):
        raw = self._read_raw_body()
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"status": "error", "message": f"Invalid JSON: {exc}"})
            return None

    def do_POST(self):
        routes = {
            "/api/save-config": self._handle_save_config,
            "/api/upload-photo": self._handle_upload_photo,
            "/api/delete-position": self._handle_delete_position,
            "/api/delete-place": self._handle_delete_place,
            "/api/rescan": self._handle_rescan,
            "/api/rename-place": self._handle_rename_place,
            "/api/rename-position": self._handle_rename_position,
        }
        handler = routes.get(self.path)
        if handler is None:
            self._send_json(404, {"status": "error", "message": "Unknown route."})
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
            log.warning("Save rejected: %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Disk error while saving: %s", exc)
            self._send_json(500, {"status": "error", "message": "Server error while writing the file."})

    def _handle_upload_photo(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_upload_photo(payload)
            status_code = 200 if result.get("status") == "success" else 409
            self._send_json(status_code, result)
        except ConfigValidationError as exc:
            log.warning("Import rejected: %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Disk error while importing: %s", exc)
            self._send_json(500, {"status": "error", "message": "Server error while writing the file."})

    def _handle_delete_position(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_delete_position(payload)
            self._send_json(200, result)
        except ConfigValidationError as exc:
            log.warning("Deletion rejected: %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Disk error while deleting: %s", exc)
            self._send_json(500, {"status": "error", "message": "Server error while deleting."})

    def _handle_delete_place(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_delete_place(payload)
            self._send_json(200, result)
        except ConfigValidationError as exc:
            log.warning("Deletion rejected: %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Disk error while deleting: %s", exc)
            self._send_json(500, {"status": "error", "message": "Server error while deleting."})

    def _handle_rescan(self):
        # No body expected for this route: we don't read it.
        try:
            result = handle_rescan()
            self._send_json(200, result)
        except OSError as exc:
            log.error("Disk error during rescan: %s", exc)
            self._send_json(500, {"status": "error", "message": "Server error during rescan."})

    def _handle_rename_place(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_rename_place(payload)
            self._send_json(200, result)
        except ConfigValidationError as exc:
            log.warning("Rename rejected: %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Disk error during rename: %s", exc)
            self._send_json(500, {"status": "error", "message": "Server error during rename."})

    def _handle_rename_position(self):
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            result = handle_rename_position(payload)
            self._send_json(200, result)
        except ConfigValidationError as exc:
            log.warning("Rename rejected: %s", exc)
            self._send_json(400, {"status": "error", "message": str(exc)})
        except OSError as exc:
            log.error("Disk error during rename: %s", exc)
            self._send_json(500, {"status": "error", "message": "Server error during rename."})


def main():
    try:
        server = HTTPServer((HOST, PORT), PearViewHandler)
    except OSError as exc:
        log.error("Unable to start the server on %s:%s (%s)", HOST, PORT, exc)
        sys.exit(1)

    log.info("PearView running: http://%s:%s (Ctrl+C to stop)", HOST if HOST != "0.0.0.0" else "localhost", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopping the server.")
        server.shutdown()


if __name__ == "__main__":
    main()