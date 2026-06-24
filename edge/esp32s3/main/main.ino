#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <I2S.h>
#include <MFRC522.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <SPI.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <mbedtls/md.h>

#if __has_include("local_config.h")
#include "local_config.h"
#endif

#ifndef SMARTDESK_BOOTSTRAP_SERVER_URL
#define SMARTDESK_BOOTSTRAP_SERVER_URL ""
#endif

#ifndef SMARTDESK_DEVICE_TOKEN
#define SMARTDESK_DEVICE_TOKEN ""
#endif

#ifndef SMARTDESK_IOTDA_ENABLED
#define SMARTDESK_IOTDA_ENABLED 0
#endif

#ifndef SMARTDESK_IOTDA_HOST
#define SMARTDESK_IOTDA_HOST ""
#endif

#ifndef SMARTDESK_IOTDA_PORT
#define SMARTDESK_IOTDA_PORT 8883
#endif

#ifndef SMARTDESK_IOTDA_DEVICE_ID
#define SMARTDESK_IOTDA_DEVICE_ID ""
#endif

#ifndef SMARTDESK_IOTDA_SECRET
#define SMARTDESK_IOTDA_SECRET ""
#endif

#ifndef SMARTDESK_IOTDA_TIMESTAMP
#define SMARTDESK_IOTDA_TIMESTAMP "2026062100"
#endif

static const char *DEVICE_ID = "desktop-agent-001";
static const char *EDGE_ID = "esp32s3-sense-001";

static const int STM32_TX_PIN = 6;   // XIAO D5 -> STM32 PB11, 9600 baud
static const int STM32_RX_PIN = 44;  // XIAO D7 <- STM32 PB3, 4800 baud

static const int RFID_RST_PIN = 3;   // XIAO D2
static const int RFID_SS_PIN = 4;    // XIAO D3
static const int RFID_SCK_PIN = 7;   // XIAO D8
static const int RFID_MISO_PIN = 8;  // XIAO D9
static const int RFID_MOSI_PIN = 9;  // XIAO D10
static const int MIC_CLK_PIN = 42;   // XIAO ESP32S3 Sense PDM CLK
static const int MIC_DATA_PIN = 41;  // XIAO ESP32S3 Sense PDM DATA

HardwareSerial stm32Tx(1);
HardwareSerial stm32Rx(2);
Preferences prefs;
WebSocketsClient webSocket;
MFRC522 rfid(RFID_SS_PIN, RFID_RST_PIN);
#if SMARTDESK_IOTDA_ENABLED
#if SMARTDESK_IOTDA_PORT == 1883
WiFiClient iotdaClient;
#else
WiFiClientSecure iotdaClient;
#endif
PubSubClient iotdaMqtt(iotdaClient);
#endif

String wifiSsid;
String wifiPassword;
String serverHost;
String deviceToken = String(SMARTDESK_DEVICE_TOKEN);
uint16_t serverPort = 8082;
bool serverSecure = false;
bool wsConnected = false;
bool wsStarted = false;

String usbLine;
String stm32Line;
unsigned long lastHeartbeatMs = 0;
unsigned long lastAckMs = 0;
unsigned long lastStm32TxMs = 0;
unsigned long lastUartKeepaliveMs = 0;
unsigned long lastRfidMs = 0;
unsigned long lastRfidSeenMs = 0;
unsigned long lastRfidHealthMs = 0;
unsigned long lastCommandPollMs = 0;
unsigned long lastWifiMissingLogMs = 0;
unsigned long lastIotdaReconnectMs = 0;
String lastRfidUid;
String voiceState = "text_bridge";
bool micReady = false;
bool micBusy = false;

static const unsigned long UART_OK_WINDOW_MS = 15000;
static const unsigned long UART_KEEPALIVE_INTERVAL_MS = 10000;
static const unsigned long UART_TX_QUIET_MS = 7000;
static const unsigned long COMMAND_POLL_INTERVAL_MS = 800;
static const unsigned long RFID_POLL_INTERVAL_MS = 200;
static const unsigned long RFID_REPEAT_SUPPRESS_MS = 15000;
static const unsigned long RFID_HEALTH_INTERVAL_MS = 5000;
static const unsigned long WIFI_CONNECT_TIMEOUT_MS = 30000;
static const bool MIC_PATH_ENABLED = false;
static const uint32_t MIC_RECORD_SECONDS = 6;
static const uint32_t MIC_SAMPLE_RATE = 16000;
static const uint32_t MIC_SAMPLE_BITS = 16;
static const uint32_t MIC_WAV_HEADER_SIZE = 44;
static const int32_t MIC_DIGITAL_GAIN = 16;
static const uint16_t MIC_COUNTDOWN_CUE_DELAY_MS = 1450;
static const size_t MIC_UPLOAD_CHUNK_SIZE = 512;
static const uint8_t MIC_UPLOAD_INTER_CHUNK_DELAY_MS = 2;
static const size_t MIC_UPLOAD_CHUNKED_PART_SIZE = 8192;
static const uint8_t MIC_UPLOAD_CHUNKED_PART_ATTEMPTS = 4;

struct AsrUploadResult {
  bool requestOk = false;
  bool asrOk = false;
  String provider;
  String text;
  String error;
};

struct MicCapture {
  uint8_t *wavBuffer = nullptr;
  size_t wavSize = 0;
};

struct ChunkUploadResponse {
  bool requestOk = false;
  bool chunkOk = false;
  bool complete = false;
  size_t received = 0;
  String error;
  AsrUploadResult asr;
};

uint8_t *allocLargeBuffer(size_t size) {
  uint8_t *buffer = (uint8_t *)ps_malloc(size);
  if (buffer == nullptr) {
    buffer = (uint8_t *)malloc(size);
  }
  return buffer;
}

String httpBase() {
  return String(serverSecure ? "https://" : "http://") + serverHost + ":" + String(serverPort);
}

String wsBase() {
  return String(serverSecure ? "wss://" : "ws://") + serverHost + ":" + String(serverPort);
}

String wsPath() {
  return "/api/realtime/ws?device_id=" + String(DEVICE_ID) + "&edge_id=" + String(EDGE_ID);
}

String utf8Hex(const String &text) {
  static const char *HEX_DIGITS = "0123456789ABCDEF";
  String encoded;
  encoded.reserve(text.length() * 2);
  for (unsigned int i = 0; i < text.length(); i++) {
    uint8_t value = (uint8_t)text.charAt(i);
    encoded += HEX_DIGITS[(value >> 4) & 0x0F];
    encoded += HEX_DIGITS[value & 0x0F];
  }
  return encoded;
}

void saveConfig() {
  prefs.begin("smartdesk", false);
  prefs.putString("wifi_ssid", wifiSsid);
  prefs.putString("wifi_pass", wifiPassword);
  prefs.putString("server_host", serverHost);
  prefs.putUShort("server_port", serverPort);
  prefs.putBool("server_secure", serverSecure);
  prefs.putString("device_token", deviceToken);
  prefs.end();
}

void loadConfig() {
  prefs.begin("smartdesk", true);
  wifiSsid = prefs.getString("wifi_ssid", "");
  wifiPassword = prefs.getString("wifi_pass", "");
  serverHost = prefs.getString("server_host", "");
  serverPort = prefs.getUShort("server_port", 8082);
  serverSecure = prefs.getBool("server_secure", false);
  deviceToken = prefs.getString("device_token", SMARTDESK_DEVICE_TOKEN);
  prefs.end();
}

bool parseServerUrl(String value) {
  value.trim();
  bool secure = false;
  if (value.startsWith("https://")) {
    secure = true;
    value.remove(0, strlen("https://"));
  } else if (value.startsWith("wss://")) {
    secure = true;
    value.remove(0, strlen("wss://"));
  } else if (value.startsWith("http://")) {
    value.remove(0, strlen("http://"));
  } else if (value.startsWith("ws://")) {
    value.remove(0, strlen("ws://"));
  }
  int slash = value.indexOf('/');
  if (slash >= 0) {
    value = value.substring(0, slash);
  }
  int colon = value.lastIndexOf(':');
  if (colon >= 0) {
    serverHost = value.substring(0, colon);
    serverPort = (uint16_t)value.substring(colon + 1).toInt();
  } else {
    serverHost = value;
    serverPort = secure ? 443 : 8082;
  }
  serverHost.trim();
  serverSecure = secure;
  return serverHost.length() > 0 && serverPort > 0;
}

