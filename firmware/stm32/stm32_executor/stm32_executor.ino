#include <Arduino.h>
#include <SoftwareSerial.h>
#include <Wire.h>
#include "oled_font5x7.h"
#include "oled_cjk16.h"

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
#ifndef INFO_BUTTON_PIN
static const int PIN_INFO_BUTTON = PB12;  // KEY1: OLED information screen switch.
#else
static const int PIN_INFO_BUTTON = INFO_BUTTON_PIN;
#endif

#ifndef ULTRASONIC_ENABLED_BY_DEFAULT
#define ULTRASONIC_ENABLED_BY_DEFAULT 1
#endif

#ifndef DRV8833_CONNECTED_BY_DEFAULT
#define DRV8833_CONNECTED_BY_DEFAULT 1
#endif

static const uint32_t TELEMETRY_INTERVAL_MS = 4000;
static const uint32_t UI_FRAME_INTERVAL_MS = 80;
static const uint32_t RGB_FRAME_INTERVAL_MS = 80;
static const uint32_t OLED_FLUSH_INTERVAL_MS = 4;
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
static const uint32_t UI_BOOT_HOLD_MS = 1800;
static const uint32_t UI_TRANSIENT_HOLD_MS = 2200;
static const uint32_t UI_SPEAK_HOLD_MS = 7000;
static const uint32_t RGB_ACK_FLASH_MS = 520;
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
static const uint32_t KEY2_HOLD_START_MS = 600;
static const uint32_t KEY1_LONG_PRESS_MS = 700;
static const uint32_t SCREEN_OVERLAY_MS = 1400;
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
static const uint8_t SYN6288_CMD_STOP = 0x02;
static const uint8_t SYN6288_TYPE_UNICODE = 0x03;
static const size_t SYN6288_MAX_TEXT_BYTES = 200;
static const uint8_t SYN6288_MAX_VOLUME = 16;
static const uint8_t VOLUME_DEFAULT_PERCENT = 60;
static const uint8_t VOLUME_MAX_PERCENT = 100;
static const uint8_t VOLUME_STEP_PERCENT = 10;
static const int8_t ENCODER_STEPS_PER_DETENT = 4;
static const uint32_t VOLUME_ANNOUNCE_DELAY_MS = 450;

uint8_t speechVolume = 10;
uint8_t speechVolumePercent = VOLUME_DEFAULT_PERCENT;
int8_t encoderVolumeTicks = 0;
bool volumeAnnouncementPending = false;
uint32_t lastVolumeChangeMs = 0;

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

enum UiMachineState : uint8_t {
  UI_STATE_BOOT,
  UI_STATE_LOCKED,
  UI_STATE_READY,
  UI_STATE_LISTENING,
  UI_STATE_PROCESSING,
  UI_STATE_SPEAKING,
  UI_STATE_EXECUTING,
  UI_STATE_ERROR
};

