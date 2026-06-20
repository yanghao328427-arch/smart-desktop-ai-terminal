#include <Arduino.h>
#include <SoftwareSerial.h>
#include <Wire.h>
#include "oled_font5x7.h"

// STM32F103C8T6 board baseline from docs/HARDWARE_WIRING.md.
static const uint32_t ESP_IN_BAUD = 9600;   // ESP32S3 TX -> STM32 PB11 / Serial3 RX
static const uint32_t ESP_ACK_BAUD = 4800;  // STM32 PB3 software TX -> ESP32S3 RX

static const int PIN_BUZZER = PB9;
static const int PIN_DRV8833_IN1 = PA0;  // TIM2_CH1 in the Botelvdong DRV8833 example.
static const int PIN_DRV8833_IN2 = PA1;  // TIM2_CH2 in the Botelvdong DRV8833 example.
static const int PIN_RGB_BLUE = PA6;
static const int PIN_RGB_GREEN = PA7;
static const int PIN_RGB_RED = PB0;
static const int PIN_SERVO = PB8;
static const int PIN_NTC = PA4;
static const int PIN_POTENTIOMETER = PA5;
static const int PIN_ULTRASONIC_TRIG = PA11;
static const int PIN_ULTRASONIC_ECHO = PA10;
static const int PIN_ENCODER_A = PA8;
static const int PIN_ENCODER_B = PA9;
static const int PIN_ENCODER_BUTTON = PB15;
static const int PIN_TRACKING_SENSOR = PB14;
#ifndef DEMO_BUTTON_PIN
static const int PIN_DEMO_BUTTON = PB13;  // KEY2 on the Botelvdong STM32 learning kit.
#else
static const int PIN_DEMO_BUTTON = DEMO_BUTTON_PIN;
#endif

#ifndef ULTRASONIC_ENABLED_BY_DEFAULT
#define ULTRASONIC_ENABLED_BY_DEFAULT 1
#endif

#ifndef DRV8833_CONNECTED_BY_DEFAULT
#define DRV8833_CONNECTED_BY_DEFAULT 1
#endif

static const uint32_t TELEMETRY_INTERVAL_MS = 4000;
static const uint32_t UI_FRAME_INTERVAL_MS = 120;
static const uint32_t RGB_FRAME_INTERVAL_MS = 80;
static const uint32_t OLED_FLUSH_INTERVAL_MS = 12;
static const uint32_t SERVO_PULSE_PERIOD_US = 20000;
static const uint32_t SERVO_HOLD_MS = 800;
static const uint16_t SERVO_MIN_PULSE_US = 500;
static const uint16_t SERVO_MAX_PULSE_US = 2500;
static const uint8_t AHT20_I2C_ADDRESS = 0x38;
static const uint8_t AHT20_CMD_INIT = 0xBE;
static const uint8_t AHT20_CMD_MEASURE = 0xAC;
static const uint32_t ULTRASONIC_TIMEOUT_US = 25000;
static const uint16_t ANALOG_RAW_MAX = 1023;
static const uint8_t DRV8833_FAN_LEVEL1_DUTY = 217;  // ~85%; lower duty may fail to start small fans.
static const uint8_t DRV8833_FAN_LEVEL2_DUTY = 235;  // ~92%.
static const uint8_t DRV8833_FAN_LEVEL3_DUTY = 255;  // Full speed.
static const uint16_t MUSIC_NOTE_GAP_MS = 35;
static const uint32_t RGB_EVENT_HOLD_MS = 1800;
static const uint32_t RGB_ERROR_HOLD_MS = 3200;
static const uint8_t OLED_WIDTH = 128;
static const uint8_t OLED_HEIGHT = 64;
static const uint8_t OLED_PAGES = OLED_HEIGHT / 8;
static const uint8_t OLED_ADDR_PRIMARY = 0x3D;   // 0x7A in 8-bit datasheets.
static const uint8_t OLED_ADDR_FALLBACK = 0x3C;
static const uint8_t OLED_CHUNK_BYTES = 16;
static const uint8_t UI_PANEL_X = 4;
static const uint8_t UI_TEXT_X = 6;
static const uint8_t UI_RIGHT_MARGIN = 10;
static const uint8_t UI_PANEL_WIDTH = OLED_WIDTH - UI_PANEL_X - UI_RIGHT_MARGIN;
static const uint8_t UI_MAX_CHARS = (OLED_WIDTH - UI_TEXT_X - UI_RIGHT_MARGIN) / 6;
static const uint16_t UI_DEMO_DEFAULT_STEP_MS = 950;
static const uint32_t BUTTON_DEBOUNCE_MS = 35;
static const uint32_t TELEMETRY_ESP_QUIET_MS = 3000;

// RX pin is unused. PB3 is the documented software TX back to ESP32S3.
SoftwareSerial espAckSerial(PB4, PB3);
// USB-UART on the board is wired to USART2 PA3/PA2 and is our debug console on COM7.
HardwareSerial usbConsole(PA3, PA2);
// BluePill F103C8 variants do not always pre-instantiate Serial3, so bind USART3 explicitly.
HardwareSerial espCommandSerial(PB11, PB10);

struct MelodyNote {
  uint16_t frequency;
  uint16_t durationMs;
};

String usbLine;
String espLine;
uint32_t espEmptyDelimiterCount = 0;
uint32_t lastTelemetryMs = 0;
uint32_t lastEspRxActivityMs = 0;
bool aht20Initialized = false;
bool ultrasonicEnabled = ULTRASONIC_ENABLED_BY_DEFAULT != 0;
bool drv8833Connected = DRV8833_CONNECTED_BY_DEFAULT != 0;
uint8_t encoderLastState = 0;
long encoderPosition = 0;
long encoderDeltaSinceTelemetry = 0;
bool servoActive = false;
bool servoPulseHigh = false;
uint16_t servoPulseWidthUs = 1500;
uint32_t servoPulseStartedUs = 0;
uint32_t nextServoPulseUs = 0;
uint32_t lastServoCommandMs = 0;
const MelodyNote *activeMelody = nullptr;
uint8_t activeMelodyLength = 0;
uint8_t activeMelodyIndex = 0;
uint32_t musicStepStartedMs = 0;
uint16_t musicStepTotalMs = 0;
bool musicPlaying = false;

static const uint8_t SYN6288_FRAME_HEADER = 0xFD;
static const uint8_t SYN6288_CMD_SYNTHESIS = 0x01;
static const uint8_t SYN6288_TYPE_UNICODE = 0x03;
static const size_t SYN6288_MAX_TEXT_BYTES = 200;

enum UiEventType : uint8_t {
  UI_EVENT_BOOT,
  UI_EVENT_DEMO,
  UI_EVENT_LISTEN,
  UI_EVENT_THINK,
  UI_EVENT_ACTION,
  UI_EVENT_ACK,
  UI_EVENT_UART,
  UI_EVENT_I2C,
  UI_EVENT_TELEMETRY,
  UI_EVENT_OLED,
  UI_EVENT_TTS,
  UI_EVENT_FAN_ON,
  UI_EVENT_FAN_OFF,
  UI_EVENT_BEEP,
  UI_EVENT_MUSIC,
  UI_EVENT_LOCK_ON,
  UI_EVENT_LOCK_OFF,
  UI_EVENT_AI_BUSY,
  UI_EVENT_AI_IDLE,
  UI_EVENT_AI_OFF,
  UI_EVENT_SERVO,
  UI_EVENT_RFID,
  UI_EVENT_ERROR
};

struct RgbState {
  bool red;
  bool green;
  bool blue;
};

struct UiEventState {
  UiEventType type;
  String detail;
  String actionId;
  uint32_t startedMs;
  uint32_t parseMs;
  uint32_t actionMs;
  uint32_t lightMs;
  uint32_t ackMs;
  bool hasLight;
  bool ackSeen;
  bool ackOk;
  bool wrapped;
};

struct UiDemoStep {
  UiEventType type;
  const char *detail;
  uint16_t durationMs;
  int8_t fanState;
  bool beep;
  const char *ttsHex;
};

struct ParsedCommand {
  String actionId;
  String command;
  bool wrapped;
};

UiEventState uiEvent;
uint8_t oledAddress = OLED_ADDR_PRIMARY;
uint8_t oledBuffer[OLED_WIDTH * OLED_PAGES];
uint8_t oledFlushPage = 0;
bool oledAvailable = false;
bool oledDirty = false;
bool oledRenderPending = false;
uint32_t lastUiFrameMs = 0;
uint32_t lastRgbFrameMs = 0;
uint32_t lastOledFlushMs = 0;
uint32_t ackFlashUntilMs = 0;
bool ackFlashOk = true;
bool commandLightMeasureActive = false;
bool commandHadLight = false;
uint32_t commandLightResponseMs = 0;
bool uiDemoActive = false;
uint8_t uiDemoIndex = 0;
uint32_t uiDemoStepStartedMs = 0;
bool demoButtonLastReading = false;
bool demoButtonStablePressed = false;
uint32_t demoButtonLastChangeMs = 0;
bool rgbSensorMode = true;
bool latestTelemetryValid = false;
int latestPotRaw = 0;
uint8_t latestPotPct = 0;
int latestNtcRaw = 0;
uint8_t latestNtcPct = 0;
bool latestTrackingSignal = false;
bool latestAhtOk = false;
float latestTemperatureC = 0.0f;
float latestHumidityPct = 0.0f;
bool latestDistanceOk = false;
bool latestDistanceEnabled = false;
float latestDistanceCm = 0.0f;
long latestEncoderPosition = 0;
long latestEncoderDelta = 0;
bool latestEncoderButtonPressed = false;
const char *latestDistanceZone = "unknown";
const char *latestEnvState = "unknown";
const char *latestInteractionHint = "idle";
const char *latestRgbStatus = "waiting";
const char *latestRgbReason = "waiting_telemetry";