String stm32LogLine(const String &line) {
  int ttsHexPos = line.indexOf("NET:TTSHEX:");
  if (ttsHexPos < 0) {
    return line;
  }

  String prefix = line.substring(0, ttsHexPos);
  String payload = line.substring(ttsHexPos + strlen("NET:TTSHEX:"));
  return prefix + "NET:TTSHEX:[" + String(payload.length() / 2) + " bytes]";
}

void sendToStm32(const String &line, uint16_t postDelayMs = 80) {
  Serial.print("[STM32 TX] ");
  Serial.println(stm32LogLine(line));
  stm32Tx.println(line);
  stm32Tx.flush();
  lastStm32TxMs = millis();
  if (postDelayMs > 0) {
    delay(postDelayMs);
  }
}

#if SMARTDESK_IOTDA_ENABLED
String hmacSha256Hex(const String &key, const String &message) {
  unsigned char digest[32];
  const mbedtls_md_info_t *mdInfo = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  mbedtls_md_hmac(
      mdInfo,
      reinterpret_cast<const unsigned char *>(key.c_str()),
      key.length(),
      reinterpret_cast<const unsigned char *>(message.c_str()),
      message.length(),
      digest);

  static const char *HEX_DIGITS = "0123456789abcdef";
  String encoded;
  encoded.reserve(64);
  for (uint8_t value : digest) {
    encoded += HEX_DIGITS[(value >> 4) & 0x0F];
    encoded += HEX_DIGITS[value & 0x0F];
  }
  return encoded;
}

String iotdaDeviceId() {
  return String(SMARTDESK_IOTDA_DEVICE_ID);
}

String iotdaPropertyReportTopic() {
  return "$oc/devices/" + iotdaDeviceId() + "/sys/properties/report";
}

String iotdaCommandSubscribeTopic() {
  return "$oc/devices/" + iotdaDeviceId() + "/sys/commands/#";
}

String iotdaCommandResponseTopic(const String &requestId) {
  return "$oc/devices/" + iotdaDeviceId() + "/sys/commands/response/request_id=" + requestId;
}

bool isIotdaPropertyKey(const char *key) {
  static const char *IOTDA_KEYS[] = {
      "temperature_c",
      "humidity_pct",
      "distance_cm",
      "pot_raw",
      "ntc_raw",
      "tracking_signal",
      "wifi_rssi_dbm",
      "aht20_ok",
      "distance_ok",
      "encoder_position",
  };
  for (const char *allowed : IOTDA_KEYS) {
    if (strcmp(key, allowed) == 0) {
      return true;
    }
  }
  return false;
}

String commandFromIotda(const String &commandName, JsonObject paras, bool *accepted) {
  *accepted = true;
  if (commandName == "fan_control") {
    String state = paras["state"] | "on";
    state.toLowerCase();
    if (state == "off" || state == "0" || state == "false") {
      return "NET:FAN:OFF";
    }
    int level = paras["level"] | 2;
    if (level < 1) level = 1;
    if (level > 3) level = 3;
    return "NET:FAN:ON:" + String(level);
  }
  if (commandName == "lock_control") {
    String state = paras["state"] | "on";
    state.toLowerCase();
    if (state == "off" || state == "unlock" || state == "0" || state == "false") {
      return "NET:LOCK:OFF";
    }
    return "NET:LOCK:ON";
  }
  if (commandName == "buzzer_alert") {
    return "NET:BEEP";
  }
  if (commandName == "tts_speak") {
    String text = paras["text"] | "";
    if (text.length() == 0) {
      *accepted = false;
      return "";
    }
    return "NET:TTSHEX:" + utf8Hex(text);
  }
  if (commandName == "volume_control") {
    int level = paras["level"] | 10;
    if (level < 0) level = 0;
    if (level > 16) level = 16;
    return "NET:VOLUME:" + String(level);
  }
  if (commandName == "raw_stm32") {
    String command = paras["command"] | "";
    if (!command.startsWith("NET:")) {
      *accepted = false;
      return "";
    }
    return command;
  }
  *accepted = false;
  return "";
}

void publishIotdaCommandResponse(const String &topic, bool accepted, const String &commandName) {
  int requestPos = topic.indexOf("request_id=");
  if (requestPos < 0 || !iotdaMqtt.connected()) {
    return;
  }
  String requestId = topic.substring(requestPos + strlen("request_id="));
  JsonDocument response;
  response["result_code"] = accepted ? 0 : 1;
  response["response_name"] = "smartdesk_response";
  JsonObject paras = response["paras"].to<JsonObject>();
  paras["accepted"] = accepted;
  paras["command_name"] = commandName;
  String payload;
  serializeJson(response, payload);
  iotdaMqtt.publish(iotdaCommandResponseTopic(requestId).c_str(), payload.c_str());
}

void iotdaCallback(char *topic, byte *payload, unsigned int length) {
  String text;
  text.reserve(length + 1);
  for (unsigned int i = 0; i < length; i++) {
    text += static_cast<char>(payload[i]);
  }

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, text);
  if (error) {
    Serial.print("[IOTDA] bad command json: ");
    Serial.println(error.c_str());
    publishIotdaCommandResponse(String(topic), false, "");
    return;
  }

  String commandName = doc["command_name"] | "";
  JsonObject paras = doc["paras"].as<JsonObject>();
  bool accepted = false;
  String stm32Command = commandFromIotda(commandName, paras, &accepted);
  if (accepted && stm32Command.length() > 0) {
    sendToStm32("NET:UI:ACTION", 0);
    sendToStm32(stm32Command);
  }
  publishIotdaCommandResponse(String(topic), accepted, commandName);
}

bool ensureIotdaMqttConnected() {
  if (strlen(SMARTDESK_IOTDA_HOST) == 0 || strlen(SMARTDESK_IOTDA_DEVICE_ID) == 0 ||
      strlen(SMARTDESK_IOTDA_SECRET) == 0) {
    return false;
  }
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  if (iotdaMqtt.connected()) {
    return true;
  }
  if (millis() - lastIotdaReconnectMs < 5000) {
    return false;
  }
  lastIotdaReconnectMs = millis();

#if SMARTDESK_IOTDA_PORT != 1883
  iotdaClient.setInsecure();
#endif
  iotdaMqtt.setServer(SMARTDESK_IOTDA_HOST, SMARTDESK_IOTDA_PORT);
  iotdaMqtt.setCallback(iotdaCallback);
  iotdaMqtt.setBufferSize(1024);
  iotdaMqtt.setKeepAlive(120);

  String deviceId = iotdaDeviceId();
  String timestamp = SMARTDESK_IOTDA_TIMESTAMP;
  String clientId = deviceId + "_0_0_" + timestamp;
  String password = hmacSha256Hex(timestamp, SMARTDESK_IOTDA_SECRET);

  Serial.print("[IOTDA] connecting ");
  Serial.println(SMARTDESK_IOTDA_HOST);
  bool ok = iotdaMqtt.connect(clientId.c_str(), deviceId.c_str(), password.c_str());
  if (!ok) {
    Serial.print("[IOTDA] connect failed state=");
    Serial.println(iotdaMqtt.state());
    return false;
  }
  Serial.println("[IOTDA] connected");
  iotdaMqtt.subscribe(iotdaCommandSubscribeTopic().c_str());
  return true;
}

void iotdaLoop() {
  if (ensureIotdaMqttConnected()) {
    iotdaMqtt.loop();
  }
}

void publishTelemetryToIotda(JsonObject sensors) {
  if (!ensureIotdaMqttConnected()) {
    return;
  }

  JsonDocument report;
  JsonArray services = report["services"].to<JsonArray>();
  JsonObject service = services.add<JsonObject>();
  service["service_id"] = "smartdesk";
  JsonObject properties = service["properties"].to<JsonObject>();
  bool hasProperties = false;
  for (JsonPair kv : sensors) {
    const char *key = kv.key().c_str();
    if (isIotdaPropertyKey(key)) {
      properties[key] = kv.value();
      hasProperties = true;
    }
  }
  if (!hasProperties) {
    return;
  }

  String payload;
  serializeJson(report, payload);
  bool ok = iotdaMqtt.publish(iotdaPropertyReportTopic().c_str(), payload.c_str());
  Serial.print("[IOTDA] property report ");
  Serial.println(ok ? "ok" : "failed");
}
#endif

