#!/usr/bin/env python3
"""
Scans the assets/ folder (Place/Position/Photos) and generates/enriches
config.json without overwriting the arrows, info points and ambient music
already configured.

Expected structure:
  assets/<PLACE>/<POSITION>/<POSITION>_<MM-YYYY>.jpg

This module is both runnable as a CLI and importable from server.py
(build_config() function) so that importing a photo from the web interface
can trigger a full disk rescan and regenerate config.json consistently,
without duplicating the scan logic in two places.
"""

import json
import logging
import os

CONFIG_FILE = "data/config.json"
ASSETS_DIR = "data/assets"
VALID_EXTENSIONS = (".jpg", ".jpeg", ".png")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("generate_config")


def date_sort_key(file_path):
    """Extracts MM-YYYY from the file name and converts it to a month count
    for reliable chronological sorting. Returns 0 (and logs a warning) if
    the file name doesn't follow the expected convention."""
    file_name = os.path.basename(file_path)
    name_without_ext = os.path.splitext(file_name)[0]
    parts = name_without_ext.split("_")
    date_str = parts[-1]  # e.g. "11-2012"
    try:
        month, year = map(int, date_str.split("-"))
        return year * 12 + month
    except (ValueError, IndexError):
        log.warning("Non-conforming file name (expected ..._MM-YYYY.jpg): %s", file_name)
        return 0


def sort_photos_by_date(photo_list):
    return sorted(photo_list, key=date_sort_key)


def load_existing_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Existing config.json is unreadable (%s), a new one will be created.", exc)
        return {}


def scan_assets(config):
    """Walks through assets/ and updates `config` in place (adds/refreshes
    places, positions and photo lists). NEVER removes a place or position
    that would still exist in `config` but no longer on disk: deletion is
    handled explicitly server-side (see server.py), not by this additive
    scan. Likewise, it NEVER touches the arrows, hotspots or ambient music
    ("music" field) already configured for an existing position - only the
    `photos` list is refreshed."""
    if not os.path.isdir(ASSETS_DIR):
        log.warning("Folder '%s' not found - nothing to scan.", ASSETS_DIR)
        return config

    for place in sorted(os.listdir(ASSETS_DIR)):
        place_path = os.path.join(ASSETS_DIR, place)
        if not os.path.isdir(place_path):
            continue

        if place not in config:
            config[place] = {"label": place, "defaultPosition": "", "positions": {}}
        config[place].setdefault("positions", {})
        positions = config[place]["positions"]

        for pos in sorted(os.listdir(place_path)):
            pos_path = os.path.join(place_path, pos)
            if not os.path.isdir(pos_path):
                continue

            if not config[place].get("defaultPosition"):
                config[place]["defaultPosition"] = pos

            photos = [
                os.path.join(ASSETS_DIR, place, pos, f).replace("\\", "/")
                for f in sorted(os.listdir(pos_path))
                if f.lower().endswith(VALID_EXTENSIONS)
            ]
            photos = sort_photos_by_date(photos)

            if not photos:
                log.warning("No photo found for %s / %s", place, pos)

            if pos not in positions:
                # "music" is the path (e.g. "data/music/<hash>.mp3") of the
                # ambient sound looped for this position, across all of its
                # dates. None means "no ambient music configured".
                positions[pos] = {"photos": photos, "arrows": [], "hotspots": [], "music": None}
            else:
                # Keeps the arrows / info points / ambient music already
                # configured, only refreshes the photo list.
                positions[pos]["photos"] = photos
                positions[pos].setdefault("arrows", [])
                positions[pos].setdefault("hotspots", [])
                positions[pos].setdefault("music", None)

    return config


def build_config():
    """Loads the existing config.json then completes it by scanning assets/.
    Used both by the CLI and by server.py after a photo import."""
    config = load_existing_config()
    config = scan_assets(config)
    return config


def main():
    config = build_config()

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    place_count = len(config)
    pos_count = sum(len(v.get("positions", {})) for v in config.values())
    log.info("\u2705 '%s' successfully generated: %d place(s), %d position(s).", CONFIG_FILE, place_count, pos_count)


if __name__ == "__main__":
    main()