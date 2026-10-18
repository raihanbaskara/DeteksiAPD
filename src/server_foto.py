"""
server_foto.py — Server Foto Lokal SafeK3-Cam + ngrok
=======================================================
Menggunakan ngrok.exe langsung (lebih stabil dari pyngrok)

Cara pakai:
    1. Download ngrok.exe dari https://ngrok.com/download
    2. Taruh ngrok.exe di folder ini
    3. Jalankan: ngrok config add-authtoken TOKEN_KAMU
    4. Jalankan: python server_foto.py

Install dependencies:
    pip install flask flask-cors firebase-admin requests
"""

import os
import sys
import time
import json
import subprocess
import threading
import requests
from datetime import datetime
from flask import Flask, send_from_directory, jsonify, abort
from flask_cors import CORS

# Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("⚠️  Jalankan: pip install firebase-admin")

# ============================================================
# KONFIGURASI
# ============================================================
FOTO_DIR   = "safek3_logs"
FLASK_PORT = 5050

def _find_path(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[0]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

FIREBASE_SERVICE_ACCOUNT = _find_path([
    os.path.join(PROJECT_ROOT, "config", "serviceAccountKey.json"),
    os.path.join(PROJECT_ROOT, "serviceAccountKey.json"),
    "config/serviceAccountKey.json",
    "serviceAccountKey.json"
])
FIREBASE_DATABASE_URL    = "https://safecam-b2d73-72774-default-rtdb.asia-southeast1.firebasedatabase.app"

# Path ke ngrok.exe — kalau taruh di folder yang sama biarkan begini
NGROK_PATH = "ngrok.exe"
# ============================================================

app      = Flask(__name__)
CORS(app)
NGROK_URL = ""


# ── Endpoints Flask ──────────────────────────────────────────

@app.route("/status")
def status():
    jumlah = len([f for f in os.listdir(FOTO_DIR)
                  if f.endswith('.jpg')]) if os.path.exists(FOTO_DIR) else 0
    return jsonify({
        "status"     : "online",
        "ngrok_url"  : NGROK_URL,
        "jumlah_foto": jumlah,
        "waktu"      : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

@app.route("/foto/<filename>")
def serve_foto(filename):
    if not filename.endswith('.jpg'):
        abort(403)
    if '..' in filename or '/' in filename or '\\' in filename:
        abort(403)
    return send_from_directory(os.path.abspath(FOTO_DIR), filename)

@app.route("/daftar")
def daftar():
    if not os.path.exists(FOTO_DIR):
        return jsonify({"foto": []})
    files = sorted([f for f in os.listdir(FOTO_DIR)
                    if f.endswith('.jpg')], reverse=True)
    return jsonify({"jumlah": len(files), "foto": files})


# ── Firebase ─────────────────────────────────────────────────

def init_firebase():
    if not FIREBASE_AVAILABLE:
        return False
    if not os.path.exists(FIREBASE_SERVICE_ACCOUNT):
        print(f"⚠️  {FIREBASE_SERVICE_ACCOUNT} tidak ditemukan.")
        return False
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
            firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DATABASE_URL})
        print("✅ Firebase terhubung!")
        return True
    except Exception as e:
        print(f"⚠️  Firebase gagal: {e}")
        return False

def simpan_url_ke_firebase(url):
    try:
        firebase_db.reference("server_config").set({
            "ngrok_url" : url,
            "port"      : FLASK_PORT,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status"    : "online",
        })
        print(f"✅ URL tersimpan di Firebase!")
    except Exception as e:
        print(f"⚠️  Gagal simpan URL ke Firebase: {e}")

def set_offline():
    try:
        firebase_db.reference("server_config/status").set("offline")
        print("🔴 Status server di Firebase: offline")
    except Exception:
        pass


# ── ngrok via subprocess ──────────────────────────────────────

def get_ngrok_url(timeout=15):
    """Ambil URL publik ngrok dari API lokal ngrok."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=2)
            data = resp.json()
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                url = t.get("public_url", "")
                if url.startswith("https://"):
                    return url
            # Kalau ada tapi http, convert ke https
            for t in tunnels:
                url = t.get("public_url", "")
                if url.startswith("http://"):
                    return url.replace("http://", "https://", 1)
        except Exception:
            pass
        time.sleep(1)
    return None

def start_ngrok_process():
    """Jalankan ngrok.exe sebagai subprocess."""
    global NGROK_URL

    # Cek apakah ngrok.exe ada
    if not os.path.exists(NGROK_PATH):
        # Coba cari di PATH sistem
        import shutil
        ngrok_in_path = shutil.which("ngrok")
        if not ngrok_in_path:
            print("⚠️  ngrok.exe tidak ditemukan!")
            print("    Download dari: https://ngrok.com/download")
            print("    Taruh ngrok.exe di folder yang sama dengan server_foto.py")
            return None

    try:
        ngrok_exe = NGROK_PATH if os.path.exists(NGROK_PATH) else "ngrok"
        cmd = [ngrok_exe, "http", str(FLASK_PORT), "--log=stdout"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        print("🚇 ngrok sedang membuka tunnel...")
        url = get_ngrok_url(timeout=20)
        if url:
            NGROK_URL = url
            print(f"✅ ngrok tunnel aktif!")
            print(f"   URL Publik : {NGROK_URL}")
            print(f"   Test akses : {NGROK_URL}/status")
            return proc
        else:
            print("⚠️  Timeout menunggu ngrok. Coba jalankan manual:")
            print(f"    ngrok http {FLASK_PORT}")
            proc.terminate()
            return None
    except Exception as e:
        print(f"⚠️  Gagal jalankan ngrok: {e}")
        return None


# ── Flask di thread terpisah ──────────────────────────────────

def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)   # sembunyikan log request Flask
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False)


# ── Main ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  SafeK3-Cam  |  Server Foto + ngrok Tunnel")
    print("=" * 55)

    os.makedirs(FOTO_DIR, exist_ok=True)
    jumlah = len([f for f in os.listdir(FOTO_DIR) if f.endswith('.jpg')])
    print(f"  📁 Folder foto : ./{FOTO_DIR}/ ({jumlah} foto)")
    print(f"  🌐 Port        : {FLASK_PORT}")
    print()

    # Start Flask di background thread dulu
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)   # tunggu Flask siap
    print("✅ Flask server jalan di port", FLASK_PORT)

    # Init Firebase
    fb_ok = init_firebase()

    # Start ngrok
    print()
    print("🚇 Memulai ngrok tunnel...")
    ngrok_proc = start_ngrok_process()

    # Simpan URL ke Firebase
    if fb_ok and NGROK_URL:
        simpan_url_ke_firebase(NGROK_URL)
        print()
        print("=" * 55)
        print("  ✅ SISTEM SIAP!")
        print(f"  URL Publik : {NGROK_URL}")
        print(f"  Foto dapat diakses dari internet:")
        print(f"  {NGROK_URL}/foto/nama_file.jpg")
        print("=" * 55)
    elif not NGROK_URL:
        print()
        print("  ⚠️  Foto tidak bisa diakses dari internet.")
        print("  Dashboard tetap tampil log, tapi kolom foto kosong.")

    print()
    print("  Jalankan safek3_webcam.py di terminal lain.")
    print("  Tekan Ctrl+C untuk berhenti.")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Server dihentikan.")
        if fb_ok:
            set_offline()
        if ngrok_proc:
            ngrok_proc.terminate()
        sys.exit(0)
