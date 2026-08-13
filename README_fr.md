# 🍐 PearView

**PearView** est une application web auto-hébergée de visite virtuelle 360° interactive et temporelle. Elle permet d'explorer des lieux en immersion VR/360° et de voyager dans le temps en comparant différentes époques d'une même position.

![Version](https://img.shields.io/badge/version-1.0.0-emerald)
![Docker](https://img.shields.io/badge/Docker-ready-blue)
![A-Frame](https://img.shields.io/badge/VR-A--Frame-pink)

---

## ✨ Fonctionnalités

* **Navigation WebXR / VR 360°** : Exploration fluide de panoramas 360° basée sur [A-Frame](https://aframe.io/).
* **Sélecteur Temporel ("Voyage dans le temps")** : Passage instantané entre différentes dates (années/mois) pour une même position.
* **Éditeur Visuel Intégré** :
  * **Flèches de navigation** : Pose et orientation de liens inter-positions directement dans l'espace 3D avec ajustement pas-à-pas (nudge).
  * **Points d'information (Hotspots)** : Ajout de marqueurs interactifs (titre, texte, image modale).
* **Gestion de Contenu sans Base de Données** :
  * **Import Glisser-Déposer** : Téléversement direct depuis l'UI avec détection de doublons (hash SHA-256) et gestion des conflits.
  * **Renommage & Suppression** : Renommage à chaud des lieux et positions avec répercussion automatique des dossiers sur le disque et des flèches liées.
  * **Rescan Automatique** : Tâche Cron (toutes les 5 min) pour mettre à jour la configuration en cas d'ajout manuel de fichiers sur le disque.
* **Sécurité & Résilience** : Écriture atomique des fichiers de configuration et sauvegardes horodatées automatiques (`data/backups/`).

---

## 🛠️ Prérequis

* **Docker** et **Docker Compose** installés sur votre machine.
* *Alternative hors Docker* : Python 3.11+ (bibliothèque standard uniquement, aucune dépendance `pip` requise).

---

## 🚀 Installation Rapide (Docker)

### 1. Cloner le projet
```bash
git clone https://github.com/leopoldabgn/PearView.git
cd PearView
```

### 2. Démarrer l'application

```bash
docker compose up -d --build
```

L'application est immédiatement accessible à l'adresse : **`http://localhost:1500`** (ou l'IP de votre serveur).

---

## 📁 Convention de Nommage des Fichiers

Pour que le scan automatique associe correctement les dates et positions, les photos 360° doivent être nommées selon la convention suivante :

```text
POSITION_MM-AAAA.jpg
```

### Exemple de structure sous `data/assets/` :

```text
data/
└── assets/
    ├── Maison/
    │   ├── jardin/
    │   │   ├── jardin_08-2020.jpg
    │   │   └── jardin_08-2026.jpg
    │   └── entree/
    │       └── entree_01-2024.png
    └── fleche.png
```

---

## Guide d'Utilisation

### Mode Consultation

* **Navigation** : Cliquez sur les flèches au sol pour changer de position ou de lieu.
* **Boussole** : Suivez le cap en haut à droite pour vous repérer.
* **Époque** : Utilisez le sélecteur de date (ou les boutons `A`/`B` sur manettes VR) pour changer d'année/mois.

### Mode Éditeur (🛠️)

1. Cochez **Mode Éditeur** dans le panneau supérieur gauche.
2. Visez un endroit au sol avec le viseur central.
3. Cliquez sur **➕ Flèche de navigation** ou **ℹ️ Point d'information**.
4. Ajustez la position, la rotation et la cible de l'élément dans la modale.
5. Cliquez sur **💾 Sauvegarder sur le serveur** pour persister vos modifications.

---

## ⚙️ Commandes Utiles & CLI

### Régénérer la configuration manuellement

Vous pouvez relancer le scan des photos sur le disque à tout moment :

* **Depuis l'interface web** : Bouton `🔄 Rescanner assets/` dans le mode éditeur.
* **En ligne de commande (dans le conteneur)** :
```bash
docker exec -it pearview python3 generate_config.py
```

### Variables d'Environnement (dans `docker-compose.yml`)

| Variable | Valeur par défaut | Description |
| --- | --- | --- |
| `PEARVIEW_PORT` | `1500` | Port d'écoute du serveur HTTP |
| `PEARVIEW_HOST` | `0.0.0.0` | Adresse de liaison du serveur |

---

## 🏗️ Architecture du Projet

```text
 PearView/
 ├── data/                  # Volume persistant (Montage Docker)
 │   ├── assets/            # Dossier contenant vos photos (Lieu/Position/...)
 │   ├── backups/           # Sauvegardes automatiques (config_JJ-MM-AAAA.json)
 │   └── config.json        # Fichier de configuration principal généré
 ├── lib/                   # Dépendances JS locales (A-Frame)
 ├── Dockerfile             # Image Docker (Python Slim + Cron)
 ├── docker-compose.yml     # Configuration du service Docker
 ├── entrypoint.sh          # Script d'initialisation du conteneur
 ├── generate_config.py     # Script de scan et génération du config.json
 ├── server.py              # Serveur HTTP standard Python & API REST
 └── index.html             # Application Frontend WebGL / A-Frame
```

---

## 📄 Licence

```
Ce projet est sous licence MIT. Libre à vous de l'utiliser, le modifier et l'héberger.
```