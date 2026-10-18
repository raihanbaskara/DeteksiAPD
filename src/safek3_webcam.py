"""
SafeK3-Cam — Deteksi Helm & Vest Real-time via Webcam + ESP32 Buzzer
======================================================================
Model  : YOLOv8 (best.pt)
Class  : 0 = Hardhat (Helm), 1 = Mask (Vest)

Fitur:
- Deteksi real-time dari webcam
- Peringatan teks di layar kalau helm/vest tidak terdeteksi
- Simpan log pelanggaran (CSV) + screenshot otomatis (lokal)
- Kirim log pelanggaran ke Firebase Realtime Database ✅ BARU
- Upload foto pelanggaran ke Firebase Storage ✅ BARU
- Buzzer ESP32 ON terus-menerus selama Helm/Vest tidak terdeteksi,
  dan OFF saat keduanya terdeteksi

Cara pakai:
    python safek3_webcam.py
    python safek3_webcam.py --model path/ke/best.pt --camera 0
    python safek3_webcam.py --esp32-ip 192.168.1.50

Install dependencies tambahan:
    pip install firebase-admin
"""

import cv2
import csv
import os
import time
import argparse
import threading
import requests
import json
from datetime import datetime
from ultralytics import YOLO

# ── Firebase Admin SDK ───────────────────────────────────────
try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db, storage
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("⚠️  firebase-admin belum terinstall.")
    print("    Jalankan: pip install firebase-admin")
    print("    Data pelanggaran hanya disimpan lokal.\n")

