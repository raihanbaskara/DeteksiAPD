/*
  SafeK3 - ESP32 Buzzer Alarm Controller
  ======================================
  Firmware untuk ESP32 sebagai unit alarm K3 fisik.
  Menerima perintah HTTP dari SafeK3 Computer Vision Engine.

  Hardware:
  - ESP32 Development Board (NodeMCU / DOIT ESP32 DevKit v1)
  - Active Buzzer (atau Passive Buzzer dengan PWM)
  - LED Indikator (Opsional / Built-in LED GPIO 2)

  Pinout:
  - BUZZER_PIN : GPIO 4 (Bisa disesuaikan)
  - LED_PIN    : GPIO 2 (Built-in LED)

  Endpoint HTTP:
  - GET /status        : Cek status koneksi ESP32 & kondisi buzzer saat ini
  - GET /alert?type=violation : Bunyikan buzzer (pelanggaran APD terdeteksi)
  - GET /alert?type=clear     : Matikan buzzer (APD lengkap / aman)
*/

#include <WiFi.h>
#include <WebServer.h>

// ----------------------------------------------------
// KONFIGURASI WIFI & PIN
// ----------------------------------------------------
const char* ssid     = "NAMA_WIFI_ANDA";     // Ganti dengan SSID WiFi Anda
const char* password = "PASSWORD_WIFI_ANDA"; // Ganti dengan Password WiFi Anda

const int BUZZER_PIN = 4; // Pin Buzzer (+ melalui resistor/transistor jika perlu)
const int LED_PIN    = 2; // LED Built-in

WebServer server(80);

bool buzzerActive = false;
unsigned long lastBeepTime = 0;
bool beepState = false;

// ----------------------------------------------------
// HANDLER HTTP
// ----------------------------------------------------
void handleRoot() {
  server.send(200, "text/plain", "SafeK3 ESP32 Alarm Controller is Running!");
}

void handleStatus() {
  String json = "{";
  json += "\"status\":\"ok\",";
  json += "\"device\":\"SafeK3-ESP32-Buzzer\",";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"buzzer\":\"" + String(buzzerActive ? "ON" : "OFF") + "\"";
  json += "}";
  server.send(200, "application/json", json);
}

void handleAlert() {
  if (server.hasArg("type")) {
    String type = server.arg("type");
    if (type == "violation") {
      buzzerActive = true;
      Serial.println("[ALERT] Pelanggaran APD terdeteksi -> Buzzer AKTIF!");
    } else if (type == "clear") {
      buzzerActive = false;
      digitalWrite(BUZZER_PIN, LOW);
      digitalWrite(LED_PIN, LOW);
      Serial.println("[INFO] APD Lengkap -> Buzzer DIMATIKAN.");
    }
  }
  handleStatus();
}

void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN, LOW);

  Serial.println("\n==================================");
  Serial.println(" SafeK3 ESP32 Buzzer Alarm Node ");
  Serial.println("==================================");

  // Menghubungkan ke WiFi
  Serial.print("Menghubungkan ke WiFi: ");
  Serial.println(ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  }

  digitalWrite(LED_PIN, LOW);
  Serial.println("\nWiFi Terhubung!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // Daftarkan Endpoint WebServer
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/alert", handleAlert);

  server.begin();
  Serial.println("HTTP Server aktif di port 80");
}

void loop() {
  server.handleClient();

  // Pola bunyi alarm saat pelanggaran terjadi (beeping interval)
  if (buzzerActive) {
    unsigned long currentMillis = millis();
    if (currentMillis - lastBeepTime >= 150) { // Bunyi beep setiap 150ms
      lastBeepTime = currentMillis;
      beepState = !beepState;
      digitalWrite(BUZZER_PIN, beepState ? HIGH : LOW);
      digitalWrite(LED_PIN, beepState ? HIGH : LOW);
    }
  }
}
