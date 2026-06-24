# ESP32S3 Sense edge bridge

This Arduino sketch is the bridge between the FastAPI backend and STM32.

## Local configuration

Do not write the Wi-Fi password into source code. Flash the sketch, open `COM8` at `115200`, then configure locally:

```text
CFG:WIFI:<ssid>,<password>
CFG:SERVER:http://<backend-lan-ip>:8082
CFG:TOKEN:<device-token>
CFG:WIFI:SHOW
CFG:UART:PING
CFG:TTS:hello
CFG:OLED:LISTEN
CHAT:who are you
```

The values are stored in ESP32 Preferences/NVS. `CFG:TOKEN` is optional for a local backend with no auth, but required when the public backend configures `DEVICE_TOKEN`; do not commit the real token.

## Build

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge/esp32s3/main
```

## Runtime role

- WebSocket client connects to `/api/realtime/ws`. In the China-mainland demo route, it connects to the laptop relay over LAN `ws://`; the relay maintains the Hugging Face `wss://` connection.
- `stm32/commands` lines are forwarded to STM32.
- `BT:ACK:<action_id>:OK/ERR` from STM32 is sent back over WebSocket when connected, with `POST /api/hardware/ack` as the HTTP fallback.
- `BT:{...}` or `{...}` telemetry JSON from STM32 is sent to `/api/hardware/telemetry`.
- `BT:BTN:*` button events from STM32 are forwarded to the backend over WebSocket, with `/api/hardware/button` as the HTTP fallback.
- When WebSocket is disconnected, the bridge polls `/api/hardware/commands/{device_id}` every 10 seconds as a fallback. WebSocket reconnect attempts are limited to every 30 seconds to avoid amplifying public rate limits.
- Hugging Face heartbeat posts are limited to every 15 seconds and telemetry posts to every 10 seconds. Local STM32 parsing and optional IoTDA reporting continue independently.
- RC522 UID scans are sent to `/api/rfid/scan` with `source=rc522` and `X-Device-Token` when configured.
- The bridge sends an immediate RFID OLED cue and beep before the backend round trip, then the backend response drives the authorized/denied voice announcement.
- Repeated reads of the same RC522 UID are suppressed for 15 seconds to avoid repeated unlock/TTS actions while a card is held near the reader.
- HALT-state cards are retried with `PICC_WakeupA()`.
- The onboard ESP32S3 Sense microphone path is intentionally disabled in firmware (`MIC_PATH_ENABLED=false`). `CFG:MIC:*` commands remain rejected. `KEY2/PB13` button events are now forwarded as control events: short press interrupts current output; long press/release is consumed by the laptop-side PTT listener, which records from the computer microphone and uploads to ASR.
- Use the browser or laptop-side speech listener for voice input while the ESP32S3 bridge continues to forward backend commands and button events between the backend and STM32.
- `CFG:WS:WAKE` is a USB-only transport diagnostic: when WebSocket is connected, it sends a backend `wake` event so the returned STM32 command and ACK path can be verified without a user-context token.
