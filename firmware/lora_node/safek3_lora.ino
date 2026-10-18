#include <SPI.h>
#include <LoRa.h>

// ======================================================
// BAB IV - LINK QUALITY MEASUREMENT
// RECEIVER NODE B
// A -> B
// ======================================================

// ======================================================
// KONFIGURASI HARDWARE
// Pin sama dengan skema Bab III (Standar ESP32)
// ======================================================
const int PIN_SCK = 18;
const int PIN_MISO = 19;
const int PIN_MOSI = 23;
const int PIN_SS = 22; // NSS / CS
const int PIN_RST = 15;
const int PIN_DIO0 = 21;

// ======================================================
// KONFIGURASI RADIO
// Harus sama dengan transmitter
// ======================================================
const long LORA_FREQ = 433E6;
const long SIGNAL_BW = 125E3;
const int SPREADING_FACTOR = 7;
const int CODING_RATE = 5; // Coding rate 4/5
const uint8_t SYNC_WORD = 0x33;

// ======================================================
// IDENTITAS NODE
// ======================================================
const uint8_t EXPECTED_SRC_ID = 0x10; // Node A
const uint8_t SELF_ID = 0x20;         // Node B
const uint8_t TYPE_LQ = 0x20;         // Frame Link Quality

// ======================================================
// CRC-16-CCITT
// CRC aplikasi
// ======================================================
uint16_t crc16ccitt(const uint8_t* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (int b = 0; b < 8; b++) {
      if (crc & 0x8000) {
        crc = (crc << 1) ^ 0x1021;
      } else {
        crc = crc << 1;
      }
    }
  }
  return crc;
}

// ======================================================
// PARSER FRAME
// ======================================================
bool parseFrame(const uint8_t* raw, size_t n, uint8_t &src, uint16_t &seq) {
  // Cek panjang minimal header
  if (n < 13) {
    return false;
  }
  
  // Verifikasi Header
  if (raw[0] != 1) { // Version
    return false;
  }
  if (raw[1] != TYPE_LQ) {
    return false;
  }
  if (raw[2] != EXPECTED_SRC_ID) {
    return false;
  }
  if (raw[3] != SELF_ID) {
    return false;
  }
  
  // Cek kesesuaian panjang payload
  uint8_t plen = raw[10];
  if (n != (size_t)(13 + plen)) {
    return false;
  }
  
  // Ekstrak CRC dari 2 byte terakhir
  uint16_t rxCrc = ((uint16_t)raw[n - 2] << 8) | raw[n - 1];
  
  // Hitung ulang CRC
  uint16_t calcCrc = crc16ccitt(raw, n - 2);
  
  // Validasi CRC
  if (rxCrc != calcCrc) {
    return false;
  }
  
  // Ambil Source ID dan Sequence Number
  src = raw[2];
  seq = ((uint16_t)raw[4] << 8) | raw[5];
  
  return true;
}

// ======================================================
// SETUP
// ======================================================
void setup() {
  Serial.begin(115200);
  delay(500);
  
  // --------------------------
  // SPI & LoRa Init
  // --------------------------
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_SS);
  LoRa.setPins(PIN_SS, PIN_RST, PIN_DIO0);
  
  if (!LoRa.begin(LORA_FREQ)) {
    Serial.println("ERROR: LoRa gagal diinisialisasi");
    while (true) {
      delay(1000);
    }
  }
  
  // --------------------------
  // Parameter radio
  // --------------------------
  LoRa.setSignalBandwidth(SIGNAL_BW);
  LoRa.setSpreadingFactor(SPREADING_FACTOR);
  LoRa.setCodingRate4(CODING_RATE);
  LoRa.setSyncWord(SYNC_WORD);
  
  // CRC PHY LoRa
  LoRa.enableCrc();
  
  // Header CSV
  Serial.println("event,t_ms,src,dst,seq,rssi_dbm,snr_db");
}

// ======================================================
// LOOP
// ======================================================
void loop() {
  // Cek apakah ada paket masuk
  int packetSize = LoRa.parsePacket();
  if (!packetSize) {
    return;
  }
  
  // Baca paket ke buffer raw
  uint8_t raw[128];
  size_t n = 0;
  while (LoRa.available() && n < sizeof(raw)) {
    raw[n++] = (uint8_t)LoRa.read();
  }
  
  // Cek apakah data yang terbaca sesuai dengan info size paket
  if (n != (size_t)packetSize) {
    return;
  }
  
  uint8_t src;
  uint16_t seq;
  
  // Parsing paket data
  bool valid = parseFrame(raw, n, src, seq);
  if (!valid) {
    return; // Abaikan jika paket tidak valid
  }
  
  // Ambil data kekuatan dan kualitas sinyal
  int rssi = LoRa.packetRssi();
  float snr = LoRa.packetSnr();
  
  // Logging RX
  Serial.printf("RX,%lu,%u,%u,%u,%d,%.2f\n", millis(), src, SELF_ID, seq, rssi, snr);
}