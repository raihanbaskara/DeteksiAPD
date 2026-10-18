"""
SafeK3-Cam — Test Deteksi dengan Foto
======================================
Test apakah model best.pt bisa mendeteksi
Hardhat & Mask dari file gambar (JPG/PNG).

Cara pakai:
  1. Letakkan best.pt dan foto di folder yang sama
  2. Ubah variabel IMAGE_PATH di bawah
  3. py safek3_test_foto.py
  4. Tekan tombol apapun untuk tutup jendela
"""

import cv2
import os
from ultralytics import YOLO
from datetime import datetime

# ============================================================
# KONFIGURASI — SESUAIKAN DI SINI
# ============================================================
def _find_path(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[0]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

MODEL_PATH = _find_path([
    os.path.join(PROJECT_ROOT, "models", "best.pt"),
    os.path.join(BASE_DIR, "models", "best.pt"),
    "models/best.pt",
    "best.pt"
])

IMAGE_PATH = _find_path([
    os.path.join(PROJECT_ROOT, "assets", "demo", "test_detection.jpg"),
    os.path.join(BASE_DIR, "assets", "demo", "test_detection.jpg"),
    "assets/demo/test_detection.jpg",
    "test.jpg"
])

CONF_THRESHOLD = 0.45        # confidence minimum (0.0 - 1.0)
IOU_THRESHOLD  = 0.45

REQUIRED_APD   = {"Hardhat"} # APD yang wajib dipakai
                              # tambah "Mask" jika masker juga wajib
# ============================================================

CLASS_COLORS = {
    "Hardhat" : (57, 255, 20),   # hijau neon
    "Mask"    : (0, 220, 255),   # kuning
}
DEFAULT_COLOR   = (255, 165, 0)
COLOR_SAFE      = (40, 190, 40)
COLOR_VIOLATION = (0, 0, 210)
COLOR_NODETECT  = (100, 100, 100)


def draw_box(frame, x1, y1, x2, y2, label, conf, color):
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    text = f"{label}  {conf:.0%}"
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
    cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 8, y1), color, -1)
    cv2.putText(frame, text, (x1 + 4, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)


def main():
    print("=" * 52)
    print("  SafeK3-Cam — Test Deteksi Foto")
    print("=" * 52)

    # ── Cek file model ────────────────────────────────────────
    if not os.path.exists(MODEL_PATH):
        print(f"\n[ERROR] Model tidak ditemukan: {MODEL_PATH}")
        print(f"        Pastikan best.pt ada di folder yang sama.")
        return

    # ── Cek file gambar ───────────────────────────────────────
    if not os.path.exists(IMAGE_PATH):
        print(f"\n[ERROR] Foto tidak ditemukan: {IMAGE_PATH}")
        print(f"        Pastikan nama file sudah benar.")
        print(f"        Contoh yang benar:")
        print(f"          IMAGE_PATH = \"test.jpg\"")
        print(f"          IMAGE_PATH = \"C:/Users/Mir/Pictures/foto.jpg\"")
        return

    # ── Load model ────────────────────────────────────────────
    print(f"\n[1/3] Loading model  : {MODEL_PATH}")
    model = YOLO(MODEL_PATH)
    print(f"      Kelas model    : {list(model.names.values())}")
    print(f"      APD wajib      : {list(REQUIRED_APD)}")

    # ── Load gambar ───────────────────────────────────────────
    print(f"\n[2/3] Membaca foto   : {IMAGE_PATH}")
    frame = cv2.imread(IMAGE_PATH)
    if frame is None:
        print(f"\n[ERROR] Gagal membaca foto!")
        print(f"        Pastikan file tidak rusak dan formatnya JPG/PNG.")
        return

    h, w = frame.shape[:2]
    print(f"      Ukuran foto    : {w}x{h} piksel")

    # ── Jalankan deteksi ──────────────────────────────────────
    print(f"\n[3/3] Menjalankan deteksi...")
    results = model.predict(
        source  = frame,
        conf    = CONF_THRESHOLD,
        iou     = IOU_THRESHOLD,
        verbose = False
    )[0]

    total_deteksi  = len(results.boxes)
    detected_classes = set()

    for box in results.boxes:
        cls_id       = int(box.cls[0])
        label        = model.names[cls_id]
        conf         = float(box.conf[0])
        x1,y1,x2,y2 = map(int, box.xyxy[0])
        color        = CLASS_COLORS.get(label, DEFAULT_COLOR)

        detected_classes.add(label)
        draw_box(frame, x1, y1, x2, y2, label, conf, color)

        print(f"      Terdeteksi : {label:10s} | confidence: {conf:.2%} "
              f"| posisi: ({x1},{y1}) → ({x2},{y2})")

    # ── Tentukan status ───────────────────────────────────────
    no_person    = total_deteksi == 0
    is_violation = (not no_person) and bool(REQUIRED_APD - detected_classes)
    missing_apd  = REQUIRED_APD - detected_classes

    # ── Status bar atas ───────────────────────────────────────
    if no_person:
        bar_color = COLOR_NODETECT
        msg       = "Tidak ada APD terdeteksi di foto ini"
    elif is_violation:
        bar_color = COLOR_VIOLATION
        msg       = f"PELANGGARAN — APD kurang: {', '.join(missing_apd)}"
    else:
        bar_color = COLOR_SAFE
        msg       = "AMAN — Semua APD terpasang"

    cv2.rectangle(frame, (0, 0), (w, 62), bar_color, -1)
    cv2.putText(frame, msg, (16, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 0.88, (255, 255, 255), 2)

    # ── Info bar bawah ────────────────────────────────────────
    cv2.rectangle(frame, (0, h - 38), (w, h), (20, 20, 20), -1)
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    cv2.putText(frame, f"Total deteksi: {total_deteksi}",
                (12, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
    cv2.putText(frame, ts,
                (w // 2 - 105, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
    cv2.putText(frame, "SafeK3-Cam  [FOTO TEST]",
                (w - 235, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 200, 255), 1)

    # ── Simpan hasil ──────────────────────────────────────────
    nama_asli   = os.path.splitext(os.path.basename(IMAGE_PATH))[0]
    output_path = f"{nama_asli}_hasil.jpg"
    cv2.imwrite(output_path, frame)

    # ── Ringkasan di terminal ─────────────────────────────────
    print()
    print("=" * 52)
    print("  HASIL DETEKSI")
    print("=" * 52)
    print(f"  Foto input     : {IMAGE_PATH}")
    print(f"  Total objek    : {total_deteksi}")
    print(f"  Kelas ditemukan: {list(detected_classes) if detected_classes else '-'}")
    print(f"  APD wajib      : {list(REQUIRED_APD)}")
    print(f"  APD kurang     : {list(missing_apd) if missing_apd else '-'}")
    print()

    if no_person:
        print("  STATUS  : ⚪ TIDAK ADA OBJEK TERDETEKSI")
        print("            Coba foto lebih dekat atau cek confidence threshold")
    elif is_violation:
        print(f"  STATUS  : 🔴 PELANGGARAN K3")
        print(f"            APD yang tidak dipakai: {', '.join(missing_apd)}")
    else:
        print("  STATUS  : 🟢 AMAN — Semua APD terpasang")

    print()
    print(f"  Hasil tersimpan: {output_path}")
    print("=" * 52)
    print()
    print("  Tekan tombol apapun untuk menutup jendela...")

    # ── Tampilkan hasil ───────────────────────────────────────
    # Resize jika foto terlalu besar untuk layar
    display = frame.copy()
    max_display_w = 1100
    if w > max_display_w:
        scale   = max_display_w / w
        display = cv2.resize(display,
                             (int(w * scale), int(h * scale)))

    cv2.imshow(f"SafeK3-Cam — Hasil Deteksi: {os.path.basename(IMAGE_PATH)}",
               display)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    print("\n[OK] Selesai.")


if __name__ == "__main__":
    main()