bool postJson(const String &path, const String &body, String *responseOut = nullptr) {
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty()) {
    return false;
  }
  HTTPClient http;
  WiFiClientSecure secureClient;
  bool began = false;
  if (serverSecure) {
    secureClient.setInsecure();
    began = http.begin(secureClient, httpBase() + path);
  } else {
    began = http.begin(httpBase() + path);
  }
  if (!began) {
    Serial.printf("[HTTP] POST %s begin failed\n", path.c_str());
    return false;
  }
  http.addHeader("Content-Type", "application/json");
  if (deviceToken.length() > 0) {
    http.addHeader("X-Device-Token", deviceToken);
  }
  int code = http.POST(body);
  bool ok = code >= 200 && code < 300;
  if (responseOut != nullptr) {
    *responseOut = http.getString();
  }
  Serial.printf("[HTTP] POST %s -> %d\n", path.c_str(), code);
  http.end();
  return ok;
}

bool getJson(const String &path, String *responseOut = nullptr) {
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty()) {
    return false;
  }
  HTTPClient http;
  WiFiClientSecure secureClient;
  bool began = false;
  if (serverSecure) {
    secureClient.setInsecure();
    began = http.begin(secureClient, httpBase() + path);
  } else {
    began = http.begin(httpBase() + path);
  }
  if (!began) {
    Serial.printf("[HTTP] GET %s begin failed\n", path.c_str());
    return false;
  }
  int code = http.GET();
  bool ok = code >= 200 && code < 300;
  if (responseOut != nullptr) {
    *responseOut = http.getString();
  }
  Serial.printf("[HTTP] GET %s -> %d\n", path.c_str(), code);
  http.end();
  return ok;
}

void forwardCommandsFromJson(const String &jsonText) {
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, jsonText);
  if (error) {
    Serial.print("[JSON] parse failed: ");
    Serial.println(error.c_str());
    return;
  }
  JsonArray commands = doc["commands"].as<JsonArray>();
  if (!commands.isNull() && commands.size() > 0) {
    sendToStm32("NET:UART?", 0);
  }
  for (JsonVariant command : commands) {
    sendToStm32(command.as<String>());
  }
}

void pollBackendCommands() {
  if (wsConnected || millis() - lastCommandPollMs < COMMAND_POLL_INTERVAL_MS) {
    return;
  }
  lastCommandPollMs = millis();
  String response;
  if (getJson("/api/hardware/commands/" + String(DEVICE_ID), &response)) {
    forwardCommandsFromJson(response);
  }
}

void sendAckToBackend(const String &line) {
  JsonDocument wsDoc;
  wsDoc["type"] = "ack";
  wsDoc["line"] = line;
  String wsPayload;
  serializeJson(wsDoc, wsPayload);
  if (wsConnected && webSocket.sendTXT(wsPayload)) {
    Serial.println("[ACK] forwarded via websocket");
    return;
  }

  JsonDocument httpDoc;
  httpDoc["device_id"] = DEVICE_ID;
  httpDoc["line"] = line;
  String body;
  serializeJson(httpDoc, body);
  if (postJson("/api/hardware/ack", body)) {
    Serial.println("[ACK] forwarded via http fallback");
  }
}

void sendButtonEventToBackend(const String &line) {
  JsonDocument doc;
  doc["type"] = "button";
  doc["device_id"] = DEVICE_ID;
  doc["line"] = line;
  doc["source"] = "stm32";
  String body;
  serializeJson(doc, body);
  if (wsConnected) {
    webSocket.sendTXT(body);
    Serial.print("[BTN] forwarded via websocket ");
    Serial.println(line);
    return;
  }
  if (postJson("/api/hardware/button", body)) {
    Serial.print("[BTN] forwarded via http ");
    Serial.println(line);
    return;
  }
  Serial.print("[BTN] forward failed ");
  Serial.println(line);
}

bool isAllowedTelemetryKey(const char *key) {
  static const char *ALLOWED_KEYS[] = {
      "pot_raw",          "pot_pct",          "ntc_raw",          "ntc_pct",
      "tracking_signal",  "aht20_ok",         "temperature_c",    "humidity_pct",
      "distance_ok",      "distance_enabled", "distance_cm",      "distance_zone",
      "env_state",        "interaction_hint", "rgb_mode",         "rgb_status",
      "rgb_reason",       "encoder_delta",    "encoder_position", "encoder_button",
  };
  for (const char *allowed : ALLOWED_KEYS) {
    if (strcmp(key, allowed) == 0) {
      return true;
    }
  }
  return false;
}

void sendTelemetryToBackend(String line) {
  line.trim();
  if (line.startsWith("BT:")) {
    line = line.substring(3);
  }
  if (!line.startsWith("{")) {
    return;
  }

  JsonDocument source;
  DeserializationError error = deserializeJson(source, line);
  if (error) {
    Serial.print("[TELEMETRY] bad json: ");
    Serial.println(error.c_str());
    return;
  }

  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["edge_id"] = EDGE_ID;
  doc["voice_state"] = voiceState;
  JsonObject sensors = doc["sensors"].to<JsonObject>();
  if (WiFi.status() == WL_CONNECTED) {
    sensors["wifi_rssi_dbm"] = WiFi.RSSI();
  }
  JsonObject sourceObject = source.as<JsonObject>();
  for (JsonPair kv : sourceObject) {
    const char *key = kv.key().c_str();
    if (isAllowedTelemetryKey(key)) {
      sensors[key] = kv.value();
    }
  }

  String body;
  serializeJson(doc, body);
#if SMARTDESK_IOTDA_ENABLED
  publishTelemetryToIotda(sensors);
#endif
  postJson("/api/hardware/telemetry", body);
}

void handleWsText(const uint8_t *payload, size_t length) {
  String text;
  text.reserve(length + 1);
  for (size_t i = 0; i < length; i++) {
    text += (char)payload[i];
  }

  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, text);
  if (error) {
    Serial.print("[WS] bad json: ");
    Serial.println(error.c_str());
    return;
  }

  String type = doc["type"] | "";
  Serial.print("[WS] ");
  Serial.println(type);

  if (type == "stm32/commands") {
    JsonArray lines = doc["lines"].as<JsonArray>();
    if (!lines.isNull() && lines.size() > 0) {
      sendToStm32("NET:UI:ACTION", 0);
      sendToStm32("NET:UART?", 0);
    }
    for (JsonVariant line : lines) {
      sendToStm32(line.as<String>());
    }
  } else if (type == "speak") {
    String speak = doc["text"] | "";
    if (speak.length() > 0) {
      sendToStm32("NET:UI:ACTION", 0);
      sendToStm32("NET:TTSHEX:" + utf8Hex(speak));
    }
  } else if (type == "ping") {
    webSocket.sendTXT("{\"type\":\"pong\"}");
  }
}

void webSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      Serial.println("[WS] connected");
      webSocket.sendTXT("{\"type\":\"ping\"}");
      break;
    case WStype_DISCONNECTED:
      wsConnected = false;
      Serial.println("[WS] disconnected");
      break;
    case WStype_TEXT:
      handleWsText(payload, length);
      break;
    default:
      break;
  }
}

bool scanTargetWifi(int32_t *channelOut, uint8_t bssidOut[6], int32_t *rssiOut, bool logResult = true) {
  int count = WiFi.scanNetworks(false, true);
  int bestIndex = -1;
  int32_t bestRssi = -127;
  int32_t bestChannel = 0;
  bool found = false;
  for (int i = 0; i < count; i++) {
    if (WiFi.SSID(i) == wifiSsid) {
      found = true;
      if (WiFi.RSSI(i) > bestRssi) {
        bestIndex = i;
        bestRssi = WiFi.RSSI(i);
        bestChannel = WiFi.channel(i);
      }
    }
  }

  if (found && bestIndex >= 0) {
    uint8_t *bssid = WiFi.BSSID(bestIndex);
    if (bssid != nullptr && bssidOut != nullptr) {
      memcpy(bssidOut, bssid, 6);
    }
    if (channelOut != nullptr) {
      *channelOut = bestChannel;
    }
    if (rssiOut != nullptr) {
      *rssiOut = bestRssi;
    }
    if (logResult) {
      Serial.printf(
          "[WIFI] scan target rssi=%d channel=%d bssid=%s enc=%d\n",
          bestRssi,
          bestChannel,
          WiFi.BSSIDstr(bestIndex).c_str(),
          (int)WiFi.encryptionType(bestIndex));
    }
  } else if (logResult) {
    Serial.printf("[WIFI] scan target not found count=%d\n", count);
  }
  WiFi.scanDelete();
  return found && bestIndex >= 0;
}

