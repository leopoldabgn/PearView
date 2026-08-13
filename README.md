# 🍐 PearView

**PearView** is a self-hosted, interactive, and time-travel WebXR 360° virtual tour web application. It allows you to explore locations in immersive VR/360° and travel back and forth in time to compare different eras from the exact same place.

![Version](https://img.shields.io/badge/version-1.0.0-emerald)
![Docker](https://img.shields.io/badge/Docker-ready-blue)
![A-Frame](https://img.shields.io/badge/VR-A--Frame-pink)

---

## ✨ Features

* **WebXR / 360° VR Navigation**: Smooth exploration of 360° panoramas powered by [A-Frame](https://aframe.io/).
* **Time Selector ("Time Travel")**: Instant switching between different dates (years/months) for any given place.
* **Built-in Visual Editor**:
  * **Navigation Arrows**: Place and align inter-place links directly in 3D space with step-by-step adjustments (nudge).
  * **Info Hotspots**: Add interactive markers (title, text, image pop-ups).
* **Database-free Content Management**:
  * **Drag-and-Drop Import**: Direct upload from the UI featuring duplicate detection (SHA-256 hash) and conflict handling.
  * **Renaming & Deletion**: Hot-renaming of locations and places with instant filesystem folder updates and linked arrow synchronization.
  * **Automatic Rescan**: Cron job running every 5 minutes to keep the configuration updated if files are manually added to disk.
* **Security & Resilience**: Atomic config file writes and automated timestamped backups (`data/backups/`).

---

## 🛠️ Prerequisites

* **Docker** and **Docker Compose** installed on your host system.
* *Non-Docker Alternative*: Python 3.11+ (uses standard library only—no `pip` dependencies required).

---

## 🚀 Quick Start (Docker)

### 1. Clone the repository
```bash
git clone https://github.com/leopoldabgn/PearView.git
cd PearView
```

### 2. Start the application

```bash
docker compose up -d --build
```

The application will be immediately accessible at **`http://localhost:1500`** (or your server's IP address).

---

## 📁 File Naming Convention

For automatic scanning to properly map dates and places, 360° photos must strictly follow this naming convention:

```text
PLACE_MM-YYYY.jpg
```

### Example structure inside `data/assets/`:

```text
data/
└── assets/
    ├── House/
    │   ├── garden/
    │   │   ├── garden_08-2020.jpg
    │   │   └── garden_08-2026.jpg
    │   └── entrance/
    │       └── entrance_01-2024.png
    └── arrow.png
```

---

## User Guide

### Viewer Mode

* **Navigation**: Click ground arrows to move between places or locations.
* **Compass**: Follow the top-right compass indicator to keep your bearings.
* **Time Travel**: Use the date selector (or the `A`/`B` buttons on VR controllers) to switch years/months.

### Editor Mode (🛠️)

1. Check **Editor Mode** in the top-left panel.
2. Aim the central crosshair at a spot on the floor.
3. Click **➕ Navigation Arrow** or **ℹ️ Info Hotspot**.
4. Adjust position, rotation, and target place in the modal pop-up.
5. Click **💾 Save to Server** to persist your changes.

---

## ⚙️ Useful Commands & CLI

### Manually Regenerate Configuration

You can trigger a manual scan of on-disk photos at any time:

* **Via the Web Interface**: Click the `🔄 Rescan assets/` button in Editor Mode.
* **Via Command Line (inside container)**:

```bash
docker exec -it pearview python3 generate_config.py
```

### Environment Variables (in `docker-compose.yml`)

| Variable | Default Value | Description |
| --- | --- | --- |
| `PEARVIEW_PORT` | `1500` | HTTP server listening port |
| `PEARVIEW_HOST` | `0.0.0.0` | Server binding host address |

---

## 🏗️ Project Architecture

```text
 PearView/
 ├── data/                  # Persistent volume (Docker mount)
 │   ├── assets/            # Directory containing your photos (Location/Place/...)
 │   ├── backups/           # Automated backups (config_DD-MM-YYYY.json)
 │   └── config.json        # Main generated configuration file
 ├── lib/                   # Local JS dependencies (A-Frame)
 ├── Dockerfile             # Docker image (Python Slim + Cron)
 ├── docker-compose.yml     # Docker service configuration
 ├── entrypoint.sh          # Container initialization script
 ├── generate_config.py     # Asset scanning and config generation script
 ├── server.py              # Python standard HTTP server & REST API
 └── index.html             # WebGL / A-Frame Frontend application
```

---

## 📄 License

```
This project is licensed under the MIT License. Feel free to use, modify, and self-host it.
```
