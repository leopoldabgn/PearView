#!/usr/bin/env python3
"""
Scanne le dossier assets/ (Lieu/Position/Photos) et génère/enrichit config.json
sans écraser les flèches et points d'information déjà configurés.

Structure attendue :
  assets/<LIEU>/<POSITION>/<POSITION>_<MM-AAAA>.jpg

Ce module est à la fois exécutable en CLI et importable depuis server.py
(fonction build_config()) afin que l'import de photo depuis l'interface web
puisse relancer un scan complet du disque et régénérer config.json de façon
cohérente, sans dupliquer la logique de scan à deux endroits.
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
    """Extrait MM-AAAA du nom de fichier et le convertit en nombre de mois
    pour un tri chronologique fiable. Retourne 0 (et log un avertissement)
    si le nom de fichier ne suit pas la convention attendue."""
    file_name = os.path.basename(file_path)
    name_without_ext = os.path.splitext(file_name)[0]
    parts = name_without_ext.split("_")
    date_str = parts[-1]  # ex: "11-2012"
    try:
        month, year = map(int, date_str.split("-"))
        return year * 12 + month
    except (ValueError, IndexError):
        log.warning("Nom de fichier non conforme (attendu ..._MM-AAAA.jpg) : %s", file_name)
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
        log.warning("config.json existant illisible (%s), un nouveau sera créé.", exc)
        return {}


def scan_assets(config):
    """Parcourt assets/ et met à jour `config` en place (ajoute/actualise les
    lieux, positions et listes de photos). Ne supprime JAMAIS un lieu ou une
    position qui existerait encore dans `config` mais plus sur le disque :
    la suppression est gérée explicitement côté serveur (voir server.py),
    pas par ce scan additif."""
    if not os.path.isdir(ASSETS_DIR):
        log.warning("Dossier '%s' introuvable — rien à scanner.", ASSETS_DIR)
        return config

    for lieu in sorted(os.listdir(ASSETS_DIR)):
        lieu_path = os.path.join(ASSETS_DIR, lieu)
        if not os.path.isdir(lieu_path):
            continue

        if lieu not in config:
            config[lieu] = {"label": lieu, "defaultPosition": "", "positions": {}}
        config[lieu].setdefault("positions", {})
        positions = config[lieu]["positions"]

        for pos in sorted(os.listdir(lieu_path)):
            pos_path = os.path.join(lieu_path, pos)
            if not os.path.isdir(pos_path):
                continue

            if not config[lieu].get("defaultPosition"):
                config[lieu]["defaultPosition"] = pos

            photos = [
                os.path.join(ASSETS_DIR, lieu, pos, f).replace("\\", "/")
                for f in sorted(os.listdir(pos_path))
                if f.lower().endswith(VALID_EXTENSIONS)
            ]
            photos = sort_photos_by_date(photos)

            if not photos:
                log.warning("Aucune photo trouvée pour %s / %s", lieu, pos)

            if pos not in positions:
                positions[pos] = {"photos": photos, "arrows": [], "hotspots": []}
            else:
                # Conserve les flèches / points d'info déjà configurés,
                # ne met à jour que la liste des photos.
                positions[pos]["photos"] = photos
                positions[pos].setdefault("arrows", [])
                positions[pos].setdefault("hotspots", [])

    return config


def build_config():
    """Charge le config.json existant puis le complète en scannant assets/.
    Utilisé aussi bien par le CLI que par server.py après un import de photo."""
    config = load_existing_config()
    config = scan_assets(config)
    return config


def main():
    config = build_config()

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    lieu_count = len(config)
    pos_count = sum(len(v.get("positions", {})) for v in config.values())
    log.info("✅ '%s' généré avec succès : %d lieu(x), %d position(s).", CONFIG_FILE, lieu_count, pos_count)


if __name__ == "__main__":
    main()