static const UiDemoStep UI_DEMO_STEPS[] = {
  {UI_EVENT_OLED, "OLED READY", UI_DEMO_DEFAULT_STEP_MS, -1, false, nullptr},
  {UI_EVENT_AI_BUSY, "AI BUSY", UI_DEMO_DEFAULT_STEP_MS, -1, false, nullptr},
  {UI_EVENT_TTS, "TTS HELLO", 1200, -1, false, "E4BDA0E5A5BD"},
  {UI_EVENT_FAN_ON, "FAN ON L2", UI_DEMO_DEFAULT_STEP_MS, 1, false, nullptr},
  {UI_EVENT_BEEP, "BEEP ALERT", UI_DEMO_DEFAULT_STEP_MS, -1, true, nullptr},
  {UI_EVENT_LOCK_ON, "LOCKED", UI_DEMO_DEFAULT_STEP_MS, -1, false, nullptr},
  {UI_EVENT_LOCK_OFF, "UNLOCK ACK", UI_DEMO_DEFAULT_STEP_MS, -1, false, nullptr},
  {UI_EVENT_RFID, "RFID ACK OK", UI_DEMO_DEFAULT_STEP_MS, -1, false, nullptr},
  {UI_EVENT_FAN_OFF, "FAN OFF", UI_DEMO_DEFAULT_STEP_MS, 0, false, nullptr},
  {UI_EVENT_AI_IDLE, "AI IDLE", UI_DEMO_DEFAULT_STEP_MS, -1, false, nullptr}
};
static const uint8_t UI_DEMO_STEP_COUNT = sizeof(UI_DEMO_STEPS) / sizeof(UI_DEMO_STEPS[0]);

static const MelodyNote MELODY_SUCCESS[] = {
  {523, 120}, {659, 120}, {784, 160}, {1047, 260}
};

static const MelodyNote MELODY_ALERT[] = {
  {988, 100}, {0, 70}, {988, 100}, {0, 70}, {784, 240}
};

static const MelodyNote MELODY_SCALE[] = {
  {262, 110}, {294, 110}, {330, 110}, {349, 110},
  {392, 110}, {440, 110}, {494, 110}, {523, 220}
};

static const MelodyNote MELODY_STARTUP[] = {
  {392, 100}, {523, 100}, {659, 120}, {784, 220}
};

static const MelodyNote MELODY_BIRTHDAY[] = {
  {392, 170}, {392, 170}, {440, 340}, {392, 340}, {523, 340}, {494, 520},
  {0, 120},
  {392, 170}, {392, 170}, {440, 340}, {392, 340}, {587, 340}, {523, 520}
};

void writeBack(const String &line) {
  usbConsole.println(line);
  espAckSerial.println(line);
}

void sendAck(const ParsedCommand &parsed, bool ok) {
  if (parsed.wrapped && parsed.actionId.length() > 0) {
    writeBack("BT:ACK:" + parsed.actionId + ":" + (ok ? "OK" : "ERR"));
  } else {
    writeBack(ok ? "BT:OK" : "BT:ERR");
  }
}

ParsedCommand parseLine(String line) {
  line.trim();
  ParsedCommand parsed;
  parsed.actionId = "";
  parsed.command = line;
  parsed.wrapped = false;

  if (!line.startsWith("NET:CMD:")) {
    return parsed;
  }

  int idStart = strlen("NET:CMD:");
  int commandStart = line.indexOf(":NET:", idStart);
  if (commandStart < 0) {
    parsed.command = "";
    return parsed;
  }

  parsed.wrapped = true;
  parsed.actionId = line.substring(idStart, commandStart);
  parsed.command = line.substring(commandStart + 1);
  return parsed;
}

String upperCopy(const String &text) {
  String result = text;
  result.toUpperCase();
  return result;
}

bool containsUpperToken(const String &text, const char *token) {
  return upperCopy(text).indexOf(token) >= 0;
}

String compactForDisplay(const String &text, uint8_t maxLen) {
  String out;
  bool lastReplacement = false;
  for (unsigned int i = 0; i < text.length() && out.length() < maxLen; ++i) {
    uint8_t ch = (uint8_t)text.charAt(i);
    if (ch >= 32 && ch <= 126) {
      out += (char)ch;
      lastReplacement = false;
    } else if (!lastReplacement) {
      out += '?';
      lastReplacement = true;
    }
  }
  return out;
}

const char *eventLabel(UiEventType type) {
  switch (type) {
    case UI_EVENT_BOOT:
      return "BOOT";
    case UI_EVENT_DEMO:
      return "UI DEMO";
    case UI_EVENT_LISTEN:
      return "LISTEN";
    case UI_EVENT_THINK:
      return "THINK";
    case UI_EVENT_ACTION:
      return "ACTION";
    case UI_EVENT_ACK:
      return "ACK";
    case UI_EVENT_UART:
      return "UART";
    case UI_EVENT_I2C:
      return "I2C SCAN";
    case UI_EVENT_TELEMETRY:
      return "TELEMETRY";
    case UI_EVENT_OLED:
      return "OLED";
    case UI_EVENT_TTS:
      return "SYN6288 TTS";
    case UI_EVENT_FAN_ON:
      return "FAN ON";
    case UI_EVENT_FAN_OFF:
      return "FAN OFF";
    case UI_EVENT_BEEP:
      return "BEEP";
    case UI_EVENT_MUSIC:
      return "MUSIC";
    case UI_EVENT_LOCK_ON:
      return "LOCK ON";
    case UI_EVENT_LOCK_OFF:
      return "LOCK OFF";
    case UI_EVENT_AI_BUSY:
      return "AI BUSY";
    case UI_EVENT_AI_IDLE:
      return "AI IDLE";
    case UI_EVENT_AI_OFF:
      return "AI OFF";
    case UI_EVENT_SERVO:
      return "SERVO";
    case UI_EVENT_RFID:
      return "RFID";
    case UI_EVENT_ERROR:
      return "ERROR";
  }
  return "EVENT";
}

RgbState rgbState(bool red, bool green, bool blue) {
  RgbState state;
  state.red = red;
  state.green = green;
  state.blue = blue;
  return state;
}

uint8_t analogPercent(int raw) {
  if (raw <= 0) {
    return 0;
  }
  uint32_t pct = ((uint32_t)raw * 100UL) / ANALOG_RAW_MAX;
  return pct > 100 ? 100 : (uint8_t)pct;
}

const char *distanceZone(bool enabled, bool ok, float cm) {
  if (!enabled) {
    return "disabled";
  }
  if (!ok) {
    return "missing";
  }
  if (cm < 10.0f) {
    return "too_close";
  }
  if (cm < 35.0f) {
    return "near";
  }
  if (cm < 90.0f) {
    return "ready";
  }
  return "far";
}

const char *environmentState(bool ok, float temperatureC, float humidityPct) {
  if (!ok) {
    return "missing";
  }
  if (temperatureC >= 32.0f) {
    return "hot";
  }
  if (temperatureC >= 29.0f) {
    return "warm";
  }
  if (temperatureC <= 16.0f) {
    return "cold";
  }
  if (humidityPct >= 75.0f) {
    return "humid";
  }
  if (humidityPct <= 30.0f) {
    return "dry";
  }
  return "comfortable";
}

const char *interactionHint(bool trackingSignal, bool encoderButtonPressed, long encoderDelta,
                            bool distanceOk, float distanceCm) {
  if (encoderButtonPressed) {
    return "encoder_press";
  }
  if (encoderDelta != 0) {
    return "encoder_turn";
  }
  if (distanceOk && distanceCm < 35.0f) {
    return "object_near";
  }
  if (trackingSignal) {
    return "tracking_high";
  }
  return "idle";
}

void updateLatestRgbStatus() {
  if (!latestTelemetryValid) {
    latestRgbStatus = "waiting";
    latestRgbReason = "waiting_telemetry";
    return;
  }

  if (!latestAhtOk || (latestDistanceEnabled && !latestDistanceOk)) {
    latestRgbStatus = "sensor_check";
    latestRgbReason = !latestAhtOk ? "aht20_missing" : "distance_missing";
    return;
  }

  if (latestDistanceOk && latestDistanceCm < 10.0f) {
    latestRgbStatus = "too_close";
    latestRgbReason = "object_too_close";
    return;
  }

  if (strcmp(latestEnvState, "comfortable") != 0) {
    latestRgbStatus = "env_watch";
    latestRgbReason = latestEnvState;
    return;
  }

  if (latestDistanceOk && latestDistanceCm < 35.0f) {
    latestRgbStatus = "near_object";
    latestRgbReason = "interaction_zone";
    return;
  }

  if (latestTrackingSignal) {
    latestRgbStatus = "tracking_high";
    latestRgbReason = "tracking_signal_high";
    return;
  }

  latestRgbStatus = "ready";
  latestRgbReason = "all_ok";
}

String buildRgbStatusLine() {
  String line = "BT:RGB:";
  line += "mode=";
  line += rgbSensorMode ? "sensor" : "event";
  line += ",status=";
  line += latestRgbStatus;
  line += ",reason=";
  line += latestRgbReason;
  line += ",env=";
  line += latestEnvState;
  line += ",distance=";
  line += latestDistanceZone;
  line += ",pot_pct=";
  line += String(latestPotPct);
  line += ",ntc_pct=";
  line += String(latestNtcPct);
  line += ",tracking=";
  line += latestTrackingSignal ? "1" : "0";
  return line;
}

RgbState eventBaseRgb(UiEventType type) {
  switch (type) {
    case UI_EVENT_BOOT:
      return rgbState(false, false, true);
    case UI_EVENT_DEMO:
      return rgbState(true, true, false);
    case UI_EVENT_LISTEN:
      return rgbState(false, false, true);
    case UI_EVENT_THINK:
      return rgbState(true, true, false);
    case UI_EVENT_ACTION:
      return rgbState(false, false, true);
    case UI_EVENT_ACK:
      return rgbState(false, true, false);
    case UI_EVENT_UART:
      return rgbState(false, true, true);
    case UI_EVENT_I2C:
      return rgbState(false, true, true);
    case UI_EVENT_TELEMETRY:
      return rgbState(false, false, true);
    case UI_EVENT_OLED:
      return rgbState(false, true, true);
    case UI_EVENT_TTS:
      return rgbState(false, true, false);
    case UI_EVENT_FAN_ON:
      return rgbState(false, true, true);
    case UI_EVENT_FAN_OFF:
      return rgbState(false, false, true);
    case UI_EVENT_BEEP:
      return rgbState(true, false, true);
    case UI_EVENT_MUSIC:
      return rgbState(true, false, true);
    case UI_EVENT_LOCK_ON:
      return rgbState(true, false, false);
    case UI_EVENT_LOCK_OFF:
      return rgbState(false, true, false);
    case UI_EVENT_AI_BUSY:
      return rgbState(true, true, false);
    case UI_EVENT_AI_IDLE:
      return rgbState(false, true, false);
    case UI_EVENT_AI_OFF:
      return rgbState(false, false, false);
    case UI_EVENT_RFID:
      return rgbState(false, true, true);
    case UI_EVENT_ERROR:
      return rgbState(true, false, false);
    case UI_EVENT_SERVO:
      return rgbState(true, true, false);
  }
  return rgbState(false, false, true);
}

