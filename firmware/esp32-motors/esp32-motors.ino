#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

const char* hostname = "smartcar-motor";  // → http://smartcar-motor.local

// ─────────────── WIFI NETWORKS (add your networks here) ───────────────
struct WiFiNetwork {
  const char* ssid;
  const char* password;
};

WiFiNetwork knownNetworks[] = {
  {"TP-Link_4B76", "73005780"},           // Home WiFi
  {"MyPhoneHotspot", "hotspot123"},       // Phone hotspot (change this!)
  // Add more networks as needed:
  // {"OtherNetwork", "password"},
};
const int numNetworks = sizeof(knownNetworks) / sizeof(knownNetworks[0]);

// Auto-scan and connect to best available network
bool connectToWiFi() {
  Serial.println("Scanning for WiFi networks...");
  int n = WiFi.scanNetworks();
  if (n == 0) {
    Serial.println("No networks found!");
    return false;
  }
  Serial.printf("Found %d networks\n", n);
  
  // Find the strongest known network
  int bestRssi = -999;
  int bestIndex = -1;
  for (int i = 0; i < n; i++) {
    String foundSSID = WiFi.SSID(i);
    int rssi = WiFi.RSSI(i);
    Serial.printf("  %s (%d dBm)\n", foundSSID.c_str(), rssi);
    for (int j = 0; j < numNetworks; j++) {
      if (foundSSID == knownNetworks[j].ssid && rssi > bestRssi) {
        bestRssi = rssi;
        bestIndex = j;
      }
    }
  }
  WiFi.scanDelete();
  
  if (bestIndex < 0) {
    Serial.println("No known networks found!");
    return false;
  }
  
  Serial.printf("Connecting to: %s\n", knownNetworks[bestIndex].ssid);
  WiFi.begin(knownNetworks[bestIndex].ssid, knownNetworks[bestIndex].password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    return true;
  }
  return false;
}

// L298N / L9110S pins — change to match your wiring.
const int IN1 = 14, IN2 = 27, ENA = 26;  // left motor
const int IN3 = 25, IN4 = 33, ENB = 32;  // right motor

// HC-SR04 ultrasonic sensor pins (set to -1 if not connected)
const int TRIG_PIN = 12;
const int ECHO_PIN = 13;

const int PWM_FREQ = 5000;
const int PWM_RES  = 8;       // 0..255

WebServer server(80);
unsigned long lastCommandMs = 0;
const unsigned long SAFETY_TIMEOUT_MS = 500;  // stop if no command in 500ms

void applyMotor(int pinFwd, int pinRev, int pinEn, int speed) {
  speed = constrain(speed, -255, 255);
  digitalWrite(pinFwd, speed >  0);
  digitalWrite(pinRev, speed <  0);
  ledcWrite(pinEn, abs(speed));
}

void drive(int left, int right) {
  applyMotor(IN1, IN2, ENA, left);
  applyMotor(IN3, IN4, ENB, right);
  lastCommandMs = millis();
}

void handleDrive() {
  int l = server.arg("l").toInt();
  int r = server.arg("r").toInt();
  drive(l, r);
  server.send(200, "text/plain", "ok");
}

void handleStop() {
  drive(0, 0);
  server.send(200, "text/plain", "stopped");
}

void handleRssi() {
  server.send(200, "text/plain", String(WiFi.RSSI()));
}

float readDistanceCm() {
  if (TRIG_PIN < 0 || ECHO_PIN < 0) return -1.0;
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long dur = pulseIn(ECHO_PIN, HIGH, 30000); // 30ms timeout (~5m)
  if (dur == 0) return -1.0;
  return dur * 0.0343 / 2.0;
}

void handleDistance() {
  float d = readDistanceCm();
  server.send(200, "text/plain", String(d, 1));
}

void handleRoot() {
  server.send(200, "text/html",
    "<h3>ESP32 motors</h3>"
    "<p>GET /drive?l=-255..255&r=-255..255</p>"
    "<p>GET /stop</p>"
    "<p>GET /rssi</p>"
    "<p>GET /distance</p>");
}

void setup() {
  Serial.begin(115200);
  for (int p : {IN1, IN2, IN3, IN4}) pinMode(p, OUTPUT);
  if (TRIG_PIN >= 0) pinMode(TRIG_PIN, OUTPUT);
  if (ECHO_PIN >= 0) pinMode(ECHO_PIN, INPUT);

  ledcAttach(ENA, PWM_FREQ, PWM_RES);
  ledcAttach(ENB, PWM_FREQ, PWM_RES);
  drive(0, 0);

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname);
  WiFi.setAutoReconnect(true);
  
  // Scan and connect to available network
  while (!connectToWiFi()) {
    Serial.println("Retrying in 5 seconds...");
    delay(5000);
  }
  Serial.print("Motor IP: "); Serial.println(WiFi.localIP());

  if (MDNS.begin(hostname)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("mDNS: http://%s.local\n", hostname);
  }

  server.on("/",        handleRoot);
  server.on("/drive",    handleDrive);
  server.on("/stop",     handleStop);
  server.on("/rssi",     handleRssi);
  server.on("/distance", handleDistance);
  server.begin();
}

void loop() {
  server.handleClient();
  // Safety: if brain disconnects, coast to stop.
  if (millis() - lastCommandMs > SAFETY_TIMEOUT_MS) {
    ledcWrite(ENA, 0);
    ledcWrite(ENB, 0);
  }
  // Auto-reconnect WiFi if dropped
  if (WiFi.status() != WL_CONNECTED) {
    drive(0, 0);  // safety stop while disconnected
    Serial.println("WiFi lost, reconnecting...");
    connectToWiFi();
  }
}
