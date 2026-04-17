#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include "esp_camera.h"

const char* hostname = "smartcar-cam";  // → http://smartcar-cam.local:81

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

// AI-Thinker ESP32-CAM pinout
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebServer server(81);

bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer   = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href  = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size   = psramFound() ? FRAMESIZE_VGA : FRAMESIZE_QVGA;
  c.jpeg_quality = 12;
  c.fb_count     = psramFound() ? 2 : 1;
  c.grab_mode    = CAMERA_GRAB_LATEST;
  c.fb_location  = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  return esp_camera_init(&c) == ESP_OK;
}

void handleStream() {
  WiFiClient client = server.client();
  String head =
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
  client.print(head);

  while (client.connected()) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { delay(10); continue; }
    client.printf("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", fb->len);
    client.write(fb->buf, fb->len);
    client.print("\r\n");
    esp_camera_fb_return(fb);
    if (!client.connected()) break;
  }
}

void handleRoot() {
  server.send(200, "text/html", "<img src='/stream'>");
}

void setup() {
  Serial.begin(115200);
  if (!initCamera()) { Serial.println("camera init failed"); while (true) delay(1000); }

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(hostname);
  WiFi.setAutoReconnect(true);
  
  // Scan and connect to available network
  while (!connectToWiFi()) {
    Serial.println("Retrying in 5 seconds...");
    delay(5000);
  }
  Serial.print("Cam IP: "); Serial.println(WiFi.localIP());

  if (MDNS.begin(hostname)) {
    MDNS.addService("http", "tcp", 81);
    Serial.printf("mDNS: http://%s.local:81/stream\n", hostname);
  }

  server.on("/",       handleRoot);
  server.on("/stream", handleStream);
  server.begin();
}

void loop() {
  server.handleClient();
  // Auto-reconnect WiFi if dropped
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi lost, reconnecting...");
    connectToWiFi();
  }
}