UiEventType classifyNetCommand(const String &command, const String &actionId) {
  if (containsUpperToken(command, "RFID") || containsUpperToken(actionId, "RFID")) {
    return UI_EVENT_RFID;
  }
  if (command == "NET:UI:LISTEN") {
    return UI_EVENT_LISTEN;
  }
  if (command == "NET:UI:THINK") {
    return UI_EVENT_THINK;
  }
  if (command == "NET:UI:ACTION") {
    return UI_EVENT_ACTION;
  }
  if (command == "NET:UI:ACK") {
    return UI_EVENT_ACK;
  }
  if (command == "NET:UI:OUTPUT") {
    return UI_EVENT_AI_IDLE;
  }
  if (command == "NET:UI:IDLE") {
    return UI_EVENT_AI_IDLE;
  }
  if (command == "NET:UI:ERROR") {
    return UI_EVENT_ERROR;
  }
  if (command.startsWith("NET:UI:")) {
    return UI_EVENT_DEMO;
  }
  if (command == "NET:UART?") {
    return UI_EVENT_UART;
  }
  if (command == "NET:I2C?") {
    return UI_EVENT_I2C;
  }
  if (command == "NET:TELEMETRY?") {
    return UI_EVENT_TELEMETRY;
  }
  if (command.startsWith("NET:RGB:")) {
    return UI_EVENT_TELEMETRY;
  }
  if (command.startsWith("NET:TTS:") || command.startsWith("NET:TTSHEX:")) {
    return UI_EVENT_TTS;
  }
  if (command.startsWith("NET:OLED:")) {
    return UI_EVENT_OLED;
  }
  if (command == "NET:BEEP") {
    return UI_EVENT_BEEP;
  }
  if (command.startsWith("NET:MUSIC:")) {
    return UI_EVENT_MUSIC;
  }
  if (command.startsWith("NET:FAN:ON")) {
    return UI_EVENT_FAN_ON;
  }
  if (command == "NET:FAN:OFF") {
    return UI_EVENT_FAN_OFF;
  }
  if (command == "NET:LOCK:ON") {
    return UI_EVENT_LOCK_ON;
  }
  if (command == "NET:LOCK:OFF") {
    return UI_EVENT_LOCK_OFF;
  }
  if (command == "NET:AI:BUSY") {
    return UI_EVENT_AI_BUSY;
  }
  if (command == "NET:AI:IDLE") {
    return UI_EVENT_AI_IDLE;
  }
  if (command == "NET:AI:OFF") {
    return UI_EVENT_AI_OFF;
  }
  if (command.startsWith("NET:SERVO:")) {
    return UI_EVENT_SERVO;
  }
  return UI_EVENT_ERROR;
}

String commandPreview(const String &command) {
  if (command.startsWith("NET:TTSHEX:")) {
    uint16_t hexChars = command.length() - strlen("NET:TTSHEX:");
    return String("TTSHEX ") + String(hexChars / 2) + "B";
  }
  if (command.startsWith("NET:TTS:")) {
    return String("TTS ") + compactForDisplay(command.substring(strlen("NET:TTS:")), 16);
  }
  if (command.startsWith("NET:OLED:")) {
    return String("OLED ") + compactForDisplay(command.substring(strlen("NET:OLED:")), 16);
  }
  if (command.startsWith("NET:FAN:ON")) {
    return "FAN ON";
  }
  if (command == "NET:FAN:OFF") {
    return "FAN OFF";
  }
  if (command == "NET:BEEP") {
    return "BEEP";
  }
  if (command.startsWith("NET:MUSIC:")) {
    return String("MUSIC ") + compactForDisplay(command.substring(strlen("NET:MUSIC:")), 12);
  }
  if (command.startsWith("NET:LOCK:")) {
    return command.substring(strlen("NET:"));
  }
  if (command.startsWith("NET:AI:")) {
    return command.substring(strlen("NET:"));
  }
  if (command.startsWith("NET:UI:")) {
    return command.substring(strlen("NET:"));
  }
  if (command == "NET:UART?") {
    return "UART PING";
  }
  if (command == "NET:I2C?") {
    return "I2C SCAN";
  }
  if (command == "NET:TELEMETRY?") {
    return "TELEMETRY";
  }
  if (command.startsWith("NET:RGB:")) {
    return String("RGB ") + compactForDisplay(command.substring(strlen("NET:RGB:")), 12);
  }
  if (command.startsWith("NET:ULTRASONIC:")) {
    return String("ULTRASONIC ") + compactForDisplay(command.substring(strlen("NET:ULTRASONIC:")), 10);
  }
  if (command.startsWith("NET:MOTOR:")) {
    return String("MOTOR ") + compactForDisplay(command.substring(strlen("NET:MOTOR:")), 12);
  }
  if (command.startsWith("NET:SERVO:")) {
    return String("SERVO ") + compactForDisplay(command.substring(strlen("NET:SERVO:")), 12);
  }
  return compactForDisplay(command, 20);
}

bool stringMatchesAt(const String &text, int index, const char *prefix) {
  size_t prefixLen = strlen(prefix);
  if (index < 0 || index + (int)prefixLen > (int)text.length()) {
    return false;
  }
  for (size_t i = 0; i < prefixLen; ++i) {
    if (text.charAt(index + i) != prefix[i]) {
      return false;
    }
  }
  return true;
}

bool isKnownNetCommandStart(const String &text, int index) {
  if (index < 0 || index >= (int)text.length()) {
    return false;
  }
  if (index > 0 && text.charAt(index - 1) == ':') {
    return false;
  }

  static const char *prefixes[] = {
    "NET:CMD:",
    "NET:UART?",
    "NET:I2C?",
    "NET:TELEMETRY?",
    "NET:ULTRASONIC:",
    "NET:MOTOR:",
    "NET:TTS:",
    "NET:TTSHEX:",
    "NET:OLED:",
    "NET:BEEP",
    "NET:MUSIC:",
    "NET:FAN:",
    "NET:LOCK:",
    "NET:AI:",
    "NET:UI:",
    "NET:RGB:",
    "NET:SERVO:",
    "NET:RFID:"
  };

  for (uint8_t i = 0; i < sizeof(prefixes) / sizeof(prefixes[0]); ++i) {
    if (stringMatchesAt(text, index, prefixes[i])) {
      return true;
    }
  }
  return false;
}

int findKnownNetCommandStart(const String &text, int fromIndex) {
  for (int i = fromIndex; i < (int)text.length(); ++i) {
    if (isKnownNetCommandStart(text, i)) {
      return i;
    }
  }
  return -1;
}

void writeRgbRaw(bool red, bool green, bool blue) {
  digitalWrite(PIN_RGB_RED, red ? HIGH : LOW);
  digitalWrite(PIN_RGB_GREEN, green ? HIGH : LOW);
  digitalWrite(PIN_RGB_BLUE, blue ? HIGH : LOW);
}

void setRgb(bool red, bool green, bool blue) {
  uint32_t startedMs = millis();
  writeRgbRaw(red, green, blue);
  if (commandLightMeasureActive && !commandHadLight) {
    commandHadLight = true;
    commandLightResponseMs = millis() - startedMs;
  }
}

void beginUiEvent(UiEventType type, const String &detail, const String &actionId, bool wrapped, uint32_t startedMs) {
  uiEvent.type = type;
  uiEvent.detail = detail;
  uiEvent.actionId = actionId;
  uiEvent.startedMs = startedMs;
  uiEvent.parseMs = 0;
  uiEvent.actionMs = 0;
  uiEvent.lightMs = 0;
  uiEvent.ackMs = 0;
  uiEvent.hasLight = false;
  uiEvent.ackSeen = false;
  uiEvent.ackOk = false;
  uiEvent.wrapped = wrapped;
  oledRenderPending = true;
}

void finishUiEvent(uint32_t parseMs, uint32_t actionMs, uint32_t ackMs, bool ok) {
  uiEvent.parseMs = parseMs;
  uiEvent.actionMs = actionMs;
  uiEvent.lightMs = commandLightResponseMs;
  uiEvent.hasLight = commandHadLight;
  uiEvent.ackMs = ackMs;
  uiEvent.ackSeen = true;
  uiEvent.ackOk = ok;
  ackFlashOk = ok;
  ackFlashUntilMs = millis() + 180;
  oledRenderPending = true;
}

void logEventTiming(const char *source, const ParsedCommand &parsed, bool ok) {
  usbConsole.print("[EVT] source=");
  usbConsole.print(source);
  usbConsole.print(" event=");
  usbConsole.print(eventLabel(uiEvent.type));
  usbConsole.print(" action_id=");
  usbConsole.print(parsed.actionId.length() > 0 ? parsed.actionId : "-");
  usbConsole.print(" status=");
  usbConsole.print(ok ? "OK" : "ERR");
  usbConsole.print(" parse_ms=");
  usbConsole.print(uiEvent.parseMs);
  usbConsole.print(" action_ms=");
  usbConsole.print(uiEvent.actionMs);
  usbConsole.print(" light_ms=");
  if (uiEvent.hasLight) {
    usbConsole.print(uiEvent.lightMs);
  } else {
    usbConsole.print("n/a");
  }
  usbConsole.print(" ack_total_ms=");
  usbConsole.print(uiEvent.ackMs);
  usbConsole.print(" detail=");
  usbConsole.println(compactForDisplay(uiEvent.detail, 40));
}

