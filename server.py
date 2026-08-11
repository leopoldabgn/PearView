import os
import json
import shutil
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 8000
BACKUP_DIR = 'backup'
MAX_BACKUPS = 20

def save_with_backup(data_bytes):
    # 1. Créer le dossier backup s'il n'existe pas
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    # 2. Si un config.json existe déjà, on en fait une backup horodatée
    if os.path.exists('config.json'):
        today_str = datetime.now().strftime("%d-%m-%Y")
        backup_filename = f"config_{today_str}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        # Si le fichier du jour existe déjà, on incrémente (_2, _3, ...)
        counter = 2
        while os.path.exists(backup_path):
            backup_filename = f"config_{today_str}_{counter}.json"
            backup_path = os.path.join(BACKUP_DIR, backup_filename)
            counter += 1

        shutil.copy('config.json', backup_path)
        print(f"📦 Backup créée : {backup_path}")

        # 3. Nettoyer les vieux fichiers si > 20
        all_backups = [
            os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)
            if f.startswith('config_') and f.endswith('.json')
        ]
        # Trier par date de modification (les plus anciens en premier)
        all_backups.sort(key=os.path.getmtime)

        while len(all_backups) > MAX_BACKUPS:
            oldest = all_backups.pop(0)
            os.remove(oldest)
            print(f"🗑️ Plus de {MAX_BACKUPS} sauvegardes : suppression de la plus ancienne ({oldest})")

    # 4. Écrire le nouveau config.json
    data = json.loads(data_bytes.decode('utf-8'))
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("💾 config.json mis à jour avec succès !")


class CustomHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/save-config':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                save_with_backup(post_data)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "success"}')
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), CustomHandler)
    print(f"🚀 Serveur actif sur le port {PORT} : http://localhost:{PORT}")
    server.serve_forever()