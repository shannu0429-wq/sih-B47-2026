

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include "esp_http_server.h"


const char* ssid     = "VVIT Campus WIFI";
const char* password = "91357924680";


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


#define BUZZER_PIN        14


#define BUZZER_WATCHDOG_TIMEOUT_MS 3000


WebServer controlServer(80);
httpd_handle_t stream_httpd = NULL;

bool buzzerState = false;
unsigned long lastBuzzerKeepalive = 0;
bool cameraInitialized = false;


#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

void setBuzzer(bool state) {
  buzzerState = state;
  if (buzzerState) {
    digitalWrite(BUZZER_PIN, HIGH);
    lastBuzzerKeepalive = millis();
    Serial.println("[BUZZER] ON");
  } else {
    digitalWrite(BUZZER_PIN, LOW);
    Serial.println("[BUZZER] OFF");
  }
}


void handleStatus() {
  controlServer.sendHeader("Access-Control-Allow-Origin", "*");
  controlServer.sendHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  controlServer.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  
  String json = "{";
  json += "\"status\":\"ok\",";
  json += "\"camera\":" + String(cameraInitialized ? "\"connected\"" : "\"error\"") + ",";
  json += "\"buzzer\":" + String(buzzerState ? "true" : "false") + ",";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"rssi\":" + String(WiFi.RSSI()) + ",";
  json += "\"psram\":" + String(psramFound() ? "true" : "false") + ",";
  json += "\"uptime_ms\":" + String(millis());
  json += "}";
  
  controlServer.send(200, "application/json", json);
}

void handleBuzzerOn() {
  controlServer.sendHeader("Access-Control-Allow-Origin", "*");
  setBuzzer(true);
  controlServer.send(200, "application/json", "{\"buzzer\":true,\"status\":\"on\"}");
}

void handleBuzzerOff() {
  controlServer.sendHeader("Access-Control-Allow-Origin", "*");
  setBuzzer(false);
  controlServer.send(200, "application/json", "{\"buzzer\":false,\"status\":\"off\"}");
}

void handleBuzzerTest() {
  controlServer.sendHeader("Access-Control-Allow-Origin", "*");
  // Quick test beep
  digitalWrite(BUZZER_PIN, HIGH);
  delay(300);
  digitalWrite(BUZZER_PIN, LOW);
  buzzerState = false;
  controlServer.send(200, "application/json", "{\"buzzer\":false,\"status\":\"tested\"}");
}

void handleNotFound() {
  controlServer.sendHeader("Access-Control-Allow-Origin", "*");
  controlServer.send(404, "text/plain", "Not Found");
}


static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char * part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) {
    return res;
  }
  
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[CAMERA] Camera capture failed");
      res = ESP_FAIL;
      break;
    }
    
    _jpg_buf_len = fb->len;
    _jpg_buf = fb->buf;

    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }
    if (res == ESP_OK) {
      size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    
    esp_camera_fb_return(fb);
    fb = NULL;
    _jpg_buf = NULL;

    if (res != ESP_OK) {
      break;
    }
    
    // Yield to let watchdog & WiFi tasks run smoothly
    vTaskDelay(pdMS_TO_TICKS(10));
  }
  
  return res;
}

void startStreamServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 81;
  config.ctrl_port = 32768;

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  Serial.printf("[HTTP] Starting stream server on port: %d\n", config.server_port);
  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
    Serial.println("[HTTP] Stream server started at /stream on Port 81");
  } else {
    Serial.println("[HTTP] Failed to start stream server on Port 81");
  }
}


void setup() {
  // CRITICAL: Buzzer MUST start silent
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  buzzerState = false;

  Serial.begin(115200);
  Serial.setDebugOutput(false);
  Serial.println();
  Serial.println("==========================================");
  Serial.println(" ESP32-CAM Animal Detection & Buzzer Node ");
  Serial.println("==========================================");

  // Configure Camera Pins & Buffers
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    Serial.println("[CAMERA] PSRAM found! Using VGA resolution with dual frame buffers.");
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    Serial.println("[CAMERA] Warning: PSRAM not found. Using QVGA resolution.");
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 14;
    config.fb_count = 1;
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  // Camera Initialization
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAMERA] Camera init failed with error 0x%x\n", err);
    cameraInitialized = false;
  } else {
    Serial.println("[CAMERA] Camera initialized successfully.");
    cameraInitialized = true;
    
    sensor_t * s = esp_camera_sensor_get();
    if (s != NULL) {
      s->set_vflip(s, 0);
      s->set_hmirror(s, 0);
      s->set_brightness(s, 1);
      s->set_contrast(s, 1);
      s->set_saturation(s, 0);
    }
  }

  // Connect to WiFi
  Serial.printf("[WIFI] Connecting to SSID: %s\n", ssid);
  WiFi.begin(ssid, password);
  WiFi.setSleep(false); // Disable WiFi sleep for low-latency streaming

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WIFI] WiFi connected successfully!");
    Serial.print("[WIFI] IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WIFI] WiFi connection failed. Will retry in loop.");
  }

  // Setup Port 80 Control Server
  controlServer.on("/status", HTTP_GET, handleStatus);
  controlServer.on("/buzzer/on", HTTP_GET, handleBuzzerOn);
  controlServer.on("/buzzer/off", HTTP_GET, handleBuzzerOff);
  controlServer.on("/buzzer/test", HTTP_GET, handleBuzzerTest);
  controlServer.onNotFound(handleNotFound);
  controlServer.begin();
  Serial.println("[HTTP] Control server started on Port 80");

  // Setup Port 81 Stream Server
  startStreamServer();

  // Ensure buzzer remains OFF after all initialization
  digitalWrite(BUZZER_PIN, LOW);
  buzzerState = false;

  Serial.println("==========================================");
  Serial.println("Ready!");
  Serial.printf("Port 80 Control: http://%s/status\n", WiFi.localIP().toString().c_str());
  Serial.printf("Port 81 Stream:  http://%s:81/stream\n", WiFi.localIP().toString().c_str());
  Serial.println("==========================================");
}


void loop() {
  // Handle incoming HTTP requests on Port 80
  controlServer.handleClient();

  // Safety Watchdog: If buzzer is ON and no keepalive received within timeout, turn OFF
  if (buzzerState) {
    if (millis() - lastBuzzerKeepalive > BUZZER_WATCHDOG_TIMEOUT_MS) {
      digitalWrite(BUZZER_PIN, LOW);
      buzzerState = false;
      Serial.println("[WATCHDOG] Safety timeout reached. Buzzer turned OFF.");
    }
  }

  // WiFi Reconnection Watchdog
  if (WiFi.status() != WL_CONNECTED) {
    static unsigned long lastWifiRetry = 0;
    if (millis() - lastWifiRetry > 10000) {
      lastWifiRetry = millis();
      Serial.println("[WIFI] Reconnecting to WiFi...");
      WiFi.reconnect();
    }
  }

  delay(2);
}