void clearOledBuffer() {
  memset(oledBuffer, 0, sizeof(oledBuffer));
}

void oledSetPixel(uint8_t x, uint8_t y, bool on) {
  if (x >= OLED_WIDTH || y >= OLED_HEIGHT) {
    return;
  }
  uint16_t index = x + (uint16_t)(y / 8) * OLED_WIDTH;
  uint8_t mask = 1 << (y & 0x07);
  if (on) {
    oledBuffer[index] |= mask;
  } else {
    oledBuffer[index] &= ~mask;
  }
}

void oledFillRect(uint8_t x, uint8_t y, uint8_t w, uint8_t h, bool on) {
  for (uint8_t yy = y; yy < y + h && yy < OLED_HEIGHT; ++yy) {
    for (uint8_t xx = x; xx < x + w && xx < OLED_WIDTH; ++xx) {
      oledSetPixel(xx, yy, on);
    }
  }
}

void oledDrawChar(uint8_t x, uint8_t y, char ch, bool inverted) {
  if ((uint8_t)ch < 32 || (uint8_t)ch > 126) {
    ch = '?';
  }
  const uint8_t *glyph = OLED_FONT_5X7[(uint8_t)ch - 32];
  for (uint8_t col = 0; col < 6; ++col) {
    uint8_t bits = (col < 5) ? glyph[col] : 0x00;
    for (uint8_t row = 0; row < 8; ++row) {
      bool on = (row < 7) && ((bits & (1 << row)) != 0);
      if (inverted) {
        on = !on;
      }
      oledSetPixel(x + col, y + row, on);
    }
  }
}

void oledDrawText(uint8_t x, uint8_t y, const String &text, uint8_t maxChars, bool inverted) {
  uint8_t cursorX = x;
  for (unsigned int i = 0; i < text.length() && i < maxChars; ++i) {
    if (cursorX + 5 >= OLED_WIDTH) {
      break;
    }
    uint8_t ch = (uint8_t)text.charAt(i);
    oledDrawChar(cursorX, y, (ch >= 32 && ch <= 126) ? (char)ch : '?', inverted);
    cursorX += 6;
  }
}

void oledDrawProgress(uint8_t x, uint8_t y, uint8_t w, uint8_t h, uint8_t filled) {
  oledFillRect(x, y, w, h, false);
  oledFillRect(x, y, w, 1, true);
  oledFillRect(x, y + h - 1, w, 1, true);
  oledFillRect(x, y, 1, h, true);
  oledFillRect(x + w - 1, y, 1, h, true);
  if (filled > 0 && w > 2 && h > 2) {
    uint8_t fillWidth = filled;
    if (fillWidth > w - 2) {
      fillWidth = w - 2;
    }
    oledFillRect(x + 1, y + 1, fillWidth, h - 2, true);
  }
}

void oledDrawLine(int x0, int y0, int x1, int y1, bool on) {
  int dx = abs(x1 - x0);
  int sx = x0 < x1 ? 1 : -1;
  int dy = -abs(y1 - y0);
  int sy = y0 < y1 ? 1 : -1;
  int err = dx + dy;

  while (true) {
    if (x0 >= 0 && x0 < OLED_WIDTH && y0 >= 0 && y0 < OLED_HEIGHT) {
      oledSetPixel((uint8_t)x0, (uint8_t)y0, on);
    }
    if (x0 == x1 && y0 == y1) {
      break;
    }
    int e2 = 2 * err;
    if (e2 >= dy) {
      err += dy;
      x0 += sx;
    }
    if (e2 <= dx) {
      err += dx;
      y0 += sy;
    }
  }
}

void oledDrawRoundedBox(uint8_t x, uint8_t y, uint8_t w, uint8_t h, bool on) {
  oledFillRect(x + 2, y, w - 4, h, on);
  oledFillRect(x, y + 2, w, h - 4, on);
  oledSetPixel(x + 1, y + 1, on);
  oledSetPixel(x + w - 2, y + 1, on);
  oledSetPixel(x + 1, y + h - 2, on);
  oledSetPixel(x + w - 2, y + h - 2, on);
}

void oledDrawEye(uint8_t cx, uint8_t cy, uint8_t w, uint8_t h, int8_t pupilOffset, bool closed, int8_t browTilt) {
  uint8_t x = cx - w / 2;
  uint8_t y = cy - h / 2;

  if (closed) {
    oledDrawLine(x + 2, cy, x + w - 3, cy, true);
    oledDrawLine(x + 4, cy + 1, x + w - 5, cy + 1, true);
  } else {
    oledDrawRoundedBox(x, y, w, h, true);
    int pupilX = (int)cx + pupilOffset - 3;
    int pupilY = (int)cy - 4;
    oledFillRect((uint8_t)pupilX, (uint8_t)pupilY, 6, 8, false);
    oledSetPixel((uint8_t)(pupilX + 1), (uint8_t)(pupilY + 1), true);
  }

  if (browTilt != 0) {
    if (browTilt > 0) {
      oledDrawLine(x + 1, y - 3, x + w - 2, y - 7, true);
    } else {
      oledDrawLine(x + 1, y - 7, x + w - 2, y - 3, true);
    }
  }
}

void oledDrawSoundWaves(uint8_t phase) {
  uint8_t y = 24 + (phase % 5);
  oledDrawLine(13, y, 18, y - 5, true);
  oledDrawLine(13, y, 18, y + 5, true);
  oledDrawLine(110, y - 5, 115, y, true);
  oledDrawLine(110, y + 5, 115, y, true);
  if ((phase & 0x01) == 0) {
    oledDrawLine(7, y, 14, y - 8, true);
    oledDrawLine(7, y, 14, y + 8, true);
    oledDrawLine(114, y - 8, 121, y, true);
    oledDrawLine(114, y + 8, 121, y, true);
  }
}

void oledDrawEnergyBars(uint8_t phase) {
  for (uint8_t i = 0; i < 7; ++i) {
    uint8_t bar = 2 + ((phase + i * 2) % 9);
    oledFillRect(36 + i * 8, 44 - bar, 4, bar, true);
  }
}

void oledDrawSmallFooter(uint32_t now) {
  String detail = compactForDisplay(uiEvent.detail, 10);
  if (detail.length() == 0) {
    detail = eventLabel(uiEvent.type);
  }
  oledDrawText(UI_TEXT_X, 52, detail, 10, false);

  String ms = String(uiEvent.ackSeen ? "ACK" : "T") + ":" + String(uiEvent.ackSeen ? uiEvent.ackMs : (now - uiEvent.startedMs));
  oledDrawText(82, 52, compactForDisplay(ms, 7), 7, false);
}

void renderAiFace(uint32_t now) {
  uint8_t phase = (now / UI_FRAME_INTERVAL_MS) & 0x0F;
  uint16_t age = now - uiEvent.startedMs;
  bool blink = (age % 4200) > 4050;
  int8_t pupil = 0;
  bool leftClosed = blink;
  bool rightClosed = blink;
  int8_t leftBrow = 0;
  int8_t rightBrow = 0;

  UiEventType faceType = uiEvent.type;
  if (now < ackFlashUntilMs) {
    faceType = ackFlashOk ? UI_EVENT_ACK : UI_EVENT_ERROR;
  }

  switch (faceType) {
    case UI_EVENT_LISTEN:
      pupil = ((phase % 4) - 1) * 2;
      leftClosed = false;
      rightClosed = false;
      oledDrawSoundWaves(phase);
      break;
    case UI_EVENT_THINK:
    case UI_EVENT_AI_BUSY:
      pupil = (phase < 8 ? phase : 15 - phase) - 4;
      leftBrow = 1;
      rightBrow = -1;
      oledDrawEnergyBars(phase);
      break;
    case UI_EVENT_ACTION:
    case UI_EVENT_TTS:
    case UI_EVENT_FAN_ON:
    case UI_EVENT_FAN_OFF:
    case UI_EVENT_BEEP:
    case UI_EVENT_MUSIC:
    case UI_EVENT_LOCK_ON:
    case UI_EVENT_LOCK_OFF:
    case UI_EVENT_RFID:
    case UI_EVENT_OLED:
      pupil = (phase & 0x01) ? 3 : -3;
      leftBrow = -1;
      rightBrow = 1;
      oledDrawEnergyBars(phase + 4);
      break;
    case UI_EVENT_ACK:
    case UI_EVENT_AI_IDLE:
      leftClosed = (phase & 0x04) != 0;
      rightClosed = false;
      oledDrawLine(88, 42, 94, 48, true);
      oledDrawLine(94, 48, 107, 35, true);
      break;
    case UI_EVENT_ERROR:
      leftBrow = -1;
      rightBrow = 1;
      oledDrawLine(28, 42, 100, 42, true);
      oledDrawLine(30, 44, 98, 44, true);
      break;
    default:
      pupil = ((phase % 8) < 4) ? -1 : 1;
      break;
  }

  oledDrawEye(45, 25, 29, 17, pupil, leftClosed, leftBrow);
  oledDrawEye(83, 25, 29, 17, pupil, rightClosed, rightBrow);
  oledDrawSmallFooter(now);
}

bool oledProbe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

uint8_t scanI2cBus() {
  uint8_t found = 0;
  usbConsole.println("[I2C] scan start");
  for (uint8_t address = 1; address < 0x78; ++address) {
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();
    if (error == 0) {
      found++;
      usbConsole.print("[I2C] found 0x");
      if (address < 0x10) {
        usbConsole.print("0");
      }
      usbConsole.println(address, HEX);
    } else if (error == 4) {
      usbConsole.print("[I2C] unknown error at 0x");
      if (address < 0x10) {
        usbConsole.print("0");
      }
      usbConsole.println(address, HEX);
    }
  }
  if (found == 0) {
    usbConsole.println("[I2C] no devices found");
  }
  usbConsole.print("[I2C] scan done count=");
  usbConsole.println(found);
  return found;
}

bool oledWriteCommand(uint8_t command) {
  Wire.beginTransmission(oledAddress);
  Wire.write(0x00);
  Wire.write(command);
  return Wire.endTransmission() == 0;
}