void connectWifi() {
  if (wifiSsid.isEmpty()) {
    if (millis() - lastWifiMissingLogMs > 5000) {
      lastWifiMissingLogMs = millis();
      Serial.println("[WIFI] not configured; use CFG:WIFI:<ssid>,<password>");
    }
    return;
  }
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  WiFi.disconnect(false, false);
  delay(200);
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  uint8_t targetBssid[6] = {0};
  int32_t targetChannel = 0;
  int32_t targetRssi = 0;
  bool hasTarget = scanTargetWifi(&targetChannel, targetBssid, &targetRssi);
  if (hasTarget && targetChannel > 0) {
    WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str(), targetChannel, targetBssid);
  } else {
    WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
  }
  Serial.print("[WIFI] connecting");
  unsigned long deadline = millis() + WIFI_CONNECT_TIMEOUT_MS;
  while (WiFi.status() != WL_CONNECTED && millis() < deadline) {
    Serial.print(".");
    delay(500);
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[WIFI] ip=");
    Serial.println(WiFi.localIP());
    Serial.printf("[WIFI] rssi=%d bssid=%s\n", WiFi.RSSI(), WiFi.BSSIDstr().c_str());
  } else {
    Serial.printf("[WIFI] connect timeout status=%d rssi=%d\n", (int)WiFi.status(), WiFi.RSSI());
  }
}

void startWebSocket() {
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty() || wsStarted) {
    return;
  }
  if (serverSecure) {
    webSocket.beginSSL(serverHost.c_str(), serverPort, wsPath().c_str());
  } else {
    webSocket.begin(serverHost.c_str(), serverPort, wsPath().c_str());
  }
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  webSocket.enableHeartbeat(15000, 3000, 2);
  wsStarted = true;
  Serial.print("[WS] connecting to ");
  Serial.println(wsBase() + wsPath());
}

bool pauseWebSocketForMicUpload() {
  if (!wsStarted) {
    return false;
  }
  webSocket.disconnect();
  wsConnected = false;
  wsStarted = false;
  delay(150);
  return true;
}

void sendHeartbeat(bool force = false) {
  if (!force && millis() - lastHeartbeatMs < 5000) {
    return;
  }
  lastHeartbeatMs = millis();

  bool uartOk = lastAckMs > 0 && millis() - lastAckMs < UART_OK_WINDOW_MS;
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["edge_id"] = EDGE_ID;
  doc["online"] = WiFi.status() == WL_CONNECTED;
  doc["uart_ok"] = uartOk;
  doc["voice_state"] = voiceState;
  doc["uptime_ms"] = millis();
  String body;
  serializeJson(doc, body);
  postJson("/api/hardware/heartbeat", body);
}

void setVoiceState(const String &state, bool sendNow = false) {
  voiceState = state;
  if (sendNow) {
    sendHeartbeat(true);
  }
}

bool initMicrophone() {
  if (!MIC_PATH_ENABLED) {
    micReady = false;
    Serial.println("[MIC] disabled by firmware config; browser/laptop speech path stays available");
    return false;
  }
  I2S.setAllPins(-1, MIC_CLK_PIN, MIC_DATA_PIN, -1, -1);
  micReady = I2S.begin(PDM_MONO_MODE, MIC_SAMPLE_RATE, MIC_SAMPLE_BITS);
  if (micReady) {
    Serial.println("[MIC] ready at 16 kHz mono");
  } else {
    Serial.println("[MIC] init failed; browser speech fallback stays available");
  }
  return micReady;
}

bool rejectMicPath(const char *trigger) {
  Serial.print("[MIC] disabled; ignored ");
  Serial.println(trigger);
  voiceState = "mic_disabled";
  return false;
}

void generateWavHeader(uint8_t *wavHeader, uint32_t wavSize, uint32_t sampleRate) {
  uint32_t fileSize = wavSize + MIC_WAV_HEADER_SIZE - 8;
  uint32_t byteRate = sampleRate * MIC_SAMPLE_BITS / 8;
  const uint8_t templateHeader[] = {
      'R', 'I', 'F', 'F',
      (uint8_t)(fileSize), (uint8_t)(fileSize >> 8), (uint8_t)(fileSize >> 16), (uint8_t)(fileSize >> 24),
      'W', 'A', 'V', 'E',
      'f', 'm', 't', ' ',
      0x10, 0x00, 0x00, 0x00,
      0x01, 0x00,
      0x01, 0x00,
      (uint8_t)(sampleRate), (uint8_t)(sampleRate >> 8), (uint8_t)(sampleRate >> 16), (uint8_t)(sampleRate >> 24),
      (uint8_t)(byteRate), (uint8_t)(byteRate >> 8), (uint8_t)(byteRate >> 16), (uint8_t)(byteRate >> 24),
      0x02, 0x00,
      0x10, 0x00,
      'd', 'a', 't', 'a',
      (uint8_t)(wavSize), (uint8_t)(wavSize >> 8), (uint8_t)(wavSize >> 16), (uint8_t)(wavSize >> 24),
  };
  memcpy(wavHeader, templateHeader, sizeof(templateHeader));
}

void conditionPcm16(uint8_t *pcmBuffer, size_t pcmSize) {
  int16_t *samples = (int16_t *)pcmBuffer;
  size_t sampleCount = pcmSize / sizeof(int16_t);
  if (sampleCount == 0) {
    return;
  }

  int64_t sum = 0;
  for (size_t i = 0; i < sampleCount; i++) {
    sum += samples[i];
  }
  int32_t dcOffset = (int32_t)(sum / (int64_t)sampleCount);

  for (size_t i = 0; i < sampleCount; i++) {
    int32_t value = ((int32_t)samples[i] - dcOffset) * MIC_DIGITAL_GAIN;
    if (value > 32767) {
      value = 32767;
    } else if (value < -32768) {
      value = -32768;
    }
  samples[i] = (int16_t)value;
  }
}

bool writeAllToClient(
    WiFiClient &client,
    const uint8_t *data,
    size_t length,
    uint32_t timeoutMs = 15000,
    size_t *writtenOut = nullptr) {
  size_t offset = 0;
  uint32_t deadline = millis() + timeoutMs;
  while (offset < length) {
    if (!client.connected()) {
      if (writtenOut != nullptr) {
        *writtenOut = offset;
      }
      return false;
    }

    size_t chunk = min(MIC_UPLOAD_CHUNK_SIZE, length - offset);
    int writable = client.availableForWrite();
    if (writable > 0) {
      chunk = min(chunk, (size_t)writable);
    }

    size_t written = client.write(data + offset, chunk);
    if (written > 0) {
      offset += written;
      deadline = millis() + timeoutMs;
      delay(MIC_UPLOAD_INTER_CHUNK_DELAY_MS);
      continue;
    }

    if ((int32_t)(millis() - deadline) > 0) {
      if (writtenOut != nullptr) {
        *writtenOut = offset;
      }
      return false;
    }
    delay(10);
  }
  if (writtenOut != nullptr) {
    *writtenOut = offset;
  }
  return true;
}

String formatWriteFailure(const char *part, size_t written, size_t expected) {
  String error = String(part) + " write failed at ";
  error += String((uint32_t)written);
  error += "/";
  error += String((uint32_t)expected);
  error += " rssi=";
  error += String(WiFi.RSSI());
  error += " status=";
  error += String((int)WiFi.status());
  return error;
}

int readHttpResponse(WiFiClient &client, String &response) {
  String statusLine = client.readStringUntil('\n');
  int code = 0;
  int firstSpace = statusLine.indexOf(' ');
  if (firstSpace >= 0) {
    code = statusLine.substring(firstSpace + 1, firstSpace + 4).toInt();
  }
  int contentLength = -1;
  while (client.connected()) {
    String header = client.readStringUntil('\n');
    header.trim();
    if (header.length() == 0) {
      break;
    }
    String lowerHeader = header;
    lowerHeader.toLowerCase();
    if (lowerHeader.startsWith("content-length:")) {
      contentLength = lowerHeader.substring(strlen("content-length:")).toInt();
    }
  }
  response = "";
  if (contentLength >= 0) {
    response.reserve(contentLength + 1);
    uint32_t bodyDeadline = millis() + 30000;
    while ((int)response.length() < contentLength && (client.connected() || client.available())) {
      while (client.available() && (int)response.length() < contentLength) {
        response += (char)client.read();
        bodyDeadline = millis() + 30000;
      }
      if ((int32_t)(millis() - bodyDeadline) > 0) {
        break;
      }
      delay(5);
    }
  } else {
    response = client.readString();
  }
  return code;
}