enum InfoScreen : uint8_t {
  INFO_SCREEN_MAIN,
  INFO_SCREEN_USER,
  INFO_SCREEN_LINK,
  INFO_SCREEN_SENSORS,
  INFO_SCREEN_ACTUATORS,
  INFO_SCREEN_COUNT
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
UiMachineState uiMachineState = UI_STATE_BOOT;
uint32_t uiMachineStateStartedMs = 0;
uint8_t oledAddress = OLED_ADDR_PRIMARY;
uint8_t oledBuffer[OLED_WIDTH * OLED_PAGES];
uint8_t oledFlushPage = 0;
bool oledAvailable = false;
bool oledDirty = false;
bool oledRenderPending = false;
uint32_t lastUiFrameMs = 0;
uint32_t lastRgbFrameMs = 0;
uint32_t lastOledFlushMs = 0;
uint32_t oledFpsWindowMs = 0;
uint16_t oledFrameCounter = 0;
uint8_t oledFps = 0;
InfoScreen infoScreen = INFO_SCREEN_MAIN;
uint32_t infoOverlayUntilMs = 0;
uint32_t ackFlashUntilMs = 0;
bool ackFlashOk = true;
bool commandLightMeasureActive = false;
bool commandHadLight = false;
uint32_t commandLightResponseMs = 0;
bool uiDemoActive = false;
uint8_t uiDemoIndex = 0;
uint32_t uiDemoStepStartedMs = 0;
bool key2LastReading = false;
bool key2StablePressed = false;
bool key2HoldStartSent = false;
uint32_t key2LastChangeMs = 0;
uint32_t key2PressedMs = 0;
bool infoButtonLastReading = false;
bool infoButtonStablePressed = false;
bool infoButtonLongSent = false;
uint32_t infoButtonLastChangeMs = 0;
uint32_t infoButtonPressedMs = 0;
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
String currentUserId = "-";
String currentCardUid = "-";
String currentUserMode = "NONE";
String lastButtonEvent = "-";
uint32_t lastButtonEventMs = 0;
uint32_t volumeOverlayUntilMs = 0;
uint8_t currentFanLevel = 0;
bool currentLockOn = false;
bool ttsInterrupted = false;

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

RgbState uiMachineBaseRgb() {
  switch (uiMachineState) {
    case UI_STATE_BOOT:
      return rgbState(false, false, true);
    case UI_STATE_LISTENING:
      return rgbState(false, true, true);
    case UI_STATE_PROCESSING:
    case UI_STATE_SPEAKING:
    case UI_STATE_EXECUTING:
      return rgbState(true, true, false);
    case UI_STATE_READY:
      return rgbState(false, true, false);
    case UI_STATE_LOCKED:
    case UI_STATE_ERROR:
      return rgbState(true, false, false);
  }
  return rgbState(true, false, false);
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
  if (command == "NET:UI:DEMO") {
    return UI_EVENT_DEMO;
  }
  if (command == "NET:UI:DEMO:STOP" || command == "NET:UI:STATUS?") {
    return UI_EVENT_TELEMETRY;
  }
  if (command.startsWith("NET:UI:USER:")) {
    return UI_EVENT_RFID;
  }
  if (command.startsWith("NET:UI:")) {
    return UI_EVENT_ERROR;
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
  if (command == "NET:TTS:STOP" || command == "NET:AUDIO:STOP" ||
      command.startsWith("NET:TTS:") || command.startsWith("NET:TTSHEX:") ||
      command.startsWith("NET:VOLUME:")) {
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
  if (command == "NET:TTS:STOP" || command == "NET:AUDIO:STOP") {
    return "TTS STOP";
  }
  if (command.startsWith("NET:UI:USER:")) {
    return String("USER ") + compactForDisplay(command.substring(strlen("NET:UI:USER:")), 14);
  }
  if (command.startsWith("NET:VOLUME:")) {
    return String("VOLUME ") + compactForDisplay(command.substring(strlen("NET:VOLUME:")), 4);
  }
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
    "NET:AUDIO:",
    "NET:VOLUME:",
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

void enterUiMachineState(UiMachineState state, uint32_t startedMs) {
  uiMachineState = state;
  uiMachineStateStartedMs = startedMs;
  oledRenderPending = true;
}

void transitionUiMachineForEvent(UiEventType type, uint32_t startedMs) {
  if (uiMachineState == UI_STATE_LOCKED &&
      type != UI_EVENT_LOCK_OFF && type != UI_EVENT_ERROR && type != UI_EVENT_AI_OFF) {
    return;
  }

  switch (type) {
    case UI_EVENT_BOOT:
      enterUiMachineState(UI_STATE_BOOT, startedMs);
      break;
    case UI_EVENT_LOCK_ON:
      enterUiMachineState(UI_STATE_LOCKED, startedMs);
      break;
    case UI_EVENT_LOCK_OFF:
    case UI_EVENT_ACK:
    case UI_EVENT_AI_IDLE:
      enterUiMachineState(UI_STATE_READY, startedMs);
      break;
    case UI_EVENT_LISTEN:
      enterUiMachineState(UI_STATE_LISTENING, startedMs);
      break;
    case UI_EVENT_THINK:
    case UI_EVENT_AI_BUSY:
      enterUiMachineState(UI_STATE_PROCESSING, startedMs);
      break;
    case UI_EVENT_TTS:
      enterUiMachineState(UI_STATE_SPEAKING, startedMs);
      break;
    case UI_EVENT_ACTION:
    case UI_EVENT_FAN_ON:
    case UI_EVENT_FAN_OFF:
    case UI_EVENT_BEEP:
    case UI_EVENT_MUSIC:
    case UI_EVENT_SERVO:
    case UI_EVENT_DEMO:
      enterUiMachineState(UI_STATE_EXECUTING, startedMs);
      break;
    case UI_EVENT_ERROR:
    case UI_EVENT_AI_OFF:
      enterUiMachineState(UI_STATE_ERROR, startedMs);
      break;
    default:
      break;
  }
}

void updateUiMachineState(uint32_t now) {
  uint32_t age = now - uiMachineStateStartedMs;
  if ((uiMachineState == UI_STATE_BOOT && age >= UI_BOOT_HOLD_MS) ||
      (uiMachineState == UI_STATE_EXECUTING && age >= UI_TRANSIENT_HOLD_MS) ||
      (uiMachineState == UI_STATE_SPEAKING && age >= UI_SPEAK_HOLD_MS)) {
    enterUiMachineState(UI_STATE_READY, now);
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
  transitionUiMachineForEvent(type, startedMs);
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
  ackFlashUntilMs = ok ? 0 : millis() + RGB_ACK_FLASH_MS;
  if (!ok) {
    enterUiMachineState(UI_STATE_ERROR, millis());
  }
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

void oledDrawTextCentered(const String &text, uint8_t y, uint8_t maxChars) {
  uint8_t count = text.length() > maxChars ? maxChars : text.length();
  uint8_t width = count * 6;
  oledDrawText((OLED_WIDTH - width) / 2, y, text, maxChars, false);
}

const OledCjkGlyph *oledFindCjkGlyph(uint16_t codepoint) {
  for (uint8_t i = 0; i < OLED_CJK16_GLYPH_COUNT; ++i) {
    if (OLED_CJK16_GLYPHS[i].codepoint == codepoint) {
      return &OLED_CJK16_GLYPHS[i];
    }
  }
  return nullptr;
}

bool oledNextUtf8Codepoint(const char *text, uint16_t &offset, uint16_t &codepoint) {
  uint8_t first = (uint8_t)text[offset];
  if (first == 0) {
    return false;
  }
  offset++;
  if (first < 0x80) {
    codepoint = first;
    return true;
  }
  uint8_t second = (uint8_t)text[offset];
  uint8_t third = (uint8_t)text[offset + 1];
  if ((first & 0xF0) == 0xE0 && (second & 0xC0) == 0x80 && (third & 0xC0) == 0x80) {
    offset += 2;
    codepoint = ((uint16_t)(first & 0x0F) << 12) | ((uint16_t)(second & 0x3F) << 6) | (third & 0x3F);
    return true;
  }
  codepoint = '?';
  return true;
}

void oledDrawCjkGlyph(uint8_t x, uint8_t y, uint16_t codepoint) {
  const OledCjkGlyph *glyph = oledFindCjkGlyph(codepoint);
  if (glyph == nullptr) {
    oledFillRect(x + 2, y + 2, 12, 12, true);
    oledFillRect(x + 4, y + 4, 8, 8, false);
    return;
  }
  for (uint8_t row = 0; row < 16; ++row) {
    uint16_t bits = ((uint16_t)glyph->bitmap[row * 2] << 8) | glyph->bitmap[row * 2 + 1];
    for (uint8_t col = 0; col < 16; ++col) {
      if ((bits & ((uint16_t)1 << (15 - col))) != 0) {
        oledSetPixel(x + col, y + row, true);
      }
    }
  }
}

void oledDrawCjkTextCentered(const char *text, uint8_t y) {
  uint16_t offset = 0;
  uint16_t codepoint = 0;
  uint8_t count = 0;
  while (oledNextUtf8Codepoint(text, offset, codepoint)) {
    count++;
  }
  uint8_t width = count > 8 ? OLED_WIDTH : count * 16;
  uint8_t x = (OLED_WIDTH - width) / 2;
  offset = 0;
  while (oledNextUtf8Codepoint(text, offset, codepoint) && x + 15 < OLED_WIDTH) {
    oledDrawCjkGlyph(x, y, codepoint);
    x += 16;
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

const char *uiMachineCode(UiMachineState state) {
  switch (state) {
    case UI_STATE_BOOT: return "S0 BOOT";
    case UI_STATE_LOCKED: return "S1 LOCKED";
    case UI_STATE_READY: return "S2 READY";
    case UI_STATE_LISTENING: return "S3 LISTEN";
    case UI_STATE_PROCESSING: return "S4 PROCESS";
    case UI_STATE_SPEAKING: return "S5 SPEAK";
    case UI_STATE_EXECUTING: return "S6 EXEC";
    case UI_STATE_ERROR: return "S7 ERROR";
  }
  return "S7 ERROR";
}

const char *uiMachineTitle(UiMachineState state) {
  switch (state) {
    case UI_STATE_BOOT: return "正在启动";
    case UI_STATE_LOCKED: return "已锁定";
    case UI_STATE_READY: return "准备就绪";
    case UI_STATE_LISTENING: return "正在聆听";
    case UI_STATE_PROCESSING: return "正在思考";
    case UI_STATE_SPEAKING: return "正在播报";
    case UI_STATE_EXECUTING: return "正在执行";
    case UI_STATE_ERROR: return "操作失败";
  }
  return "操作失败";
}

const char *uiMachineCompactTitle(UiMachineState state) {
  switch (state) {
    case UI_STATE_BOOT: return "BOOT SELF-CHECK";
    case UI_STATE_LOCKED: return "ACCESS LOCKED";
    case UI_STATE_READY: return "READY";
    case UI_STATE_LISTENING: return "LISTEN / PTT";
    case UI_STATE_PROCESSING: return "AI THINKING";
    case UI_STATE_SPEAKING: return "SPEAKING";
    case UI_STATE_EXECUTING: return "EXECUTING";
    case UI_STATE_ERROR: return "ERROR";
  }
  return "ERROR";
}

void renderStateHeader(UiMachineState state) {
  oledFillRect(0, 0, OLED_WIDTH, 10, true);
  oledDrawText(4, 1, uiMachineCode(state), 16, true);
  oledDrawText(91, 1, String("P") + String((uint8_t)infoScreen), 3, true);
  oledDrawText(108, 1, String("F") + String(oledFps), 4, true);
}

void renderStateBody(UiMachineState state) {
  uint32_t now = millis();
  oledDrawTextCentered(uiMachineCompactTitle(state), 13, 20);
  oledDrawLine(4, 24, 123, 24, true);

  switch (state) {
    case UI_STATE_BOOT:
      oledDrawText(6, 29, "OLED/AHT/UART CHECK", 20, false);
      oledDrawText(6, 39, String("I2C 0x") + String(oledAddress, HEX), 20, false);
      oledDrawText(6, 49, "FEATURES ONLINE...", 20, false);
      break;
    case UI_STATE_LOCKED:
      oledDrawText(6, 29, "USER -", 20, false);
      oledDrawText(6, 39, "RFID REQUIRED", 20, false);
      oledDrawText(6, 49, "K1 PAGE  K2 STOP", 20, false);
      break;
    case UI_STATE_READY: {
      String temperature = latestAhtOk ? String(latestTemperatureC, 1) + "C" : "--.-C";
      String humidity = latestAhtOk ? String(latestHumidityPct, 0) + "%" : "--%";
      String distance = latestDistanceOk ? String(latestDistanceCm, 0) + "cm" : "--cm";
      oledDrawText(6, 29, String("USER ") + compactForDisplay(currentUserId, 14), 20, false);
      oledDrawText(6, 39, temperature + " " + humidity + " " + distance, 20, false);
      if (now < volumeOverlayUntilMs) {
        oledDrawText(6, 49, String("VOL ") + String(speechVolumePercent) + "% K1 PAGE", 20, false);
      } else {
        oledDrawText(6, 49, "K1 PAGE K2 HOLD REC", 20, false);
      }
      break;
    }
    case UI_STATE_LISTENING:
      oledDrawText(6, 29, "LAPTOP MIC PTT", 20, false);
      oledDrawText(6, 39, "RELEASE TO UPLOAD", 20, false);
      oledDrawText(6, 49, String("USER ") + compactForDisplay(currentUserId, 14), 20, false);
      break;
    case UI_STATE_PROCESSING:
      oledDrawText(6, 29, "ASR/QWEN PIPELINE", 20, false);
      oledDrawText(6, 39, "WAIT FOR RESULT", 20, false);
      oledDrawText(6, 49, String("USER ") + compactForDisplay(currentUserId, 14), 20, false);
      break;
    case UI_STATE_SPEAKING:
      oledDrawText(6, 29, "SYN6288 OUTPUT", 20, false);
      oledDrawText(6, 39, "K2 SHORT: STOP", 20, false);
      oledDrawText(6, 49, "K2 HOLD: BARGE-IN", 20, false);
      break;
    case UI_STATE_EXECUTING:
      oledDrawText(6, 29, "COMMAND", 20, false);
      oledDrawText(6, 39, compactForDisplay(uiEvent.detail, 20), 20, false);
      oledDrawText(6, 49, String("ACK ") + String(uiEvent.ackSeen ? (uiEvent.ackOk ? "OK" : "ERR") : "..."), 20, false);
      break;
    case UI_STATE_ERROR:
      oledDrawText(6, 29, "CHECK LINK / RETRY", 20, false);
      oledDrawText(6, 39, compactForDisplay(uiEvent.detail, 20), 20, false);
      oledDrawText(6, 49, String("BTN ") + compactForDisplay(lastButtonEvent, 15), 20, false);
      break;
  }
}

void renderInfoScreen(uint32_t now) {
  switch (infoScreen) {
    case INFO_SCREEN_USER:
      oledDrawTextCentered("USER CONTEXT", 13, 20);
      oledDrawLine(4, 24, 123, 24, true);
      oledDrawText(6, 29, String("ID ") + compactForDisplay(currentUserId, 17), 20, false);
      oledDrawText(6, 39, String("CARD ") + compactForDisplay(currentCardUid, 15), 20, false);
      oledDrawText(6, 49, String("MODE ") + compactForDisplay(currentUserMode, 14), 20, false);
      break;
    case INFO_SCREEN_LINK:
      oledDrawTextCentered("LINK / FPS", 13, 20);
      oledDrawLine(4, 24, 123, 24, true);
      oledDrawText(6, 29, String("FPS ") + String(oledFps) + " FLUSH 4MS", 20, false);
      oledDrawText(6, 39, String("UART ") + (millis() - lastEspRxActivityMs < 5000 ? "ACTIVE" : "QUIET"), 20, false);
      oledDrawText(6, 49, String("ACK ") + String(uiEvent.ackSeen ? (uiEvent.ackOk ? "OK" : "ERR") : "WAIT"), 20, false);
      break;
    case INFO_SCREEN_SENSORS: {
      String temperature = latestAhtOk ? String(latestTemperatureC, 1) + "C" : "--.-C";
      String humidity = latestAhtOk ? String(latestHumidityPct, 0) + "%" : "--%";
      String distance = latestDistanceOk ? String(latestDistanceCm, 0) + "CM" : "--CM";
      oledDrawTextCentered("SENSORS", 13, 20);
      oledDrawLine(4, 24, 123, 24, true);
      oledDrawText(6, 29, temperature + " HUM " + humidity, 20, false);
      oledDrawText(6, 39, String("DIST ") + distance + " " + latestDistanceZone, 20, false);
      oledDrawText(6, 49, String("POT ") + String(latestPotPct) + "% NTC " + String(latestNtcPct) + "%", 20, false);
      break;
    }
    case INFO_SCREEN_ACTUATORS:
      oledDrawTextCentered("ACTUATORS", 13, 20);
      oledDrawLine(4, 24, 123, 24, true);
      oledDrawText(6, 29, String("VOL ") + String(speechVolumePercent) + "% FAN L" + String(currentFanLevel), 20, false);
      oledDrawText(6, 39, String("LOCK ") + (currentLockOn ? "ON" : "OFF") + " RGB " + latestRgbStatus, 20, false);
      oledDrawText(6, 49, String("BTN ") + compactForDisplay(lastButtonEvent, 15), 20, false);
      break;
    case INFO_SCREEN_MAIN:
    case INFO_SCREEN_COUNT:
      renderStateBody(uiMachineState);
      break;
  }
  if (now < infoOverlayUntilMs && infoScreen != INFO_SCREEN_MAIN) {
    oledDrawText(96, 55, "K1>", 4, false);
  }
}

void renderStatusScreen(uint32_t now) {
  renderStateHeader(uiMachineState);
  if (infoScreen == INFO_SCREEN_MAIN) {
    renderStateBody(uiMachineState);
  } else {
    renderInfoScreen(now);
  }
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
  if (oledFpsWindowMs == 0) {
    oledFpsWindowMs = now;
  }
  oledFrameCounter++;
  if (now - oledFpsWindowMs >= 1000) {
    uint32_t elapsedMs = now - oledFpsWindowMs;
    if (elapsedMs == 0) {
      elapsedMs = 1;
    }
    oledFps = (uint8_t)((oledFrameCounter * 1000UL) / elapsedMs);
    oledFrameCounter = 0;
    oledFpsWindowMs = now;
  }
  renderStatusScreen(now);
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

void updateRgbAnimation() {
  uint32_t now = millis();
  if (now - lastRgbFrameMs < RGB_FRAME_INTERVAL_MS) {
    return;
  }
  lastRgbFrameMs = now;

  if (now < ackFlashUntilMs) {
    if (ackFlashOk) {
      bool flashOn = (((ackFlashUntilMs - now) / 130) & 0x01) == 0;
      writeRgbRaw(false, flashOn, false);
    } else {
      writeRgbRaw(true, false, false);
    }
    return;
  }

  uint16_t phase = (now - uiMachineStateStartedMs) % 1000;
  bool pulse = phase < 520;
  switch (uiMachineState) {
    case UI_STATE_BOOT:
      writeRgbRaw(false, false, pulse);
      break;
    case UI_STATE_LISTENING:
      writeRgbRaw(false, true, true);
      break;
    case UI_STATE_PROCESSING:
    case UI_STATE_SPEAKING:
    case UI_STATE_EXECUTING:
      writeRgbRaw(pulse, pulse, false);
      break;
    case UI_STATE_LOCKED:
    case UI_STATE_ERROR:
      {
        bool doubleBlink = phase < 140 || (phase >= 280 && phase < 420);
        writeRgbRaw(doubleBlink, false, false);
      }
      break;
    case UI_STATE_READY:
      writeRgbRaw(false, true, false);
      break;
  }
}

void updateSystemUi() {
  uint32_t now = millis();
  updateUiMachineState(now);
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

bool sendSyn6288Command(uint8_t command) {
  uint8_t frame[5];
  frame[0] = SYN6288_FRAME_HEADER;
  frame[1] = 0x00;
  frame[2] = 0x01;
  frame[3] = command;
  frame[4] = frame[0] ^ frame[1] ^ frame[2] ^ frame[3];
  espCommandSerial.write(frame, sizeof(frame));
  espCommandSerial.flush();
  delay(6);
  return true;
}

bool speakUtf8Bytes(const uint8_t *bytes, size_t length) {
  uint8_t unicodeBytes[SYN6288_MAX_TEXT_BYTES];
  size_t unicodeLen = 0;
  size_t index = 0;

  String volumeControl = String("[v") + String(speechVolume) + "]";
  for (unsigned int i = 0; i < volumeControl.length(); ++i) {
    if (!appendCodePointAsUtf16Be((uint8_t)volumeControl.charAt(i), unicodeBytes,
                                  sizeof(unicodeBytes), unicodeLen)) {
      return false;
    }
  }

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
  ttsInterrupted = false;
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
  ttsInterrupted = false;
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

bool stopSpeechOutput() {
  stopMusic();
  volumeAnnouncementPending = false;
  ttsInterrupted = true;
  oledRenderPending = true;
  return sendSyn6288Command(SYN6288_CMD_STOP);
}

uint8_t volumeLevelFromPercent(uint8_t percent) {
  return (uint8_t)(((uint16_t)percent * SYN6288_MAX_VOLUME + 50) / 100);
}

uint8_t volumePercentFromLevel(uint8_t level) {
  return (uint8_t)((((uint16_t)level * 10 + SYN6288_MAX_VOLUME / 2) /
                    SYN6288_MAX_VOLUME) *
                   10);
}

bool setSpeechVolume(const String &value, bool announce) {
  (void)announce;
  String normalized = value;
  normalized.trim();
  normalized.toUpperCase();

  int percent = speechVolumePercent;
  if (normalized == "UP") {
    percent += VOLUME_STEP_PERCENT;
  } else if (normalized == "DOWN") {
    percent -= VOLUME_STEP_PERCENT;
  } else {
    if (normalized.length() == 0) {
      return false;
    }
    for (unsigned int i = 0; i < normalized.length(); ++i) {
      if (!isDigit(normalized.charAt(i))) {
        return false;
      }
    }
    int level = normalized.toInt();
    if (level < 0) level = 0;
    if (level > SYN6288_MAX_VOLUME) level = SYN6288_MAX_VOLUME;
    percent = volumePercentFromLevel((uint8_t)level);
  }

  if (percent < 0) percent = 0;
  if (percent > VOLUME_MAX_PERCENT) percent = VOLUME_MAX_PERCENT;
  speechVolumePercent = (uint8_t)percent;
  speechVolume = volumeLevelFromPercent(speechVolumePercent);
  uiEvent.detail = String("VOLUME ") + String(speechVolumePercent) + "%";
  oledRenderPending = true;
  lastVolumeChangeMs = millis();
  volumeOverlayUntilMs = lastVolumeChangeMs + SCREEN_OVERLAY_MS;
  volumeAnnouncementPending = false;
  return true;
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
  RgbState cueRgb = uiMachineBaseRgb();
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

void writeButtonEvent(const String &event) {
  lastButtonEvent = event;
  lastButtonEventMs = millis();
  uiEvent.detail = event;
  oledRenderPending = true;
  writeBack(String("BT:BTN:") + event);
}

void handleKey2Pressed(uint32_t now) {
  uint32_t startedMs = now;
  beginUiEvent(UI_EVENT_LISTEN, "K2 INTERRUPT", "key2", false, startedMs);
  commandHadLight = false;
  commandLightResponseMs = 0;
  commandLightMeasureActive = true;
  setRgb(false, true, true);
  commandLightMeasureActive = false;
  stopSpeechOutput();
  finishUiEvent(0, 0, millis() - startedMs, true);
  writeButtonEvent("KEY2:DOWN");
}

void handleKey2HoldStart(uint32_t now) {
  uint32_t duration = now - key2PressedMs;
  beginUiEvent(UI_EVENT_LISTEN, "PTT RECORDING", "key2", false, now);
  setRgb(false, true, true);
  writeButtonEvent(String("KEY2:HOLD_START:") + String(duration));
}

void handleKey2Released(uint32_t now) {
  uint32_t duration = now - key2PressedMs;
  writeButtonEvent(String("KEY2:UP:") + String(duration));
  if (key2HoldStartSent) {
    beginUiEvent(UI_EVENT_THINK, "PTT UPLOAD", "key2", false, now);
  } else {
    beginUiEvent(UI_EVENT_ACTION, "OUTPUT STOP", "key2", false, now);
    stopSpeechOutput();
    writeButtonEvent(String("KEY2:SHORT:") + String(duration));
  }
}

void updateKey2Button() {
  bool pressed = digitalRead(PIN_DEMO_BUTTON) == LOW;
  uint32_t now = millis();

  if (pressed != key2LastReading) {
    key2LastReading = pressed;
    key2LastChangeMs = now;
  }

  if (now - key2LastChangeMs < BUTTON_DEBOUNCE_MS) {
    return;
  }

  if (pressed == key2StablePressed) {
    if (key2StablePressed && !key2HoldStartSent && now - key2PressedMs >= KEY2_HOLD_START_MS) {
      key2HoldStartSent = true;
      handleKey2HoldStart(now);
    }
    return;
  }

  key2StablePressed = pressed;
  if (key2StablePressed) {
    key2PressedMs = now;
    key2HoldStartSent = false;
    handleKey2Pressed(now);
  } else {
    handleKey2Released(now);
  }
}

void handleInfoButtonShort() {
  uint8_t next = ((uint8_t)infoScreen + 1) % (uint8_t)INFO_SCREEN_COUNT;
  infoScreen = (InfoScreen)next;
  infoOverlayUntilMs = millis() + SCREEN_OVERLAY_MS;
  writeButtonEvent(String("KEY1:PAGE:") + String(next));
}

void handleInfoButtonLong() {
  infoScreen = INFO_SCREEN_MAIN;
  infoOverlayUntilMs = millis() + SCREEN_OVERLAY_MS;
  writeButtonEvent("KEY1:HOME");
}

void updateInfoButton() {
  bool pressed = digitalRead(PIN_INFO_BUTTON) == LOW;
  uint32_t now = millis();

  if (pressed != infoButtonLastReading) {
    infoButtonLastReading = pressed;
    infoButtonLastChangeMs = now;
  }

  if (now - infoButtonLastChangeMs < BUTTON_DEBOUNCE_MS) {
    return;
  }

  if (pressed == infoButtonStablePressed) {
    if (infoButtonStablePressed && !infoButtonLongSent && now - infoButtonPressedMs >= KEY1_LONG_PRESS_MS) {
      infoButtonLongSent = true;
      handleInfoButtonLong();
    }
    return;
  }

  infoButtonStablePressed = pressed;
  if (infoButtonStablePressed) {
    infoButtonPressedMs = now;
    infoButtonLongSent = false;
  } else if (!infoButtonLongSent) {
    handleInfoButtonShort();
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
  uiEvent.detail = String("OLED ") + text;
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
  currentFanLevel = 0;
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
  currentFanLevel = level < 1 ? 1 : (level > 3 ? 3 : level);
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
    encoderVolumeTicks += delta;
    if (encoderVolumeTicks >= ENCODER_STEPS_PER_DETENT) {
      encoderVolumeTicks = 0;
      setSpeechVolume("UP", true);
    } else if (encoderVolumeTicks <= -ENCODER_STEPS_PER_DETENT) {
      encoderVolumeTicks = 0;
      setSpeechVolume("DOWN", true);
    }
  }
  encoderLastState = state;
}

void announceVolumeWhenSettled() {
  volumeAnnouncementPending = false;
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

String nextColonField(const String &text, int &offset) {
  int next = text.indexOf(':', offset);
  String value = next >= 0 ? text.substring(offset, next) : text.substring(offset);
  offset = next >= 0 ? next + 1 : text.length();
  value.trim();
  return value.length() > 0 ? value : "-";
}

bool handleUserContextCommand(const String &payload) {
  int offset = 0;
  currentUserId = nextColonField(payload, offset);
  currentCardUid = nextColonField(payload, offset);
  currentUserMode = nextColonField(payload, offset);
  currentUserMode.toUpperCase();
  if (currentUserId == "-" || currentUserMode == "NONE" || currentUserMode == "DENIED") {
    if (currentUserMode != "DENIED") {
      currentCardUid = "-";
    }
  }
  infoScreen = INFO_SCREEN_USER;
  infoOverlayUntilMs = millis() + SCREEN_OVERLAY_MS;
  uiEvent.detail = String("USER ") + compactForDisplay(currentUserId, 14);
  oledRenderPending = true;
  return true;
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

  if (command.startsWith("NET:UI:USER:")) {
    return handleUserContextCommand(command.substring(strlen("NET:UI:USER:")));
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
    line += ",screen=";
    line += String((uint8_t)infoScreen);
    line += ",fps=";
    line += String(oledFps);
    line += ",volume_pct=";
    line += String(speechVolumePercent);
    line += ",user_id=";
    line += currentUserId;
    line += ",card_uid=";
    line += currentCardUid;
    line += ",user_mode=";
    line += currentUserMode;
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

  if (command == "NET:TTS:STOP" || command == "NET:AUDIO:STOP") {
    return stopSpeechOutput();
  }

  if (command.startsWith("NET:TTS:")) {
    return speakText(command.substring(strlen("NET:TTS:")));
  }

  if (command.startsWith("NET:TTSHEX:")) {
    return speakHexText(command.substring(strlen("NET:TTSHEX:")));
  }

  if (command.startsWith("NET:VOLUME:")) {
    return setSpeechVolume(command.substring(strlen("NET:VOLUME:")), false);
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
    currentLockOn = true;
    setRgb(true, false, false);
    return true;
  }

  if (command == "NET:LOCK:OFF") {
    currentLockOn = false;
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
  RgbState cueRgb = uiMachineBaseRgb();
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
  pinMode(PIN_INFO_BUTTON, INPUT_PULLUP);
  pinMode(PIN_DEMO_BUTTON, INPUT_PULLUP);

  Wire.begin();
  Wire.setClock(400000);
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
  announceVolumeWhenSettled();
  updateServoPulse();
  updateMusicPlayer();
  updateInfoButton();
  updateKey2Button();
  updateUiDemo();
  updateSystemUi();
  if (millis() - lastTelemetryMs >= TELEMETRY_INTERVAL_MS && canSendPeriodicTelemetry()) {
    lastTelemetryMs = millis();
    sendTelemetrySnapshot();
  }
}
