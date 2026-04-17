#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>

const char* ssid     = "TP-Link_4B76";
const char* password = "73005780";
const char* hostname = "smartcar-motor";  // → http://smartcar-motor.local

// L298N / L9110S pins — change to match your wiring.
const int IN1 = 14, IN2 = 27, ENA = 26;  // left motor
const int IN3 = 25, IN4 = 33, ENB = 32;  // right motor

// HC-SR04 ultrasonic sensor pins (set to -1 if not connected)
const int TRIG_PIN = 12;
const int ECHO_PIN = 13;

const int PWM_FREQ = 5000;
const int PWM_RES  = 8;       // 0..255
const int PWM_CH_A = 0;    // LEDC channel for motor A
const int PWM_CH_B = 1;    // LEDC channel for motor B

WebServer server(80);
unsigned long lastCommandMs = 0;
const unsigned long SAFETY_TIMEOUT_MS = 500;  // stop if no command in 500ms

void applyMotor(int pinFwd, int pinRev, int channel, int speed) {
  speed = constrain(speed, -255, 255);
  digitalWrite(pinFwd, speed >  0);
  digitalWrite(pinRev, speed <  0);
  ledcWrite(channel, abs(speed));
}

void drive(int left, int right) {
  applyMotor(IN1, IN2, PWM_CH_A, left);
  applyMotor(IN3, IN4, PWM_CH_B, right);
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

  ledcSetup(PWM_CH_A, PWM_FREQ, PWM_RES);
  ledcAttachPin(ENA, PWM_CH_A);
  ledcSetup(PWM_CH_B, PWM_FREQ, PWM_RES);
  ledcAttachPin(ENB, PWM_CH_B);
  drive(0, 0);

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname);
  WiFi.setAutoReconnect(true);
  WiFi.begin(ssid, password);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.println();
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
    ledcWrite(PWM_CH_A, 0);
    ledcWrite(PWM_CH_B, 0);
  }
  // Auto-reconnect WiFi if dropped
  if (WiFi.status() != WL_CONNECTED) {
    drive(0, 0);  // safety stop while disconnected
    WiFi.reconnect();
    delay(500);
  }
}