# ============================================================
# 🔧 KONFIGURASI — SESUAIKAN BAGIAN INI
# ============================================================
def _find_path(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[0]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

DEFAULT_MODEL_PATH = _find_path([
    os.path.join(PROJECT_ROOT, "models", "best.pt"),
    os.path.join(BASE_DIR, "models", "best.pt"),
    "models/best.pt",
    "best.pt"
])

CONF_THRESHOLD     = 0.5
ALERT_COOLDOWN_SEC = 5
OUTPUT_DIR         = "safek3_logs"
LOG_FILE           = "violation_log.csv"

# ── ESP32 ────────────────────────────────────────────────────
DEFAULT_ESP32_IP      = "192.168.1.100"
ESP32_REQUEST_TIMEOUT = 1.5
ESP32_RESEND_INTERVAL = 2.0

# ── Firebase ─────────────────────────────────────────────────
FIREBASE_SERVICE_ACCOUNT = _find_path([
    os.path.join(PROJECT_ROOT, "config", "serviceAccountKey.json"),
    os.path.join(PROJECT_ROOT, "serviceAccountKey.json"),
    "config/serviceAccountKey.json",
    "serviceAccountKey.json"
])

# URL Realtime Database kamu
FIREBASE_DATABASE_URL = "https://safecam-b2d73-72774-default-rtdb.asia-southeast1.firebasedatabase.app"

# Nama bucket Storage (dari Firebase Console → Storage)
# Format: nama-project.firebasestorage.app
FIREBASE_STORAGE_BUCKET = "safecam-b2d73-72774.firebasestorage.app"

# Node di Realtime Database tempat log disimpan
FIREBASE_LOG_NODE = "logs_pelanggaran"

# Zona kamera (bebas diisi, tampil di dashboard)
CAMERA_ZONE = "Area Produksi"
# ============================================================

CLASS_DISPLAY_NAMES = {
    "Hardhat": "Helmet",
    "Mask":    "Vest",
}

COLOR_OK      = (60, 200, 60)
COLOR_WARN    = (0, 0, 255)
COLOR_TEXT_BG = (0, 0, 0)


# ============================================================
# FIREBASE INTEGRATION
# ============================================================
class FirebaseUploader:
    """Upload log + foto pelanggaran ke Firebase secara non-blocking."""

    def __init__(self):
        self.ready = False
        self._init_firebase()

    def _init_firebase(self):
        if not FIREBASE_AVAILABLE:
            return

        if not os.path.exists(FIREBASE_SERVICE_ACCOUNT):
            print(f"⚠️  File service account tidak ditemukan: {FIREBASE_SERVICE_ACCOUNT}")
            print("    → Data hanya disimpan lokal. Lihat README untuk setup Firebase.")
            return

        try:
            cred = credentials.Certificate(FIREBASE_SERVICE_ACCOUNT)
            firebase_admin.initialize_app(cred, {
                "databaseURL"   : FIREBASE_DATABASE_URL,
                "storageBucket" : FIREBASE_STORAGE_BUCKET,
            })
            self.ready = True
            print("✅ Firebase terhubung!")
            print(f"   Database : {FIREBASE_DATABASE_URL}")
            print(f"   Storage  : {FIREBASE_STORAGE_BUCKET}")
        except Exception as e:
            print(f"⚠️  Gagal inisialisasi Firebase: {e}")

    def upload(self, screenshot_path: str, timestamp: str,
               helmet_ok: bool, vest_ok: bool, confidence: float,
               pelanggaran: list):
        """Upload foto + log ke Firebase di thread terpisah."""
        if not self.ready:
            return
        threading.Thread(
            target=self._do_upload,
            args=(screenshot_path, timestamp, helmet_ok, vest_ok, confidence, pelanggaran),
            daemon=True
        ).start()

    def _do_upload(self, screenshot_path, timestamp, helmet_ok, vest_ok, confidence, pelanggaran):
        foto_url = ""

        # 1️⃣  Upload foto ke Firebase Storage
        try:
            bucket    = storage.bucket()
            filename  = os.path.basename(screenshot_path)
            blob      = bucket.blob(f"violations/{filename}")
            blob.upload_from_filename(screenshot_path, content_type="image/jpeg")
            blob.make_public()
            foto_url  = blob.public_url
            print(f"   📤 Foto terupload → {foto_url}")
        except Exception as e:
            print(f"   ⚠️  Gagal upload foto: {e}")

        # 2️⃣  Kirim log ke Realtime Database
        try:
            ref = firebase_db.reference(FIREBASE_LOG_NODE)
            ref.push({
                "waktu"      : timestamp,            # "2025-01-15 08:32:11"
                "zona"       : CAMERA_ZONE,
                "pelanggaran": pelanggaran,           # ["Helmet"] / ["Vest"] / ["Helmet","Vest"]
                "confidence" : round(confidence, 3),
                "url_foto"   : foto_url,
                "helmet_ok"  : helmet_ok,
                "vest_ok"    : vest_ok,
            })
            print(f"   📊 Log terkirim ke Firebase ({', '.join(pelanggaran)})")
        except Exception as e:
            print(f"   ⚠️  Gagal kirim log ke Firebase: {e}")


# ============================================================
# ESP32 COMMUNICATION
# ============================================================
class ESP32Buzzer:
    def __init__(self, ip: str):
        self.ip              = ip
        self.url             = f"http://{ip}"
        self.online          = False
        self.last_sent_state = None
        self.last_sent_time  = 0.0

    def check_connection(self) -> bool:
        try:
            resp = requests.get(f"{self.url}/status", timeout=ESP32_REQUEST_TIMEOUT)
            if resp.status_code == 200:
                self.online = True
                data = resp.json()
                print(f"✅ ESP32 terhubung di {self.ip}")
                print(f"   Device : {data.get('device', '-')}")
                print(f"   Buzzer : {data.get('buzzer', '-')}")
                return True
        except Exception as e:
            self.online = False
            print(f"⚠️  ESP32 tidak terjangkau di {self.ip} ({e})")
            print(f"   Deteksi tetap berjalan, buzzer tidak aktif.")
        return False

    def _send(self, alert_type: str):
        def _do():
            try:
                requests.get(f"{self.url}/alert",
                             params={"type": alert_type},
                             timeout=ESP32_REQUEST_TIMEOUT)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    def update(self, is_violation: bool):
        if not self.online:
            return
        state           = "violation" if is_violation else "clear"
        now             = time.time()
        state_changed   = (state != self.last_sent_state)
        time_for_resend = (now - self.last_sent_time) >= ESP32_RESEND_INTERVAL
        if state_changed or time_for_resend:
            self._send(state)
            self.last_sent_state = state
            self.last_sent_time  = now


# ============================================================
# LOGGING & DRAWING
# ============================================================
def setup_output_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log_path = os.path.join(OUTPUT_DIR, LOG_FILE)
    if not os.path.exists(log_path):
        with open(log_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "zona", "pelanggaran", "helmet_ok", "vest_ok", "screenshot_file", "firebase_status"])
    return log_path


