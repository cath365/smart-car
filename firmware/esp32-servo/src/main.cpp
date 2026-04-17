#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

const char* ssid     = "TP-Link_4B76";
const char* password = "73005780";
const char* hostname = "smartcar-servo";  // → http://smartcar-servo.local

// Servo signal pins — change to match your wiring
const int SERVO_PAN  = 26;  // horizontal (left/right)
const int SERVO_TILT = 27;  // vertical (up/down)

// Servo PWM (standard 50 Hz)
const int PWM_FREQ = 50;
const int PWM_RES  = 16;  // 16-bit for precise pulse widths
const int PWM_CH_PAN  = 0;
const int PWM_CH_TILT = 1;

// Pulse-width limits in microseconds — adjust for your servos
const int PAN_MIN_US  = 500;   // full left
const int PAN_MID_US  = 1500;  // centre
const int PAN_MAX_US  = 2500;  // full right
const int TILT_MIN_US = 500;   // full down
const int TILT_MID_US = 1500;  // centre
const int TILT_MAX_US = 2500;  // full up

WebServer server(80);
int curPan  = 90;  // current angle 0-180
int curTilt = 90;

// Convert microseconds to 16-bit LEDC duty at 50 Hz (period = 20 000 µs)
uint32_t usToDuty(int us) {
  return (uint32_t)((float)us / 20000.0f * 65536.0f);
}

void writeServo(int channel, int angle, int minUs, int maxUs) {
  angle = constrain(angle, 0, 180);
  int us = map(angle, 0, 180, minUs, maxUs);
  ledcWrite(channel, usToDuty(us));
}

void applyServos() {
  writeServo(PWM_CH_PAN,  curPan,  PAN_MIN_US,  PAN_MAX_US);
  writeServo(PWM_CH_TILT, curTilt, TILT_MIN_US, TILT_MAX_US);
}

// GET /servo?pan=0..180&tilt=0..180
void handleServo() {
  if (server.hasArg("pan"))  curPan  = constrain(server.arg("pan").toInt(),  0, 180);
  if (server.hasArg("tilt")) curTilt = constrain(server.arg("tilt").toInt(), 0, 180);
  applyServos();
  server.send(200, "text/plain", String(curPan) + "," + String(curTilt));
}

// GET /servo_status → JSON
void handleStatus() {
  String json = "{\"pan\":" + String(curPan) + ",\"tilt\":" + String(curTilt) + "}";
  server.send(200, "application/json", json);
}

void handleCenter() {
  curPan = 90;
  curTilt = 90;
  applyServos();
  server.send(200, "text/plain", "centred");
}

void handleRssi() {
  server.send(200, "text/plain", String(WiFi.RSSI()));
}

void handleRoot() {
  server.send(200, "text/html",
    "<h3>ESP32 servo controller</h3>"
    "<p>GET /servo?pan=0..180&tilt=0..180</p>"
    "<p>GET /servo_status</p>"
    "<p>GET /center</p>"
    "<p>GET /rssi</p>");
}

void setup() {
  Serial.begin(115200);

  ledcSetup(PWM_CH_PAN,  PWM_FREQ, PWM_RES);
  ledcAttachPin(SERVO_PAN, PWM_CH_PAN);
  ledcSetup(PWM_CH_TILT, PWM_FREQ, PWM_RES);
  ledcAttachPin(SERVO_TILT, PWM_CH_TILT);
  applyServos();  // centre both

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname);
  WiFi.setAutoReconnect(true);
  WiFi.begin(ssid, password);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.println();
  Serial.print("Servo IP: "); Serial.println(WiFi.localIP());

  if (MDNS.begin(hostname)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("mDNS: http://%s.local\n", hostname);
  }

  server.on("/",             handleRoot);
  server.on("/servo",        handleServo);
  server.on("/servo_status", handleStatus);
  server.on("/center",       handleCenter);
  server.on("/rssi",         handleRssi);
  server.begin();
}

void loop() {
  server.handleClient();
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(500);
  }
}