AsrUploadResult parseAsrUploadResponse(int code, const String &response) {
  AsrUploadResult result;
  result.requestOk = code >= 200 && code < 300;
  if (!result.requestOk) {
    result.error = "HTTP " + String(code);
    return result;
  }

  JsonDocument filter;
  filter["ok"] = true;
  filter["provider"] = true;
  filter["text"] = true;
  filter["error"] = true;
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, response, DeserializationOption::Filter(filter));
  if (error) {
    result.asrOk = true;
    result.error = "";
    return result;
  }

  result.asrOk = doc["ok"] | false;
  result.provider = String((const char *)(doc["provider"] | ""));
  result.text = String((const char *)(doc["text"] | ""));
  result.error = String((const char *)(doc["error"] | ""));
  return result;
}

void appendMultipartField(String &body, const String &boundary, const char *name, const String &value) {
  body += "--" + boundary + "\r\n";
  body += "Content-Disposition: form-data; name=\"";
  body += name;
  body += "\"\r\n\r\n";
  body += value;
  body += "\r\n";
}

ChunkUploadResponse parseChunkUploadAck(int code, const String &response, bool finalPart) {
  ChunkUploadResponse result;
  result.requestOk = code >= 200 && code < 300;
  if (!result.requestOk) {
    result.error = "HTTP " + String(code);
    return result;
  }

  if (finalPart) {
    JsonDocument filter;
    filter["ok"] = true;
    filter["complete"] = true;
    filter["received"] = true;
    filter["error"] = true;
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, response, DeserializationOption::Filter(filter));
    if (!error && !doc["complete"].isNull()) {
      result.chunkOk = doc["ok"] | false;
      result.complete = doc["complete"] | false;
      result.received = (size_t)((uint32_t)(doc["received"] | 0));
      result.error = String((const char *)(doc["error"] | ""));
      return result;
    }
    result.asr = parseAsrUploadResponse(code, response);
    result.chunkOk = result.asr.requestOk;
    result.complete = result.asr.requestOk;
    result.error = result.asr.error;
    return result;
  }

  JsonDocument filter;
  filter["ok"] = true;
  filter["complete"] = true;
  filter["received"] = true;
  filter["error"] = true;
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, response, DeserializationOption::Filter(filter));
  if (error) {
    result.error = "chunk ack parse failed: " + String(error.c_str());
    return result;
  }

  result.chunkOk = doc["ok"] | false;
  result.complete = doc["complete"] | false;
  result.received = (size_t)((uint32_t)(doc["received"] | 0));
  result.error = String((const char *)(doc["error"] | ""));
  return result;
}

ChunkUploadResponse postMicWavChunk(
    const String &uploadId,
    const uint8_t *data,
    size_t chunkSize,
    size_t offset,
    size_t totalAudioSize,
    bool finalPart,
    const String &source,
    bool inject) {
  ChunkUploadResponse result;
  result.received = offset;
  String boundary = "----SmartDeskChunk" + String((uint32_t)millis(), HEX) + String((uint32_t)offset, HEX);
  String prefix;
  prefix.reserve(768);
  appendMultipartField(prefix, boundary, "upload_id", uploadId);
  appendMultipartField(prefix, boundary, "offset", String((uint32_t)offset));
  appendMultipartField(prefix, boundary, "total_size", String((uint32_t)totalAudioSize));
  appendMultipartField(prefix, boundary, "final", finalPart ? "true" : "false");
  appendMultipartField(prefix, boundary, "device_id", DEVICE_ID);
  appendMultipartField(prefix, boundary, "inject", inject ? "true" : "false");
  appendMultipartField(prefix, boundary, "source", source);
  appendMultipartField(prefix, boundary, "audio_format", "wav");
  appendMultipartField(prefix, boundary, "sample_rate", String(MIC_SAMPLE_RATE));
  prefix += "--" + boundary + "\r\n";
  prefix += "Content-Disposition: form-data; name=\"chunk\"; filename=\"esp32-mic.part\"\r\n";
  prefix += "Content-Type: application/octet-stream\r\n\r\n";
  String suffix = "\r\n--" + boundary + "--\r\n";
  size_t requestSize = prefix.length() + chunkSize + suffix.length();

  WiFiClient client;
  client.setTimeout(120000);
  if (!client.connect(serverHost.c_str(), serverPort)) {
    result.error = "chunk connect failed rssi=" + String(WiFi.RSSI()) + " status=" + String((int)WiFi.status());
    return result;
  }

  Serial.printf(
      "[MIC] chunk upload offset=%u size=%u final=%u rssi=%d status=%d\n",
      (unsigned int)offset,
      (unsigned int)chunkSize,
      finalPart ? 1 : 0,
      WiFi.RSSI(),
      (int)WiFi.status());
  client.printf("POST /api/asr/transcribe/chunk HTTP/1.1\r\n");
  client.printf("Host: %s:%u\r\n", serverHost.c_str(), serverPort);
  client.printf("Connection: close\r\n");
  client.printf("Content-Type: multipart/form-data; boundary=%s\r\n", boundary.c_str());
  client.printf("Content-Length: %u\r\n\r\n", (unsigned int)requestSize);
  size_t written = 0;
  if (!writeAllToClient(client, (const uint8_t *)prefix.c_str(), prefix.length(), 15000, &written)) {
    result.error = formatWriteFailure("chunk prefix", written, prefix.length());
    client.stop();
    return result;
  }
  if (!writeAllToClient(client, data, chunkSize, 15000, &written)) {
    result.error = formatWriteFailure("chunk audio", written, chunkSize);
    client.stop();
    return result;
  }
  if (!writeAllToClient(client, (const uint8_t *)suffix.c_str(), suffix.length(), 15000, &written)) {
    result.error = formatWriteFailure("chunk suffix", written, suffix.length());
    client.stop();
    return result;
  }
  client.flush();

  String response;
  int code = readHttpResponse(client, response);
  Serial.printf("[MIC] POST /api/asr/transcribe/chunk -> %d\n", code);
  client.stop();
  return parseChunkUploadAck(code, response, finalPart);
}

AsrUploadResult uploadMicWavChunked(const uint8_t *wavBuffer, size_t wavSize, const String &source, bool inject) {
  AsrUploadResult result;
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty()) {
    result.error = "WiFi/server not ready";
    return result;
  }

  String uploadId = String(EDGE_ID) + "-" + String((uint32_t)millis(), HEX) + "-" + String((uint32_t)wavSize, HEX);
  Serial.printf(
      "[MIC] chunked upload start id=%s total=%u part=%u\n",
      uploadId.c_str(),
      (unsigned int)wavSize,
      (unsigned int)MIC_UPLOAD_CHUNKED_PART_SIZE);

  size_t offset = 0;
  while (offset < wavSize) {
    size_t partSize = min(MIC_UPLOAD_CHUNKED_PART_SIZE, wavSize - offset);
    bool finalPart = offset + partSize >= wavSize;
    bool advanced = false;
    for (uint8_t attempt = 1; attempt <= MIC_UPLOAD_CHUNKED_PART_ATTEMPTS; attempt++) {
      ChunkUploadResponse chunk = postMicWavChunk(
          uploadId,
          wavBuffer + offset,
          partSize,
          offset,
          wavSize,
          finalPart,
          source,
          inject);
      if (finalPart && chunk.requestOk && chunk.complete) {
        Serial.println("[MIC] chunked upload complete");
        return chunk.asr;
      }
      if (chunk.requestOk && chunk.chunkOk && chunk.received > offset && chunk.received <= wavSize) {
        offset = chunk.received;
        advanced = true;
        delay(40);
        break;
      }

      result.error = chunk.error;
      if (result.error.isEmpty()) {
        result.error = "chunk upload did not advance";
      }
      Serial.printf(
          "[MIC] chunk offset %u attempt %u failed: %s received=%u\n",
          (unsigned int)offset,
          attempt,
          result.error.c_str(),
          (unsigned int)chunk.received);
      delay(400 + attempt * 200);
    }
    if (!advanced) {
      return result;
    }
  }

  result.error = "chunked upload ended without final response";
  return result;
}