bool oledWriteDataChunk(uint16_t offset, uint8_t length) {
  Wire.beginTransmission(oledAddress);
  Wire.write(0x40);
  for (uint8_t i = 0; i < length; ++i) {
    Wire.write(oledBuffer[offset + i]);
  }
  return Wire.endTransmission() == 0;
}

bool initializeOled() {
  usbConsole.println("[OLED] probe 0x3D then 0x3C");
  if (oledProbe(OLED_ADDR_PRIMARY)) {
    oledAddress = OLED_ADDR_PRIMARY;
  } else if (oledProbe(OLED_ADDR_FALLBACK)) {
    oledAddress = OLED_ADDR_FALLBACK;
  } else {
    usbConsole.println("[OLED] SSD1306 not detected");
    return false;
  }

  delay(20);
  static const uint8_t initCommands[] = {
    0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
    0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8, 0xDA, 0x12,
    0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF
  };
  for (uint8_t i = 0; i < sizeof(initCommands); ++i) {
    if (!oledWriteCommand(initCommands[i])) {
      usbConsole.println("[OLED] SSD1306 init failed");
      return false;
    }
  }

  oledAvailable = true;
  clearOledBuffer();
  oledRenderPending = true;
  usbConsole.print("[OLED] SSD1306 addr=0x");
  usbConsole.println(oledAddress, HEX);
  return true;
}

bool handleI2cScanCommand() {
  uint8_t found = scanI2cBus();
  if (!oledAvailable && (oledProbe(OLED_ADDR_PRIMARY) || oledProbe(OLED_ADDR_FALLBACK))) {
    initializeOled();
    oledRenderPending = true;
  }
  uiEvent.detail = String("I2C FOUND ") + String(found);
  oledRenderPending = true;
  return found > 0;
}

void renderSystemOled() {
  if (!oledAvailable) {
    return;
  }

  clearOledBuffer();
  uint32_t now = millis();
  renderAiFace(now);
  oledFlushPage = 0;
  oledRenderPending = false;
  oledDirty = true;
}

void flushOledPage() {
  if (!oledAvailable || !oledDirty) {
    return;
  }
  uint32_t now = millis();
  if (now - lastOledFlushMs < OLED_FLUSH_INTERVAL_MS) {
    return;
  }
  lastOledFlushMs = now;

  if (!oledWriteCommand(0xB0 | oledFlushPage) ||
      !oledWriteCommand(0x00) ||
      !oledWriteCommand(0x10)) {
    oledAvailable = false;
    usbConsole.println("[OLED] flush command failed");
    return;
  }

  uint16_t pageOffset = (uint16_t)oledFlushPage * OLED_WIDTH;
  for (uint8_t col = 0; col < OLED_WIDTH; col += OLED_CHUNK_BYTES) {
    if (!oledWriteDataChunk(pageOffset + col, OLED_CHUNK_BYTES)) {
      oledAvailable = false;
      usbConsole.println("[OLED] flush data failed");
      return;
    }
  }

  oledFlushPage++;
  if (oledFlushPage >= OLED_PAGES) {
    oledFlushPage = 0;
    oledDirty = false;
  }
}

bool shouldShowEventRgb(uint32_t now) {
  if (!rgbSensorMode) {
    return true;
  }
  if (uiDemoActive) {
    return true;
  }

  switch (uiEvent.type) {
    case UI_EVENT_LISTEN:
    case UI_EVENT_THINK:
    case UI_EVENT_AI_BUSY:
    case UI_EVENT_AI_IDLE:
    case UI_EVENT_AI_OFF:
      return true;
    case UI_EVENT_ERROR:
      return now - uiEvent.startedMs < RGB_ERROR_HOLD_MS;
    default:
      return now - uiEvent.startedMs < RGB_EVENT_HOLD_MS;
  }
}

void writeSensorRgb(uint32_t now) {
  if (!latestTelemetryValid) {
    bool bluePulse = ((now / 500) % 2) == 0;
    writeRgbRaw(false, false, bluePulse);
    return;
  }

  uint16_t phase = now % 2000;
  if (strcmp(latestRgbStatus, "sensor_check") == 0) {
    bool doubleBlink = phase < 180 || (phase >= 320 && phase < 500);
    writeRgbRaw(doubleBlink, false, false);
  } else if (strcmp(latestRgbStatus, "too_close") == 0) {
    bool fastBlink = (now % 320) < 160;
    writeRgbRaw(fastBlink, false, false);
  } else if (strcmp(latestRgbStatus, "env_watch") == 0) {
    bool slowBlink = (now % 900) < 520;
    writeRgbRaw(slowBlink, slowBlink, false);
  } else if (strcmp(latestRgbStatus, "near_object") == 0) {
    bool bluePulse = phase < 760;
    writeRgbRaw(false, true, bluePulse);
  } else if (strcmp(latestRgbStatus, "tracking_high") == 0) {
    bool whiteTick = phase < 90;
    writeRgbRaw(whiteTick, true, true);
  } else {
    bool heartbeat = phase < 90;
    writeRgbRaw(false, true, heartbeat);
  }
}

void updateRgbAnimation() {
  uint32_t now = millis();
  if (now - lastRgbFrameMs < RGB_FRAME_INTERVAL_MS) {
    return;
  }
  lastRgbFrameMs = now;

  if (now < ackFlashUntilMs) {
    if (ackFlashOk) {
      writeRgbRaw(false, true, true);
    } else {
      writeRgbRaw(true, false, false);
    }
    return;
  }

  if (!shouldShowEventRgb(now)) {
    writeSensorRgb(now);
    return;
  }

  RgbState base = eventBaseRgb(uiEvent.type);
  uint16_t phase = (now - uiEvent.startedMs) % 720;
  bool pulse = phase < 360;

  switch (uiEvent.type) {
    case UI_EVENT_LISTEN:
      writeRgbRaw(false, false, true);
      break;
    case UI_EVENT_THINK:
      writeRgbRaw(true, pulse, false);
      break;
    case UI_EVENT_ACTION:
      writeRgbRaw(false, pulse, true);
      break;
    case UI_EVENT_ACK:
      writeRgbRaw(false, true, false);
      break;
    case UI_EVENT_AI_BUSY:
      writeRgbRaw(true, pulse, false);
      break;
    case UI_EVENT_TTS:
      writeRgbRaw(false, true, false);
      break;
    case UI_EVENT_BEEP:
      writeRgbRaw(pulse, false, true);
      break;
    case UI_EVENT_MUSIC:
      writeRgbRaw(pulse, false, true);
      break;
    case UI_EVENT_RFID:
      writeRgbRaw(false, true, pulse);
      break;
    case UI_EVENT_ERROR:
      writeRgbRaw(pulse, false, false);
      break;
    case UI_EVENT_AI_OFF:
      writeRgbRaw(false, false, false);
      break;
    default:
      writeRgbRaw(base.red && pulse, base.green, base.blue && pulse);
      break;
  }
}

void updateSystemUi() {
  uint32_t now = millis();
  updateRgbAnimation();
  if (oledAvailable && (oledRenderPending || now - lastUiFrameMs >= UI_FRAME_INTERVAL_MS)) {
    lastUiFrameMs = now;
    renderSystemOled();
  }
  flushOledPage();
}

bool appendCodePointAsUtf16Be(uint32_t codePoint, uint8_t *out, size_t capacity, size_t &outLen) {
  if (codePoint <= 0xFFFF) {
    if (codePoint >= 0xD800 && codePoint <= 0xDFFF) {
      return false;
    }
    if (outLen + 2 > capacity) {
      return false;
    }
    out[outLen++] = (uint8_t)((codePoint >> 8) & 0xFF);
    out[outLen++] = (uint8_t)(codePoint & 0xFF);
    return true;
  }

  if (codePoint > 0x10FFFF || outLen + 4 > capacity) {
    return false;
  }

  uint32_t value = codePoint - 0x10000;
  uint16_t high = 0xD800 | ((value >> 10) & 0x3FF);
  uint16_t low = 0xDC00 | (value & 0x3FF);
  out[outLen++] = (uint8_t)((high >> 8) & 0xFF);
  out[outLen++] = (uint8_t)(high & 0xFF);
  out[outLen++] = (uint8_t)((low >> 8) & 0xFF);
  out[outLen++] = (uint8_t)(low & 0xFF);
  return true;
}

bool decodeNextUtf8CodePoint(const uint8_t *bytes, size_t length, size_t &index, uint32_t &codePoint) {
  if (index >= length) {
    return false;
  }

  uint8_t first = bytes[index++];
  if ((first & 0x80) == 0) {
    codePoint = first;
    return true;
  }

  uint8_t needed = 0;
  uint32_t value = 0;
  if ((first & 0xE0) == 0xC0) {
    needed = 1;
    value = first & 0x1F;
    if (value == 0) {
      return false;
    }
  } else if ((first & 0xF0) == 0xE0) {
    needed = 2;
    value = first & 0x0F;
  } else if ((first & 0xF8) == 0xF0) {
    needed = 3;
    value = first & 0x07;
  } else {
    return false;
  }

  if (index + needed > length) {
    return false;
  }

  for (uint8_t i = 0; i < needed; ++i) {
    uint8_t next = bytes[index++];
    if ((next & 0xC0) != 0x80) {
      return false;
    }
    value = (value << 6) | (next & 0x3F);
  }

  if ((needed == 1 && value < 0x80) ||
      (needed == 2 && value < 0x800) ||
      (needed == 3 && value < 0x10000) ||
      value > 0x10FFFF ||
      (value >= 0xD800 && value <= 0xDFFF)) {
    return false;
  }

  codePoint = value;
  return true;
}

bool sendSyn6288Frame(const uint8_t *textBytes, size_t textLen, uint8_t textType) {
  if (textLen == 0 || textLen > SYN6288_MAX_TEXT_BYTES) {
    return false;
  }

  uint8_t frame[SYN6288_MAX_TEXT_BYTES + 6];
  size_t frameLen = textLen + 6;
  uint16_t dataLen = (uint16_t)(textLen + 3);
  frame[0] = SYN6288_FRAME_HEADER;
  frame[1] = (uint8_t)((dataLen >> 8) & 0xFF);
  frame[2] = (uint8_t)(dataLen & 0xFF);
  frame[3] = SYN6288_CMD_SYNTHESIS;
  frame[4] = textType;
  memcpy(&frame[5], textBytes, textLen);

  uint8_t checksum = 0;
  for (size_t i = 0; i < frameLen - 1; ++i) {
    checksum ^= frame[i];
  }
  frame[frameLen - 1] = checksum;

  espCommandSerial.write(frame, frameLen);
  espCommandSerial.flush();
  delay(10);
  return true;
}

