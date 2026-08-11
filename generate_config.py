import os
import json

CONFIG_FILE = 'config.json'
ASSETS_DIR = 'assets'

# 1. Charger la config existante si elle existe
config = {}
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        try:
            config = json.load(f)
        except Exception:
            config = {}

# 2. Scanner le dossier assets/
if os.path.exists(ASSETS_DIR):
    for lieu in sorted(os.listdir(ASSETS_DIR)):
        lieu_path = os.path.join(ASSETS_DIR, lieu)
        if not os.path.isdir(lieu_path):
            continue

        # Nouveau lieu découvert
        if lieu not in config:
            config[lieu] = {
                "label": lieu, # Nom par défaut (ex: "LIEU1")
                "defaultPosition": "",
                "positions": {}
            }

        positions = config[lieu]["positions"]

        for pos in sorted(os.listdir(lieu_path)):
            pos_path = os.path.join(lieu_path, pos)
            if not os.path.isdir(pos_path):
                continue

            # Définir la première position comme position par défaut si non configurée
            if not config[lieu]["defaultPosition"]:
                config[lieu]["defaultPosition"] = pos

            # Lister toutes les photos JPG de cette position
            photos = [
                os.path.join(ASSETS_DIR, lieu, pos, f).replace('\\', '/')
                for f in sorted(os.listdir(pos_path))
                if f.lower().endswith(('.jpg', '.jpeg'))
            ]

            # Nouvelle position découverte
            if pos not in positions:
                positions[pos] = {
                    "photos": photos,
                    "arrows": [] # Flèches vides par défaut
                }
            else:
                # Mise à jour de la liste des photos (conserve les flèches existantes)
                positions[pos]["photos"] = photos

# 3. Sauvegarder dans config.json
with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print("✅ Configuration 'config.json' générée avec succès !")