AsrUploadResult uploadMicWav(const uint8_t *wavBuffer, size_t wavSize, const String &source, bool inject) {
  AsrUploadResult result;
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty()) {
    result.error = "WiFi/server not ready";
    return result;
  }

  String boundary = "----SmartDeskBoundary" + String((uint32_t)millis(), HEX);
  String prefix;
  prefix.reserve(512);
  prefix += "--" + boundary + "\r\n";
  prefix += "Content-Disposition: form-data; name=\"device_id\"\r\n\r\n";
  prefix += DEVICE_ID;
  prefix += "\r\n--" + boundary + "\r\n";
  prefix += "Content-Disposition: form-data; name=\"inject\"\r\n\r\n";
  prefix += inject ? "true" : "false";
  prefix += "\r\n";
  prefix += "--" + boundary + "\r\n";
  prefix += "Content-Disposition: form-data; name=\"source\"\r\n\r\n";
  prefix += source;
  prefix += "\r\n";
  prefix += "--" + boundary + "\r\n";
  prefix += "Content-Disposition: form-data; name=\"audio_format\"\r\n\r\nwav\r\n";
  prefix += "--" + boundary + "\r\n";
  prefix += "Content-Disposition: form-data; name=\"sample_rate\"\r\n\r\n";
  prefix += String(MIC_SAMPLE_RATE);
  prefix += "\r\n--" + boundary + "\r\n";
  prefix += "Content-Disposition: form-data; name=\"audio\"; filename=\"esp32-mic.wav\"\r\n";
  prefix += "Content-Type: audio/wav\r\n\r\n";
  String suffix = "\r\n--" + boundary + "--\r\n";

  size_t totalSize = prefix.length() + wavSize + suffix.length();
  Serial.printf("[MIC] upload body %u bytes\n", (unsigned int)totalSize);

  for (uint8_t attempt = 1; attempt <= 3; attempt++) {
    result = AsrUploadResult();
    WiFiClient client;
    client.setTimeout(120000);
    if (!client.connect(serverHost.c_str(), serverPort)) {
      result.error = "connect failed rssi=" + String(WiFi.RSSI()) + " status=" + String((int)WiFi.status());
      Serial.printf("[MIC] upload attempt %u failed: %s\n", attempt, result.error.c_str());
      delay(800);
      continue;
    }

    Serial.printf(
        "[MIC] upload attempt %u rssi=%d status=%d target=%s:%u\n",
        attempt,
        WiFi.RSSI(),
        (int)WiFi.status(),
        serverHost.c_str(),
        serverPort);
    client.printf("POST /api/asr/transcribe HTTP/1.1\r\n");
    client.printf("Host: %s:%u\r\n", serverHost.c_str(), serverPort);
    client.printf("Connection: close\r\n");
    client.printf("Content-Type: multipart/form-data; boundary=%s\r\n", boundary.c_str());
    client.printf("Content-Length: %u\r\n\r\n", (unsigned int)totalSize);
    size_t written = 0;
    if (!writeAllToClient(client, (const uint8_t *)prefix.c_str(), prefix.length(), 15000, &written)) {
      result.error = formatWriteFailure("prefix", written, prefix.length());
      Serial.printf("[MIC] upload attempt %u failed: %s\n", attempt, result.error.c_str());
      client.stop();
      delay(800);
      continue;
    }
    if (!writeAllToClient(client, wavBuffer, wavSize, 15000, &written)) {
      result.error = formatWriteFailure("audio", written, wavSize);
      Serial.printf("[MIC] upload attempt %u failed: %s\n", attempt, result.error.c_str());
      client.stop();
      delay(800);
      continue;
    }
    if (!writeAllToClient(client, (const uint8_t *)suffix.c_str(), suffix.length(), 15000, &written)) {
      result.error = formatWriteFailure("suffix", written, suffix.length());
      Serial.printf("[MIC] upload attempt %u failed: %s\n", attempt, result.error.c_str());
      client.stop();
      delay(800);
      continue;
    }
    client.flush();

    String response;
    int code = readHttpResponse(client, response);
    Serial.printf("[MIC] POST /api/asr/transcribe -> %d\n", code);
    client.stop();
    result = parseAsrUploadResponse(code, response);

    if (!result.requestOk) {
      if (code <= 0 || code >= 500) {
        Serial.printf("[MIC] upload attempt %u failed: %s\n", attempt, result.error.c_str());
        delay(800);
        continue;
      }
      return result;
    }

    return result;
  }

  Serial.printf("[MIC] direct upload failed, trying chunked fallback: %s\n", result.error.c_str());
  AsrUploadResult chunked = uploadMicWavChunked(wavBuffer, wavSize, source, inject);
  if (chunked.error.isEmpty() && !chunked.requestOk) {
    chunked.error = result.error;
  }
  return chunked;
}

MicCapture captureMicWav() {
  MicCapture capture;
  size_t sampleSize = 0;
  uint32_t pcmSize = MIC_SAMPLE_RATE * (MIC_SAMPLE_BITS / 8) * MIC_RECORD_SECONDS;
  size_t wavSize = MIC_WAV_HEADER_SIZE + pcmSize;
  uint8_t *wavBuffer = allocLargeBuffer(wavSize);
  if (wavBuffer == nullptr) {
    Serial.println("[MIC] buffer alloc failed");
    return capture;
  }

  generateWavHeader(wavBuffer, pcmSize, MIC_SAMPLE_RATE);
  esp_i2s::i2s_read(esp_i2s::I2S_NUM_0, wavBuffer + MIC_WAV_HEADER_SIZE, pcmSize, &sampleSize, portMAX_DELAY);
  if (sampleSize == 0) {
    Serial.println("[MIC] recording failed");
    free(wavBuffer);
    return capture;
  }
  conditionPcm16(wavBuffer + MIC_WAV_HEADER_SIZE, sampleSize);
  generateWavHeader(wavBuffer, sampleSize, MIC_SAMPLE_RATE);
  capture.wavBuffer = wavBuffer;
  capture.wavSize = MIC_WAV_HEADER_SIZE + sampleSize;
  return capture;
}

String normalizeSelfTestText(String value) {
  value.toLowerCase();
  value.replace(" ", "");
  value.replace("\t", "");
  value.replace("\r", "");
  value.replace("\n", "");
  value.replace(",", "");
  value.replace(".", "");
  value.replace("!", "");
  value.replace("?", "");
  value.replace(":", "");
  value.replace(";", "");
  return value;
}

bool selfTestTextMatches(const String &recognized, const String &expected) {
  String actual = normalizeSelfTestText(recognized);
  String target = normalizeSelfTestText(expected);
  return target.length() > 0 && actual.indexOf(target) >= 0;
}

void sendMicSelfTestTelemetry(const String &expected, const AsrUploadResult &result, bool passed) {
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["edge_id"] = EDGE_ID;
  doc["voice_state"] = passed ? "mic_selftest_ok" : "mic_selftest_fail";
  JsonObject sensors = doc["sensors"].to<JsonObject>();
  sensors["mic_selftest_expected"] = expected;
  sensors["mic_selftest_text"] = result.text;
  sensors["mic_selftest_ok"] = passed;
  sensors["mic_selftest_provider"] = result.provider;
  sensors["mic_selftest_error"] = result.error;
  String body;
  serializeJson(doc, body);
  postJson("/api/hardware/telemetry", body);
}

bool captureAndUploadMic(bool inject = true, const String &source = "esp32_mic") {
  if (!MIC_PATH_ENABLED) {
    return rejectMicPath("capture request");
  }
  if (micBusy) {
    Serial.println("[MIC] busy");
    sendToStm32("NET:UI:ERROR", 0);
    return false;
  }
  if (!micReady) {
    Serial.println("[MIC] not ready");
    sendToStm32("NET:UI:ERROR", 0);
    return false;
  }
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty()) {
    Serial.println("[MIC] WiFi/server not ready");
    sendToStm32("NET:UI:ERROR", 0);
    return false;
  }

  micBusy = true;
  setVoiceState("recording", true);
  sendToStm32("NET:UI:LISTEN", 0);
  Serial.printf("[MIC] recording %u seconds...\n", MIC_RECORD_SECONDS);
  MicCapture capture = captureMicWav();
  if (capture.wavBuffer == nullptr || capture.wavSize == 0) {
    micBusy = false;
    setVoiceState("asr_error", true);
    sendToStm32("NET:UI:ERROR", 0);
    return false;
  }

  setVoiceState("uploading", true);
  sendToStm32("NET:UI:THINK", 0);
  Serial.printf("[MIC] captured %u bytes\n", (unsigned int)capture.wavSize);
  bool resumeWsAfterUpload = pauseWebSocketForMicUpload();
  AsrUploadResult result = uploadMicWav(capture.wavBuffer, capture.wavSize, source, inject);
  free(capture.wavBuffer);
  micBusy = false;

  if (result.requestOk && result.asrOk) {
    Serial.printf("[MIC] ASR OK provider=%s text=%s\n", result.provider.c_str(), result.text.c_str());
    setVoiceState("text_bridge", true);
    if (!inject) {
      sendToStm32("NET:UI:IDLE", 0);
    } else {
      String response;
      if (getJson("/api/hardware/commands/" + String(DEVICE_ID), &response)) {
        forwardCommandsFromJson(response);
      }
    }
    if (resumeWsAfterUpload) {
      startWebSocket();
    }
    return true;
  }

  Serial.printf(
      "[MIC] ASR FAIL transport=%s provider=%s error=%s\n",
      result.requestOk ? "ok" : "bad",
      result.provider.c_str(),
      result.error.c_str());
  setVoiceState("asr_error", true);
  sendToStm32("NET:UI:ERROR", 0);
  if (resumeWsAfterUpload) {
    startWebSocket();
  }
  return false;
}