bool speakUtf8Bytes(const uint8_t *bytes, size_t length) {
  uint8_t unicodeBytes[SYN6288_MAX_TEXT_BYTES];
  size_t unicodeLen = 0;
  size_t index = 0;

  while (index < length) {
    uint32_t codePoint = 0;
    if (!decodeNextUtf8CodePoint(bytes, length, index, codePoint)) {
      return false;
    }
    if (!appendCodePointAsUtf16Be(codePoint, unicodeBytes, sizeof(unicodeBytes), unicodeLen)) {
      return false;
    }
  }

  return sendSyn6288Frame(unicodeBytes, unicodeLen, SYN6288_TYPE_UNICODE);
}

bool speakText(const String &text) {
  return speakUtf8Bytes((const uint8_t *)text.c_str(), text.length());
}

int hexNibble(char ch) {
  if (ch >= '0' && ch <= '9') {
    return ch - '0';
  }
  if (ch >= 'a' && ch <= 'f') {
    return 10 + ch - 'a';
  }
  if (ch >= 'A' && ch <= 'F') {
    return 10 + ch - 'A';
  }
  return -1;
}

bool speakHexText(const String &hexText) {
  if (hexText.length() == 0 || (hexText.length() % 2) != 0) {
    return false;
  }

  uint8_t utf8Bytes[SYN6288_MAX_TEXT_BYTES];
  size_t utf8Len = 0;
  for (unsigned int i = 0; i < hexText.length(); i += 2) {
    int high = hexNibble(hexText.charAt(i));
    int low = hexNibble(hexText.charAt(i + 1));
    if (high < 0 || low < 0 || utf8Len >= sizeof(utf8Bytes)) {
      return false;
    }
    utf8Bytes[utf8Len++] = (uint8_t)((high << 4) | low);
  }
  return speakUtf8Bytes(utf8Bytes, utf8Len);
}

void logDemoStep(const UiDemoStep &step, uint32_t actionMs) {
  usbConsole.print("[DEMO] step=");
  usbConsole.print(eventLabel(step.type));
  usbConsole.print(" detail=");
  usbConsole.print(step.detail);
  usbConsole.print(" action_ms=");
  usbConsole.println(actionMs);
}

void runUiDemoStep(uint8_t index) {
  const UiDemoStep &step = UI_DEMO_STEPS[index];
  uint32_t startedMs = millis();
  beginUiEvent(step.type, step.detail, "ui_demo", false, startedMs);

  commandHadLight = false;
  commandLightResponseMs = 0;
  commandLightMeasureActive = true;
  RgbState cueRgb = eventBaseRgb(step.type);
  setRgb(cueRgb.red, cueRgb.green, cueRgb.blue);

  uint32_t actionStartedMs = millis();
  if (step.fanState >= 0) {
    if (step.fanState > 0) {
      driveFanOn(2);
    } else {
      stopDrv8833();
    }
  }
  if (step.beep) {
    playBeep(2400, 120);
  }
  if (step.ttsHex != nullptr) {
    speakHexText(String(step.ttsHex));
  }
  uint32_t actionMs = millis() - actionStartedMs;
  commandLightMeasureActive = false;

  finishUiEvent(0, actionMs, millis() - startedMs, true);
  logDemoStep(step, actionMs);
  uiDemoStepStartedMs = startedMs;
}

void finishUiDemo(const char *detail) {
  uiDemoActive = false;
  stopDrv8833();

  uint32_t startedMs = millis();
  beginUiEvent(UI_EVENT_AI_IDLE, detail, "ui_demo", false, startedMs);
  commandHadLight = false;
  commandLightResponseMs = 0;
  commandLightMeasureActive = true;
  setRgb(false, true, false);
  commandLightMeasureActive = false;
  finishUiEvent(0, 0, millis() - startedMs, true);
  usbConsole.print("[DEMO] ");
  usbConsole.println(detail);
}

void startUiDemo() {
  uiDemoActive = true;
  uiDemoIndex = 0;
  uiDemoStepStartedMs = 0;
  usbConsole.println("[DEMO] start");
}

void stopUiDemo() {
  finishUiDemo("DEMO STOP");
}

void handleConversationButtonPress() {
  uint32_t startedMs = millis();
  beginUiEvent(UI_EVENT_LISTEN, "VOICE BUTTON", "key2", false, startedMs);
  commandHadLight = false;
  commandLightResponseMs = 0;
  commandLightMeasureActive = true;
  setRgb(false, true, true);
  commandLightMeasureActive = false;
  finishUiEvent(0, 0, millis() - startedMs, true);

  usbConsole.print("[BUTTON] key2 pin=");
  usbConsole.println(PIN_DEMO_BUTTON);
  writeBack("BT:BTN:KEY2:SHORT");
}

void updateDemoButton() {
  bool pressed = digitalRead(PIN_DEMO_BUTTON) == LOW;
  uint32_t now = millis();

  if (pressed != demoButtonLastReading) {
    demoButtonLastReading = pressed;
    demoButtonLastChangeMs = now;
  }

  if (now - demoButtonLastChangeMs < BUTTON_DEBOUNCE_MS) {
    return;
  }

  if (pressed == demoButtonStablePressed) {
    return;
  }

  demoButtonStablePressed = pressed;
  if (demoButtonStablePressed) {
    handleConversationButtonPress();
  }
}

void updateUiDemo() {
  if (!uiDemoActive) {
    return;
  }

  uint32_t now = millis();
  if (uiDemoStepStartedMs == 0) {
    runUiDemoStep(uiDemoIndex);
    uiDemoIndex++;
    return;
  }

  uint8_t currentIndex = uiDemoIndex == 0 ? 0 : uiDemoIndex - 1;
  if (now - uiDemoStepStartedMs < UI_DEMO_STEPS[currentIndex].durationMs) {
    return;
  }

  if (uiDemoIndex >= UI_DEMO_STEP_COUNT) {
    finishUiDemo("DEMO DONE");
    return;
  }

  runUiDemoStep(uiDemoIndex);
  uiDemoIndex++;
}

void showOledText(const String &text) {
  usbConsole.print("[OLED] ");
  usbConsole.println(text);
  uiEvent.detail = String("OLED ") + compactForDisplay(text, 16);
  oledRenderPending = true;
}

bool initializeAht20() {
  Wire.beginTransmission(AHT20_I2C_ADDRESS);
  Wire.write(AHT20_CMD_INIT);
  Wire.write(0x08);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) {
    return false;
  }
  delay(10);
  return true;
}

bool readAht20(float &temperatureC, float &humidityPct) {
  if (!aht20Initialized) {
    aht20Initialized = initializeAht20();
  }
  if (!aht20Initialized) {
    return false;
  }

  Wire.beginTransmission(AHT20_I2C_ADDRESS);
  Wire.write(AHT20_CMD_MEASURE);
  Wire.write(0x33);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) {
    aht20Initialized = false;
    return false;
  }

  delay(85);
  uint8_t received = Wire.requestFrom(AHT20_I2C_ADDRESS, (uint8_t)7);
  if (received != 7) {
    aht20Initialized = false;
    return false;
  }

  uint8_t buffer[7];
  for (uint8_t i = 0; i < 7; ++i) {
    buffer[i] = Wire.read();
  }
  if ((buffer[0] & 0x80) != 0) {
    return false;
  }

  uint32_t rawHumidity = ((uint32_t)buffer[1] << 12) | ((uint32_t)buffer[2] << 4) | (buffer[3] >> 4);
  uint32_t rawTemperature = ((uint32_t)(buffer[3] & 0x0F) << 16) | ((uint32_t)buffer[4] << 8) | buffer[5];
  humidityPct = (rawHumidity * 100.0f) / 1048576.0f;
  temperatureC = ((rawTemperature * 200.0f) / 1048576.0f) - 50.0f;
  return true;
}

bool readDistanceCm(float &distanceCm) {
  if (!ultrasonicEnabled) {
    return false;
  }

  digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_ULTRASONIC_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_ULTRASONIC_TRIG, LOW);

  uint32_t durationUs = pulseIn(PIN_ULTRASONIC_ECHO, HIGH, ULTRASONIC_TIMEOUT_US);
  if (durationUs == 0) {
    return false;
  }

  distanceCm = durationUs / 58.0f;
  return true;
}

void stopMusic() {
  noTone(PIN_BUZZER);
  activeMelody = nullptr;
  activeMelodyLength = 0;
  activeMelodyIndex = 0;
  musicStepStartedMs = 0;
  musicStepTotalMs = 0;
  musicPlaying = false;
}

void startMelodyStep() {
  if (!musicPlaying || activeMelody == nullptr || activeMelodyIndex >= activeMelodyLength) {
    stopMusic();
    return;
  }

  const MelodyNote &note = activeMelody[activeMelodyIndex];
  if (note.frequency == 0) {
    noTone(PIN_BUZZER);
  } else {
    tone(PIN_BUZZER, note.frequency, note.durationMs);
  }
  musicStepStartedMs = millis();
  musicStepTotalMs = note.durationMs + MUSIC_NOTE_GAP_MS;
}

bool startMusic(const MelodyNote *melody, uint8_t length) {
  if (melody == nullptr || length == 0) {
    return false;
  }
  stopMusic();
  activeMelody = melody;
  activeMelodyLength = length;
  activeMelodyIndex = 0;
  musicPlaying = true;
  startMelodyStep();
  return true;
}

void updateMusicPlayer() {
  if (!musicPlaying) {
    return;
  }
  if (musicStepStartedMs == 0) {
    startMelodyStep();
    return;
  }
  if (millis() - musicStepStartedMs < musicStepTotalMs) {
    return;
  }
  activeMelodyIndex++;
  if (activeMelodyIndex >= activeMelodyLength) {
    stopMusic();
    return;
  }
  startMelodyStep();
}