def draw_label(frame, text, x, y, color):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(frame, (x, y - th - 8), (x + tw + 6, y), color, -1)
    cv2.putText(frame, text, (x + 3, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


def draw_status_banner(frame, helmet_ok, vest_ok, esp32_online, firebase_ready):
    h, w = frame.shape[:2]
    violations = []
    if not helmet_ok: violations.append("Helm")
    if not vest_ok:   violations.append("Vest")

    if violations:
        text  = f"PERINGATAN: {' & '.join(violations)} tidak terdeteksi! (Buzzer ON)"
        color = COLOR_WARN
    else:
        text  = "AMAN - Helm & Vest terdeteksi (Buzzer OFF)"
        color = COLOR_OK

    cv2.rectangle(frame, (0, 0), (w, 40), COLOR_TEXT_BG, -1)
    cv2.putText(frame, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    # Indikator ESP32
    esp_text  = "ESP32: Online" if esp32_online else "ESP32: Offline"
    esp_color = (60, 200, 60) if esp32_online else (0, 100, 255)
    (tw, _), _ = cv2.getTextSize(esp_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(frame, esp_text, (w - tw - 10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, esp_color, 1)

    # Indikator Firebase
    fb_text  = "Firebase: Online" if firebase_ready else "Firebase: Offline"
    fb_color = (60, 200, 60) if firebase_ready else (0, 100, 255)
    (tw2, _), _ = cv2.getTextSize(fb_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.putText(frame, fb_text, (w - tw2 - 10, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, fb_color, 1)

    return len(violations) > 0


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="SafeK3-Cam + Firebase Integration")
    parser.add_argument("--model",    default=DEFAULT_MODEL_PATH)
    parser.add_argument("--camera",   type=int, default=0)
    parser.add_argument("--conf",     type=float, default=CONF_THRESHOLD)
    parser.add_argument("--esp32-ip", default=DEFAULT_ESP32_IP)
    parser.add_argument("--no-esp32", action="store_true")
    parser.add_argument("--zone",     default=CAMERA_ZONE, help="Nama zona kamera")
    args = parser.parse_args()

    # Update zona dari argumen jika ada
    global CAMERA_ZONE
    CAMERA_ZONE = args.zone

    print("=" * 55)
    print("  SafeK3-Cam  |  Helm & Vest Detection + Firebase")
    print("=" * 55)

    print(f"\n📦 Loading model: {args.model}")
    model    = YOLO(args.model)
    log_path = setup_output_dirs()

    # ── Init Firebase ────────────────────────────────────────
    print("\n🔥 Menghubungkan ke Firebase...")
    fb = FirebaseUploader()

    # ── Init ESP32 ───────────────────────────────────────────
    esp32 = ESP32Buzzer(args.esp32_ip)
    if not args.no_esp32:
        print(f"\n🔌 Mengecek koneksi ESP32 di {args.esp32_ip}...")
        esp32.check_connection()
    else:
        print("\n⏭️  Mode --no-esp32: buzzer dilewati.")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"❌ Tidak bisa membuka kamera index {args.camera}")
        return

    print(f"\n▶️  Deteksi berjalan... Tekan 'q' untuk berhenti.")
    print(f"   Zona   : {CAMERA_ZONE}")
    print(f"   Log    : {log_path}")
    print(f"   Foto   : {OUTPUT_DIR}/\n")

    last_alert_time = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ Gagal membaca frame dari kamera")
            break

        results = model(frame, conf=args.conf, verbose=False)[0]

        helmet_detected = False
        vest_detected   = False
        max_conf        = 0.0

        for box in results.boxes:
            x1, y1, x2, y2  = map(int, box.xyxy[0])
            conf             = float(box.conf[0])
            cls_id           = int(box.cls[0])
            raw_name         = model.names[cls_id]
            display_name     = CLASS_DISPLAY_NAMES.get(raw_name, raw_name)

            if raw_name == "Hardhat": helmet_detected = True
            elif raw_name == "Mask":  vest_detected   = True
            if conf > max_conf:       max_conf = conf

            label = f"{display_name} {conf:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), COLOR_OK, 2)
            draw_label(frame, label, x1, y1, COLOR_OK)

        has_violation = draw_status_banner(
            frame, helmet_detected, vest_detected,
            esp32.online, fb.ready
        )

        # ── Update ESP32 buzzer ──────────────────────────────
        if not args.no_esp32:
            esp32.update(is_violation=has_violation)

        # ── Simpan log + screenshot + kirim ke Firebase ──────
        now = time.time()
        if has_violation and (now - last_alert_time) >= ALERT_COOLDOWN_SEC:
            timestamp       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ts_file         = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"violation_{ts_file}.jpg"
            screenshot_path = os.path.join(OUTPUT_DIR, screenshot_name)

            # Tentukan jenis pelanggaran
            pelanggaran = []
            if not helmet_detected: pelanggaran.append("Helmet")
            if not vest_detected:   pelanggaran.append("Vest")

            # Simpan foto lokal
            cv2.imwrite(screenshot_path, frame)

            # Simpan CSV lokal
            with open(log_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    CAMERA_ZONE,
                    " | ".join(pelanggaran),
                    "Ya" if helmet_detected else "Tidak",
                    "Ya" if vest_detected   else "Tidak",
                    screenshot_name,
                    "Terkirim" if fb.ready else "Lokal saja",
                ])

            # ✅ Kirim ke Firebase (foto + log)
            fb.upload(
                screenshot_path = screenshot_path,
                timestamp       = timestamp,
                helmet_ok       = helmet_detected,
                vest_ok         = vest_detected,
                confidence      = max_conf,
                pelanggaran     = pelanggaran,
            )

            print(f"⚠️  [{timestamp}] Pelanggaran: {', '.join(pelanggaran)} → {screenshot_name}")
            last_alert_time = now

        cv2.imshow("SafeK3-Cam - Deteksi Helm & Vest", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    if not args.no_esp32 and esp32.online:
        esp32._send("clear")
        time.sleep(0.3)

    print("\n✅ Selesai. Log tersimpan di:", log_path)


if __name__ == "__main__":
    main()