void handleStm32ButtonEvent(const String &line) {
  sendButtonEventToBackend(line);
}

bool captureAndUploadMicAfterCue(String cueText, bool inject = true, const String &source = "esp32_mic") {
  if (!MIC_PATH_ENABLED) {
    return rejectMicPath("cue capture request");
  }
  cueText.trim();
  if (cueText.isEmpty()) {
    cueText = "三。二。一。";
  }
  if (micBusy) {
    Serial.println("[MIC] busy");
    return false;
  }
  if (!micReady) {
    Serial.println("[MIC] not ready");
    return false;
  }
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty()) {
    Serial.println("[MIC] WiFi/server not ready");
    return false;
  }

  setVoiceState("recording_cue", true);
  Serial.printf("[MIC] cue phrase=%s delay=%u ms\n", cueText.c_str(), MIC_COUNTDOWN_CUE_DELAY_MS);
  sendToStm32("NET:TTSHEX:" + utf8Hex(cueText), 0);
  delay(MIC_COUNTDOWN_CUE_DELAY_MS);
  return captureAndUploadMic(inject, source);
}

bool runMicSelfTest(String phrase) {
  if (!MIC_PATH_ENABLED) {
    return rejectMicPath("self-test request");
  }
  phrase.trim();
  if (phrase.isEmpty()) {
    phrase = "AI TEST OK";
  }
  if (micBusy) {
    Serial.println("[MIC] busy");
    return false;
  }
  if (!micReady) {
    Serial.println("[MIC] not ready");
    return false;
  }
  if (WiFi.status() != WL_CONNECTED || serverHost.isEmpty()) {
    Serial.println("[MIC] WiFi/server not ready");
    return false;
  }

  micBusy = true;
  setVoiceState("mic_selftest_recording", true);
  Serial.printf("[MIC] selftest phrase=%s\n", phrase.c_str());
  sendToStm32("NET:TTSHEX:" + utf8Hex(phrase), 0);
  MicCapture capture = captureMicWav();
  if (capture.wavBuffer == nullptr || capture.wavSize == 0) {
    micBusy = false;
    setVoiceState("mic_selftest_fail", true);
    AsrUploadResult failed;
    failed.error = "recording failed";
    sendMicSelfTestTelemetry(phrase, failed, false);
    return false;
  }

  setVoiceState("mic_selftest_uploading", true);
  Serial.printf("[MIC] selftest captured %u bytes\n", (unsigned int)capture.wavSize);
  AsrUploadResult result = uploadMicWav(capture.wavBuffer, capture.wavSize, "esp32_mic_selftest", false);
  free(capture.wavBuffer);
  micBusy = false;

  bool passed = result.requestOk && result.asrOk && selfTestTextMatches(result.text, phrase);
  Serial.printf(
      "[MIC] SELFTEST %s expected=%s recognized=%s provider=%s error=%s\n",
      passed ? "PASS" : "FAIL",
      phrase.c_str(),
      result.text.c_str(),
      result.provider.c_str(),
      result.error.c_str());
  sendMicSelfTestTelemetry(phrase, result, passed);
  setVoiceState(passed ? "text_bridge" : "mic_selftest_fail", true);
  return passed;
}

void sendUartKeepalive() {
  if (millis() - lastUartKeepaliveMs < UART_KEEPALIVE_INTERVAL_MS) {
    return;
  }
  if (lastStm32TxMs > 0 && millis() - lastStm32TxMs < UART_TX_QUIET_MS) {
    return;
  }
  if (lastAckMs > 0 && millis() - lastAckMs < UART_OK_WINDOW_MS / 2) {
    return;
  }
  lastUartKeepaliveMs = millis();
  sendToStm32("NET:UART?");
}

void scanWifi() {
  int count = WiFi.scanNetworks();
  Serial.printf("[WIFI] scan count=%d\n", count);
  for (int i = 0; i < count; i++) {
    Serial.printf("  %s rssi=%d channel=%d\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i));
  }
}

void probeTcp(String target) {
  target.trim();
  int colon = target.lastIndexOf(':');
  if (colon <= 0 || colon >= (int)target.length() - 1) {
    Serial.println("[NET] use CFG:NET:TCP:<host>:<port>");
    return;
  }

  String host = target.substring(0, colon);
  uint16_t port = (uint16_t)target.substring(colon + 1).toInt();
  String localIp = WiFi.localIP().toString();
  String gatewayIp = WiFi.gatewayIP().toString();
  String dnsIp = WiFi.dnsIP().toString();
  Serial.printf("[NET] probe host=%s port=%u wifi=%d rssi=%d local=%s gateway=%s dns=%s\n",
                host.c_str(),
                port,
                (int)WiFi.status(),
                WiFi.RSSI(),
                localIp.c_str(),
                gatewayIp.c_str(),
                dnsIp.c_str());

  IPAddress ip;
  if (WiFi.hostByName(host.c_str(), ip)) {
    String resolved = ip.toString();
    Serial.printf("[NET] resolved %s -> %s\n", host.c_str(), resolved.c_str());
  } else {
    Serial.printf("[NET] resolve failed %s\n", host.c_str());
  }

  WiFiClient probeClient;
  probeClient.setTimeout(5000);
  bool ok = probeClient.connect(host.c_str(), port);
  Serial.printf("[NET] tcp %s\n", ok ? "ok" : "failed");
  probeClient.stop();
}

bool rfidVersionHealthy(byte version) {
  return version != 0x00 && version != 0xFF;
}

byte initializeRfidReader() {
  SPI.begin(RFID_SCK_PIN, RFID_MISO_PIN, RFID_MOSI_PIN, RFID_SS_PIN);
  rfid.PCD_Init();
  delay(4);
  rfid.PCD_AntennaOn();
  rfid.PCD_SetAntennaGain(MFRC522::RxGain_max);
  return rfid.PCD_ReadRegister(MFRC522::VersionReg);
}

void printRfidStatus(bool probeCard) {
  byte version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  byte gain = rfid.PCD_GetAntennaGain();
  byte txControl = rfid.PCD_ReadRegister(MFRC522::TxControlReg);
  bool cardReady = probeCard && rfidCardReady();
  Serial.printf(
      "[RFID] status version=0x%02X healthy=%s antenna_gain=0x%02X tx_control=0x%02X card_ready=%s last_uid=%s\n",
      version,
      rfidVersionHealthy(version) ? "true" : "false",
      gain,
      txControl,
      cardReady ? "true" : "false",
      lastRfidUid.length() > 0 ? lastRfidUid.c_str() : "-");
}

void handleSerialCommand(String line) {
  line.trim();
  if (line.isEmpty()) {
    return;
  }

  if (line.startsWith("CFG:WIFI:")) {
    String value = line.substring(strlen("CFG:WIFI:"));
    if (value == "SHOW") {
      Serial.print("[CFG] ssid=");
      Serial.print(wifiSsid);
      Serial.print(" server=");
      Serial.print(serverSecure ? "https://" : "http://");
      Serial.print(serverHost);
      Serial.print(":");
      Serial.println(serverPort);
    } else if (value == "SCAN") {
      scanWifi();
    } else {
      int comma = value.indexOf(',');
      if (comma < 0) {
        Serial.println("[CFG] use CFG:WIFI:<ssid>,<password>");
      } else {
        wifiSsid = value.substring(0, comma);
        wifiPassword = value.substring(comma + 1);
        saveConfig();
        Serial.println("[CFG] wifi saved");
        WiFi.disconnect(true);
        delay(200);
        connectWifi();
        startWebSocket();
      }
    }
    return;
  }

  if (line.startsWith("CFG:NET:TCP:")) {
    probeTcp(line.substring(strlen("CFG:NET:TCP:")));
    return;
  }

  if (line.startsWith("CFG:SERVER:")) {
    if (parseServerUrl(line.substring(strlen("CFG:SERVER:")))) {
      saveConfig();
      wsStarted = false;
      webSocket.disconnect();
      Serial.println("[CFG] server saved");
      startWebSocket();
    } else {
      Serial.println("[CFG] invalid server");
    }
    return;
  }

  if (line.startsWith("CFG:TOKEN:")) {
    deviceToken = line.substring(strlen("CFG:TOKEN:"));
    deviceToken.trim();
    saveConfig();
    Serial.println(deviceToken.length() > 0 ? "[CFG] device token saved" : "[CFG] device token cleared");
    return;
  }

  if (line == "CFG:RESET") {
    prefs.begin("smartdesk", false);
    prefs.clear();
    prefs.end();
    wifiSsid = "";
    wifiPassword = "";
    serverHost = "";
    deviceToken = String(SMARTDESK_DEVICE_TOKEN);
    serverSecure = false;
    Serial.println("[CFG] cleared");
    return;
  }

  if (line == "CFG:UART:PING") {
    sendToStm32("NET:UART?");
    return;
  }

  if (line == "CFG:RFID:STATUS") {
    printRfidStatus(true);
    return;
  }

  if (line == "CFG:RFID:RESET") {
    byte version = initializeRfidReader();
    Serial.printf("[RFID] reinitialized version=0x%02X\n", version);
    printRfidStatus(true);
    return;
  }

  if (line == "CFG:MIC:REC:CUE") {
    captureAndUploadMicAfterCue("");
    return;
  }

  if (line == "CFG:MIC:REC:CUE:ASRONLY") {
    captureAndUploadMicAfterCue("", false, "esp32_mic_asr_test");
    return;
  }

  if (line.startsWith("CFG:MIC:REC:CUE:")) {
    captureAndUploadMicAfterCue(line.substring(strlen("CFG:MIC:REC:CUE:")));
    return;
  }

  if (line == "CFG:MIC:REC:ASRONLY") {
    captureAndUploadMic(false, "esp32_mic_asr_test");
    return;
  }

  if (line == "CFG:MIC:REC") {
    captureAndUploadMic();
    return;
  }

  if (line.startsWith("CFG:MIC:SELFTEST")) {
    String phrase = "";
    if (line.startsWith("CFG:MIC:SELFTEST:")) {
      phrase = line.substring(strlen("CFG:MIC:SELFTEST:"));
    }
    runMicSelfTest(phrase);
    return;
  }

  if (line.startsWith("CFG:TTS:")) {
    sendToStm32("NET:TTSHEX:" + utf8Hex(line.substring(strlen("CFG:TTS:"))));
    return;
  }

  if (line.startsWith("CFG:OLED:")) {
    sendToStm32("NET:OLED:" + line.substring(strlen("CFG:OLED:")));
    return;
  }

  if (line.startsWith("CHAT:")) {
    JsonDocument doc;
    doc["type"] = "text";
    doc["text"] = line.substring(strlen("CHAT:"));
    String body;
    serializeJson(doc, body);
    if (wsConnected) {
      webSocket.sendTXT(body);
    } else {
      Serial.println("[CHAT] websocket not connected");
    }
    return;
  }

  Serial.println("[CFG] unknown command");
}

void pollUsbSerial() {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') {
      handleSerialCommand(usbLine);
      usbLine = "";
    } else {
      usbLine += ch;
    }
  }
}