bool startMusicByPreset(String preset) {
  preset.trim();
  String name = upperCopy(preset);
  if (name == "STOP" || name == "OFF") {
    stopMusic();
    return true;
  }
  if (name == "LIST?") {
    writeBack("BT:MUSIC:LIST:SUCCESS,ALERT,SCALE,STARTUP,BIRTHDAY");
    return true;
  }
  if (name.length() == 0 || name == "SUCCESS" || name == "OK") {
    return startMusic(MELODY_SUCCESS, (uint8_t)(sizeof(MELODY_SUCCESS) / sizeof(MELODY_SUCCESS[0])));
  }
  if (name == "ALERT" || name == "WARN" || name == "WARNING") {
    return startMusic(MELODY_ALERT, (uint8_t)(sizeof(MELODY_ALERT) / sizeof(MELODY_ALERT[0])));
  }
  if (name == "SCALE") {
    return startMusic(MELODY_SCALE, (uint8_t)(sizeof(MELODY_SCALE) / sizeof(MELODY_SCALE[0])));
  }
  if (name == "STARTUP" || name == "BOOT") {
    return startMusic(MELODY_STARTUP, (uint8_t)(sizeof(MELODY_STARTUP) / sizeof(MELODY_STARTUP[0])));
  }
  if (name == "BIRTHDAY" || name == "HAPPY") {
    return startMusic(MELODY_BIRTHDAY, (uint8_t)(sizeof(MELODY_BIRTHDAY) / sizeof(MELODY_BIRTHDAY[0])));
  }
  return false;
}

bool playBeep(uint16_t frequency, uint16_t durationMs) {
  stopMusic();
  tone(PIN_BUZZER, frequency, durationMs);
  return true;
}

void stopDrv8833() {
  if (!drv8833Connected) {
    return;
  }
  analogWrite(PIN_DRV8833_IN1, 0);
  analogWrite(PIN_DRV8833_IN2, 0);
  digitalWrite(PIN_DRV8833_IN1, LOW);
  digitalWrite(PIN_DRV8833_IN2, LOW);
}

uint8_t drv8833FanDutyForLevel(uint8_t level) {
  if (level <= 1) {
    return DRV8833_FAN_LEVEL1_DUTY;
  }
  if (level == 2) {
    return DRV8833_FAN_LEVEL2_DUTY;
  }
  return DRV8833_FAN_LEVEL3_DUTY;
}

uint8_t fanLevelFromCommand(const String &command) {
  int lastColon = command.lastIndexOf(':');
  if (lastColon < 0 || lastColon + 1 >= (int)command.length()) {
    return 2;
  }
  int level = command.substring(lastColon + 1).toInt();
  if (level < 1) {
    return 1;
  }
  if (level > 3) {
    return 3;
  }
  return (uint8_t)level;
}

bool driveFanOn(uint8_t level) {
  if (!drv8833Connected) {
    return false;
  }
  uint8_t duty = drv8833FanDutyForLevel(level);
  // Current fan wiring spins the useful direction with IN2 PWM and IN1 LOW.
  analogWrite(PIN_DRV8833_IN1, 0);
  digitalWrite(PIN_DRV8833_IN1, LOW);
  analogWrite(PIN_DRV8833_IN2, duty);
  return true;
}

uint8_t readEncoderState() {
  uint8_t state = 0;
  if (digitalRead(PIN_ENCODER_A) == HIGH) {
    state |= 0x01;
  }
  if (digitalRead(PIN_ENCODER_B) == HIGH) {
    state |= 0x02;
  }
  return state;
}

void updateEncoder() {
  static const int8_t TRANSITIONS[16] = {
    0, -1, 1, 0,
    1, 0, 0, -1,
    -1, 0, 0, 1,
    0, 1, -1, 0
  };
  uint8_t state = readEncoderState();
  uint8_t index = (encoderLastState << 2) | state;
  int8_t delta = TRANSITIONS[index];
  if (delta != 0) {
    encoderPosition += delta;
    encoderDeltaSinceTelemetry += delta;
  }
  encoderLastState = state;
}

bool parseServoAngle(const String &value, uint8_t &angle) {
  String text = value;
  text.trim();
  if (text.length() == 0) {
    return false;
  }
  for (uint16_t i = 0; i < text.length(); ++i) {
    if (!isDigit(text.charAt(i))) {
      return false;
    }
  }
  long parsed = text.toInt();
  if (parsed < 0 || parsed > 180) {
    return false;
  }
  angle = (uint8_t)parsed;
  return true;
}

void setServoAngle(uint8_t angle) {
  servoPulseWidthUs = SERVO_MIN_PULSE_US +
                      ((uint32_t)(SERVO_MAX_PULSE_US - SERVO_MIN_PULSE_US) * angle) / 180;
  lastServoCommandMs = millis();
  nextServoPulseUs = micros();
  servoPulseHigh = false;
  servoActive = true;
  digitalWrite(PIN_SERVO, LOW);
}

void updateServoPulse() {
  if (!servoActive) {
    return;
  }

  uint32_t nowUs = micros();
  if (servoPulseHigh) {
    if ((uint32_t)(nowUs - servoPulseStartedUs) >= servoPulseWidthUs) {
      digitalWrite(PIN_SERVO, LOW);
      servoPulseHigh = false;
      nextServoPulseUs = servoPulseStartedUs + SERVO_PULSE_PERIOD_US;
    }
  } else if ((int32_t)(nowUs - nextServoPulseUs) >= 0) {
    digitalWrite(PIN_SERVO, HIGH);
    servoPulseStartedUs = nowUs;
    servoPulseHigh = true;
  }

  if (!servoPulseHigh && millis() - lastServoCommandMs > SERVO_HOLD_MS) {
    servoActive = false;
    digitalWrite(PIN_SERVO, LOW);
  }
}

String buildTelemetryJson() {
  int potRaw = analogRead(PIN_POTENTIOMETER);
  int ntcRaw = analogRead(PIN_NTC);
  float temperatureC = 0.0f;
  float humidityPct = 0.0f;
  float distanceCm = 0.0f;
  long encoderDelta = encoderDeltaSinceTelemetry;
  encoderDeltaSinceTelemetry = 0;
  long encoderPositionSnapshot = encoderPosition;
  bool encoderButtonPressed = digitalRead(PIN_ENCODER_BUTTON) == LOW;
  bool trackingSignal = digitalRead(PIN_TRACKING_SENSOR) == HIGH;
  bool ahtOk = readAht20(temperatureC, humidityPct);
  bool distanceOk = readDistanceCm(distanceCm);

  latestTelemetryValid = true;
  latestPotRaw = potRaw;
  latestPotPct = analogPercent(potRaw);
  latestNtcRaw = ntcRaw;
  latestNtcPct = analogPercent(ntcRaw);
  latestTrackingSignal = trackingSignal;
  latestAhtOk = ahtOk;
  latestTemperatureC = temperatureC;
  latestHumidityPct = humidityPct;
  latestDistanceOk = distanceOk;
  latestDistanceEnabled = ultrasonicEnabled;
  latestDistanceCm = distanceCm;
  latestEncoderDelta = encoderDelta;
  latestEncoderPosition = encoderPositionSnapshot;
  latestEncoderButtonPressed = encoderButtonPressed;
  latestDistanceZone = distanceZone(ultrasonicEnabled, distanceOk, distanceCm);
  latestEnvState = environmentState(ahtOk, temperatureC, humidityPct);
  latestInteractionHint = interactionHint(trackingSignal, encoderButtonPressed, encoderDelta,
                                          distanceOk, distanceCm);
  updateLatestRgbStatus();

  String json = "BT:{";
  json += "\"pot_raw\":";
  json += String(potRaw);
  json += ",\"pot_pct\":";
  json += String(latestPotPct);
  json += ",\"ntc_raw\":";
  json += String(ntcRaw);
  json += ",\"ntc_pct\":";
  json += String(latestNtcPct);
  json += ",\"tracking_signal\":";
  json += trackingSignal ? "true" : "false";
  json += ",\"aht20_ok\":";
  json += ahtOk ? "true" : "false";
  if (ahtOk) {
    json += ",\"temperature_c\":";
    json += String(temperatureC, 1);
    json += ",\"humidity_pct\":";
    json += String(humidityPct, 1);
  }
  json += ",\"distance_ok\":";
  json += distanceOk ? "true" : "false";
  json += ",\"distance_enabled\":";
  json += ultrasonicEnabled ? "true" : "false";
  if (distanceOk) {
    json += ",\"distance_cm\":";
    json += String(distanceCm, 1);
  }
  json += ",\"distance_zone\":\"";
  json += latestDistanceZone;
  json += "\"";
  json += ",\"env_state\":\"";
  json += latestEnvState;
  json += "\"";
  json += ",\"interaction_hint\":\"";
  json += latestInteractionHint;
  json += "\"";
  json += ",\"rgb_mode\":\"";
  json += rgbSensorMode ? "sensor" : "event";
  json += "\"";
  json += ",\"rgb_status\":\"";
  json += latestRgbStatus;
  json += "\"";
  json += ",\"rgb_reason\":\"";
  json += latestRgbReason;
  json += "\"";
  json += ",\"encoder_delta\":";
  json += String(encoderDelta);
  json += ",\"encoder_position\":";
  json += String(encoderPositionSnapshot);
  json += ",\"encoder_button\":";
  json += encoderButtonPressed ? "true" : "false";
  json += "}";
  return json;
}

void sendTelemetrySnapshot() {
  writeBack(buildTelemetryJson());
}

bool canSendPeriodicTelemetry() {
  if (espLine.length() > 0) {
    return false;
  }
  if (lastEspRxActivityMs == 0) {
    return true;
  }
  return millis() - lastEspRxActivityMs >= TELEMETRY_ESP_QUIET_MS;
}