void pollStm32() {
  while (stm32Rx.available()) {
    char ch = (char)stm32Rx.read();
    if (ch == '\n' || ch == '\r') {
      stm32Line.trim();
      if (!stm32Line.startsWith("BT:") && !stm32Line.startsWith("{")) {
        int btPos = stm32Line.indexOf('B');
        int jsonPos = stm32Line.indexOf('{');
        int keepPos = -1;
        if (btPos >= 0 && jsonPos >= 0) {
          keepPos = btPos < jsonPos ? btPos : jsonPos;
        } else if (btPos >= 0) {
          keepPos = btPos;
        } else if (jsonPos >= 0) {
          keepPos = jsonPos;
        }
        if (keepPos > 0) {
          stm32Line = stm32Line.substring(keepPos);
        }
      }
      if (stm32Line.length() > 0) {
        Serial.print("[STM32 RX] ");
        Serial.println(stm32Line);
        if (stm32Line.startsWith("BT:ACK:")) {
          lastAckMs = millis();
          if (stm32Line.startsWith("BT:ACK:act_")) {
            sendAckToBackend(stm32Line);
          }
        } else if (stm32Line.startsWith("BT:PONG:")) {
          lastAckMs = millis();
        } else if (stm32Line.startsWith("BT:BTN:")) {
          handleStm32ButtonEvent(stm32Line);
        } else if (stm32Line.startsWith("BT:{") || stm32Line.startsWith("{")) {
          sendTelemetryToBackend(stm32Line);
        }
      }
      stm32Line = "";
    } else {
      stm32Line += ch;
    }
  }
}

String uidToString(MFRC522::Uid *uid) {
  String value;
  for (byte i = 0; i < uid->size; i++) {
    if (uid->uidByte[i] < 0x10) {
      value += "0";
    }
    value += String(uid->uidByte[i], HEX);
  }
  value.toUpperCase();
  return value;
}

bool rfidCardReady() {
  if (rfid.PICC_IsNewCardPresent()) {
    return true;
  }

  byte bufferATQA[2];
  byte bufferSize = sizeof(bufferATQA);
  MFRC522::StatusCode status = rfid.PICC_WakeupA(bufferATQA, &bufferSize);
  return status == MFRC522::STATUS_OK || status == MFRC522::STATUS_COLLISION;
}

void pollRfid() {
  unsigned long now = millis();
  if (now - lastRfidHealthMs >= RFID_HEALTH_INTERVAL_MS) {
    lastRfidHealthMs = now;
    byte version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
    byte txControl = rfid.PCD_ReadRegister(MFRC522::TxControlReg);
    byte gain = rfid.PCD_GetAntennaGain();
    if (!rfidVersionHealthy(version) || (txControl & 0x03) != 0x03 || gain != MFRC522::RxGain_max) {
      Serial.printf(
          "[RFID] reader recovery version=0x%02X tx_control=0x%02X antenna_gain=0x%02X\n",
          version,
          txControl,
          gain);
      initializeRfidReader();
    }
  }
  if (now - lastRfidMs < RFID_POLL_INTERVAL_MS) {
    return;
  }
  lastRfidMs = now;
  if (!rfidCardReady() || !rfid.PICC_ReadCardSerial()) {
    return;
  }
  String uid = uidToString(&rfid.uid);
  if (uid == lastRfidUid && now - lastRfidSeenMs < RFID_REPEAT_SUPPRESS_MS) {
    Serial.print("[RFID] repeat skipped ");
    Serial.println(uid);
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    return;
  }
  lastRfidUid = uid;
  lastRfidSeenMs = now;

  Serial.print("[RFID] ");
  Serial.println(uid);
  sendToStm32("NET:RFID:SCAN:" + uid, 0);
  sendToStm32("NET:BEEP", 0);

  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["uid"] = uid;
  doc["source"] = "rc522";
  String body;
  serializeJson(doc, body);
  String response;
  bool ok = postJson("/api/rfid/scan", body, &response);
  if (!ok) {
    Serial.println("[RFID] scan post failed");
    sendToStm32("NET:RFID:NETWORK_ERROR", 0);
  } else {
    Serial.println("[RFID] scan accepted by backend");
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}

void setup() {
  Serial.begin(115200);
  delay(800);
  Serial.println();
  Serial.println("[BOOT] smart desktop ESP32S3 bridge");

  stm32Tx.begin(9600, SERIAL_8N1, -1, STM32_TX_PIN);
  stm32Rx.begin(4800, SERIAL_8N1, STM32_RX_PIN, -1);

  byte rfidVersion = initializeRfidReader();
  Serial.print("[RFID] reader version=0x");
  Serial.println(rfidVersion, HEX);
  initMicrophone();

  loadConfig();
  if (strlen(SMARTDESK_BOOTSTRAP_SERVER_URL) > 0 && parseServerUrl(SMARTDESK_BOOTSTRAP_SERVER_URL)) {
    saveConfig();
    Serial.print("[CFG] bootstrap server=");
    Serial.println(httpBase());
  }
  connectWifi();
  startWebSocket();
}

void loop() {
  pollUsbSerial();
  pollStm32();
  pollRfid();
  if (wsStarted) {
    webSocket.loop();
  } else {
    connectWifi();
    startWebSocket();
  }
#if SMARTDESK_IOTDA_ENABLED
  iotdaLoop();
#endif
  pollBackendCommands();
  sendUartKeepalive();
  sendHeartbeat();
}