bool executeNetCommand(const String &command) {
  if (command == "NET:UI:LISTEN" ||
      command == "NET:UI:THINK" ||
      command == "NET:UI:ACTION" ||
      command == "NET:UI:ACK" ||
      command == "NET:UI:OUTPUT" ||
      command == "NET:UI:IDLE" ||
      command == "NET:UI:ERROR") {
    return true;
  }

  if (command == "NET:UI:DEMO") {
    startUiDemo();
    return true;
  }

  if (command == "NET:UI:DEMO:STOP") {
    stopUiDemo();
    return true;
  }

  if (command == "NET:UI:STATUS?") {
    String line = "BT:UI:";
    line += "demo=";
    line += uiDemoActive ? "ON" : "OFF";
    line += ",oled=";
    line += oledAvailable ? "OK" : "MISS";
    line += ",addr=0x";
    line += String(oledAddress, HEX);
    writeBack(line);
    return true;
  }

  if (command == "NET:UART?") {
    writeBack("BT:PONG:" + String(millis()));
    return true;
  }

  if (command == "NET:I2C?") {
    return handleI2cScanCommand();
  }

  if (command == "NET:TELEMETRY?") {
    sendTelemetrySnapshot();
    return true;
  }

  if (command == "NET:RGB:STATUS?") {
    writeBack(buildRgbStatusLine());
    return true;
  }

  if (command == "NET:RGB:LEGEND?") {
    writeBack("BT:RGB:LEGEND:GREEN=ready,CYAN=object_or_tracking,YELLOW=env_watch,RED=sensor_or_too_close,BLUE=waiting");
    return true;
  }

  if (command == "NET:RGB:MODE:SENSOR") {
    rgbSensorMode = true;
    updateLatestRgbStatus();
    writeBack("BT:RGB:MODE:SENSOR");
    return true;
  }

  if (command == "NET:RGB:MODE:EVENT") {
    rgbSensorMode = false;
    writeBack("BT:RGB:MODE:EVENT");
    return true;
  }

  if (command == "NET:ULTRASONIC:ON") {
    ultrasonicEnabled = true;
    writeBack("BT:ULTRASONIC:ON");
    return true;
  }

  if (command == "NET:ULTRASONIC:OFF") {
    ultrasonicEnabled = false;
    digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
    writeBack("BT:ULTRASONIC:OFF");
    return true;
  }

  if (command.startsWith("NET:TTS:")) {
    return speakText(command.substring(strlen("NET:TTS:")));
  }

  if (command.startsWith("NET:TTSHEX:")) {
    return speakHexText(command.substring(strlen("NET:TTSHEX:")));
  }

  if (command.startsWith("NET:OLED:")) {
    if (!oledAvailable) {
      initializeOled();
    }
    showOledText(command.substring(strlen("NET:OLED:")));
    return true;
  }

  if (command.startsWith("NET:RFID:")) {
    uiEvent.detail = String("RFID ") + compactForDisplay(command.substring(strlen("NET:RFID:")), 15);
    oledRenderPending = true;
    return true;
  }

  if (command == "NET:BEEP") {
    playBeep(2200, 120);
    return true;
  }

  if (command.startsWith("NET:MUSIC:")) {
    return startMusicByPreset(command.substring(strlen("NET:MUSIC:")));
  }

  if (command == "NET:MOTOR:OFF") {
    stopDrv8833();
    return true;
  }

  if (command.startsWith("NET:FAN:ON")) {
    return driveFanOn(fanLevelFromCommand(command));
  }

  if (command == "NET:FAN:OFF") {
    stopDrv8833();
    return true;
  }

  if (command == "NET:LOCK:ON") {
    setRgb(true, false, false);
    return true;
  }

  if (command == "NET:LOCK:OFF") {
    setRgb(false, true, false);
    return true;
  }

  if (command == "NET:AI:BUSY") {
    setRgb(true, true, false);
    return true;
  }

  if (command == "NET:AI:IDLE") {
    setRgb(false, true, false);
    return true;
  }

  if (command == "NET:AI:OFF") {
    setRgb(false, false, false);
    return true;
  }

  if (command.startsWith("NET:SERVO:")) {
    uint8_t angle = 0;
    if (!parseServoAngle(command.substring(strlen("NET:SERVO:")), angle)) {
      usbConsole.print("[SERVO] invalid angle ");
      usbConsole.println(command.substring(strlen("NET:SERVO:")));
      return false;
    }
    setServoAngle(angle);
    usbConsole.print("[SERVO] ");
    usbConsole.println(angle);
    return true;
  }

  usbConsole.print("[ERR] unsupported command: ");
  usbConsole.println(command);
  return false;
}

void handleSingleCommandLine(String line, const char *source) {
  uint32_t receivedMs = millis();
  if (strcmp(source, "ESP") == 0) {
    lastEspRxActivityMs = receivedMs;
  }
  line.trim();
  if (line.length() == 0) {
    return;
  }

  usbConsole.print("[");
  usbConsole.print(source);
  usbConsole.print("] ");
  usbConsole.println(line);

  uint32_t parseStartedMs = millis();
  ParsedCommand parsed = parseLine(line);
  uint32_t parseMs = millis() - parseStartedMs;
  if (parsed.command.length() == 0) {
    commandLightMeasureActive = false;
    commandHadLight = false;
    commandLightResponseMs = 0;
    beginUiEvent(UI_EVENT_ERROR, "PARSE ERR", parsed.actionId, parsed.wrapped, receivedMs);
    sendAck(parsed, false);
    finishUiEvent(parseMs, 0, millis() - receivedMs, false);
    logEventTiming(source, parsed, false);
    return;
  }

  beginUiEvent(classifyNetCommand(parsed.command, parsed.actionId), commandPreview(parsed.command),
               parsed.actionId, parsed.wrapped, receivedMs);
  commandHadLight = false;
  commandLightResponseMs = 0;
  commandLightMeasureActive = true;
  RgbState cueRgb = eventBaseRgb(uiEvent.type);
  setRgb(cueRgb.red, cueRgb.green, cueRgb.blue);
  uint32_t actionStartedMs = millis();
  bool ok = executeNetCommand(parsed.command);
  uint32_t actionMs = millis() - actionStartedMs;
  commandLightMeasureActive = false;
  sendAck(parsed, ok);
  finishUiEvent(parseMs, actionMs, millis() - receivedMs, ok);
  logEventTiming(source, parsed, ok);
}

void handleLine(String line, const char *source) {
  line.trim();
  if (line.length() == 0) {
    return;
  }

  int firstStart = findKnownNetCommandStart(line, 0);
  if (firstStart > 0) {
    usbConsole.print("[WARN] dropping serial prefix bytes=");
    usbConsole.println(firstStart);
    line = line.substring(firstStart);
  }

  int nextStart = findKnownNetCommandStart(line, 1);
  if (nextStart < 0) {
    handleSingleCommandLine(line, source);
    return;
  }

  usbConsole.println("[WARN] split concatenated NET commands");
  int currentStart = 0;
  while (currentStart >= 0 && currentStart < (int)line.length()) {
    int followingStart = findKnownNetCommandStart(line, currentStart + 1);
    String segment = followingStart >= 0 ? line.substring(currentStart, followingStart) : line.substring(currentStart);
    segment.trim();
    if (segment.length() > 0) {
      handleSingleCommandLine(segment, source);
    }
    if (followingStart < 0) {
      break;
    }
    currentStart = followingStart;
  }
}

void pollSerial(Stream &stream, String &buffer, const char *source) {
  while (stream.available()) {
    char ch = (char)stream.read();
    if (strcmp(source, "ESP") == 0) {
      lastEspRxActivityMs = millis();
    }
    if (ch == '\n' || ch == '\r') {
      if (buffer.length() == 0 && strcmp(source, "ESP") == 0) {
        espEmptyDelimiterCount++;
        if (espEmptyDelimiterCount <= 5 || (espEmptyDelimiterCount % 20) == 0) {
          usbConsole.print("[ESP] empty delimiter count=");
          usbConsole.println(espEmptyDelimiterCount);
        }
        continue;
      }
      handleLine(buffer, source);
      buffer = "";
    } else {
      buffer += ch;
    }
  }
}

void setup() {
  usbConsole.begin(115200);
  espCommandSerial.begin(ESP_IN_BAUD);
  espAckSerial.begin(ESP_ACK_BAUD);
  delay(20);
  while (espCommandSerial.available()) {
    espCommandSerial.read();
  }

  if (drv8833Connected) {
    pinMode(PIN_DRV8833_IN1, OUTPUT);
    pinMode(PIN_DRV8833_IN2, OUTPUT);
  }
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_RGB_BLUE, OUTPUT);
  pinMode(PIN_RGB_GREEN, OUTPUT);
  pinMode(PIN_RGB_RED, OUTPUT);
  pinMode(PIN_SERVO, OUTPUT);
  pinMode(PIN_ULTRASONIC_TRIG, OUTPUT);
  pinMode(PIN_ULTRASONIC_ECHO, INPUT_PULLDOWN);
  pinMode(PIN_NTC, INPUT_ANALOG);
  pinMode(PIN_POTENTIOMETER, INPUT_ANALOG);
  pinMode(PIN_TRACKING_SENSOR, INPUT);
  pinMode(PIN_ENCODER_A, INPUT_PULLUP);
  pinMode(PIN_ENCODER_B, INPUT_PULLUP);
  pinMode(PIN_ENCODER_BUTTON, INPUT_PULLUP);
  pinMode(PIN_DEMO_BUTTON, INPUT_PULLUP);

  Wire.begin();
  Wire.setClock(100000);
  aht20Initialized = initializeAht20();

  setRgb(false, false, true);
  stopDrv8833();
  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_SERVO, LOW);
  digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
  encoderLastState = readEncoderState();
  beginUiEvent(UI_EVENT_BOOT, "STM32 EXECUTOR", "", false, millis());
  initializeOled();
  renderSystemOled();
  writeBack("BT:BOOT:STM32_EXECUTOR");
}

void loop() {
  pollSerial(usbConsole, usbLine, "USB");
  pollSerial(espCommandSerial, espLine, "ESP");
  updateEncoder();
  updateServoPulse();
  updateMusicPlayer();
  updateDemoButton();
  updateUiDemo();
  updateSystemUi();
  if (millis() - lastTelemetryMs >= TELEMETRY_INTERVAL_MS && canSendPeriodicTelemetry()) {
    lastTelemetryMs = millis();
    sendTelemetrySnapshot();
  }
}
