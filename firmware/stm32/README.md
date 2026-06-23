# STM32 executor firmware

`stm32_executor/stm32_executor.ino` is the current STM32-side protocol executor skeleton.

## Protocol acceptance

It accepts both wrapped production commands and direct debug commands:

```text
NET:CMD:<action_id>:NET:TTSHEX:<utf8_hex_text>
NET:CMD:<action_id>:NET:OLED:<text>
NET:CMD:<action_id>:NET:FAN:ON:2
NET:CMD:<action_id>:NET:BEEP
NET:CMD:<action_id>:NET:MUSIC:SUCCESS
NET:CMD:<action_id>:NET:MUSIC:STOP
NET:UART?
NET:I2C?
NET:UI:STATUS?
NET:UI:LISTEN
NET:UI:THINK
NET:UI:ACTION
NET:UI:ACK
NET:UI:IDLE
NET:UI:ERROR
NET:UI:DEMO
NET:UI:DEMO:STOP
NET:UI:USER:user_123:04A1B2C3:STUDY
NET:TTS:hello
NET:TTSHEX:E4BDA0E5A5BD
NET:TTS:STOP
NET:VOLUME:8
NET:VOLUME:UP
NET:MUSIC:SUCCESS
NET:MUSIC:ALERT
NET:MUSIC:SCALE
NET:MUSIC:STARTUP
NET:MUSIC:BIRTHDAY
NET:MUSIC:STOP
NET:RGB:STATUS?
NET:RGB:LEGEND?
NET:RGB:MODE:SENSOR
NET:RGB:MODE:EVENT
NET:ULTRASONIC:ON
NET:ULTRASONIC:OFF
NET:MOTOR:OFF
NET:SERVO:90
```

Wrapped commands return:

```text
BT:ACK:<action_id>:OK
BT:ACK:<action_id>:ERR
```

Direct debug commands return `BT:OK`, `BT:ERR`, or `BT:PONG:<uptime_ms>`.

## Persistent UI state machine and timing logs

The executor separates incoming events from the persistent device state:

- The eight states are `S0 BOOT`, `S1 LOCKED`, `S2 READY`, `S3 LISTEN`, `S4 PROCESS`, `S5 SPEAK`, `S6 EXEC`, and `S7 ERROR`.
- OLED uses a fixed instrumentation layout: inverted state header, compact ASCII state title, divider, and dense status/action rows. `KEY1/PB12` switches the user, link/FPS, sensor, and actuator sub-screens; long press returns to the main state screen.
- UART health checks, telemetry queries, RFID notices, and arbitrary OLED text do not overwrite the persistent state. In particular, `LOCKED` remains locked until `NET:LOCK:OFF`, even while heartbeats and telemetry continue.
- RGB follows the same state machine: blue=startup, green=ready, cyan=listening, yellow=processing/speaking/executing, red=locked/error.
- The ready screen shows current user id plus real sensor values; unavailable values use explicit dashes. OLED refresh runs at 400 kHz I2C with a 4 ms page-flush cadence and displays measured FPS on the link screen.
- Parse/action/light/ACK timing and action ids remain on USB logs instead of appearing on the user-facing OLED.
- USB logs one timing line per handled command:

```text
[EVT] source=ESP event=FAN ON action_id=act_123 status=OK parse_ms=0 action_ms=0 light_ms=0 ack_total_ms=7 detail=FAN ON
```

Production ACK lines are unchanged:

```text
BT:ACK:<action_id>:OK
BT:ACK:<action_id>:ERR
```

`NET:RFID:<text>` is also accepted as a direct visual debug cue. In the production RFID flow the ESP32S3/backend still normally trigger OLED/TTS/LOCK commands and receive the same STM32 ACK lines.

`NET:I2C?` scans the PB6/PB7 I2C bus and prints detected device addresses to USB, which is the fastest way to confirm whether the OLED answers at `0x3D` or `0x3C`.

For desk-side demonstration, send:

```text
NET:UI:DEMO
```

It runs a non-blocking local sequence across OLED, AI busy/idle, SYN6288 TTS, fan, buzzer, lock/unlock, RFID ACK, RGB animation, OLED timing, and USB timing logs. Stop it with:

```text
NET:UI:DEMO:STOP
```

Check UI health with:

```text
NET:UI:STATUS?
```

`KEY2/PB13` from the Botelvdong STM32 learning kit package is the physical interruption/PTT button. Pressing it immediately stops current SYN6288 output and sends:

```text
BT:BTN:KEY2:DOWN
```

Holding it past about 600 ms sends `BT:BTN:KEY2:HOLD_START:<duration_ms>` so the laptop-side listener starts recording from the computer microphone. Releasing sends `BT:BTN:KEY2:UP:<duration_ms>`; a short press also sends `BT:BTN:KEY2:SHORT:<duration_ms>`. The ESP32S3 bridge only forwards these events to the backend; it does not use the onboard ESP32S3 microphone.

`NET:UI:LISTEN`, `NET:UI:THINK`, `NET:UI:ACTION`, `NET:UI:ACK`, `NET:UI:IDLE`, `NET:UI:ERROR`, and `NET:UI:USER:<user_id>:<uid>:<mode>` drive the OLED/RGB state and current-user display for the real dialogue flow.

`NET:UI:DEMO` remains a hidden desk-side hardware self-test command only. It is not bound to the button and is not the primary demo story. `KEY2/PB13` is the current firmware interruption/PTT button by default. `KEY1/PB12` is the OLED information-screen switch. The relay output is `PB5`, not `PB12`.

The sketch now also emits periodic telemetry lines for ESP32S3 to forward:

```text
BT:{"pot_raw":561,"pot_pct":54,"ntc_raw":1017,"ntc_pct":99,"tracking_signal":false,"aht20_ok":true,"temperature_c":26.4,"humidity_pct":62.0,"distance_ok":true,"distance_enabled":true,"distance_cm":31.4,"distance_zone":"near","env_state":"comfortable","interaction_hint":"object_near","rgb_mode":"sensor","rgb_status":"near_object","rgb_reason":"interaction_zone","encoder_delta":0,"encoder_position":0,"encoder_button":false}
```

`NET:TELEMETRY?` can be sent from USB or ESP32S3 to force one immediate snapshot.

Sensor-derived `rgb_status`, `rgb_reason`, and `rgb_mode` fields remain in telemetry for backend, Web, and mini-program compatibility. `NET:RGB:STATUS?`, `NET:RGB:LEGEND?`, `NET:RGB:MODE:EVENT`, and `NET:RGB:MODE:SENSOR` keep their existing command and response formats.

Those sensor fields no longer commandeer the physical RGB indicator. The physical lamp consistently reports the human interaction state, while sensor detail stays on the OLED, Web, mini program, and diagnostic telemetry.

## Notes before flashing

- This sketch targets STM32duino-style Arduino builds. If the final Keil project is used instead, port the parser and command switch directly.
- Fan control now uses the DRV8833 port from the Botelvdong kit. On the current fan wiring, `PA1/TIM2_CH2` is the PWM drive input and `PA0/TIM2_CH1` is held LOW so the fan spins the useful direction. `NET:FAN:ON:<1-3>` maps to about 85%, 92%, and 100% PWM duty; `NET:FAN:OFF` and `NET:MOTOR:OFF` pull both DRV8833 inputs LOW. `PB5` remains the native relay output pin, but it is not the fan output in this build.
- SYN6288 is reached through `Serial3` TX/PB10. `NET:TTS:` and `NET:TTSHEX:` are both converted into a SYN6288 synthesis frame (`0xFD + len + 0x01 + type + payload + xor`) instead of sending raw text bytes.
- SYN6288 speech volume defaults to 60%. `NET:VOLUME:<0-16|UP|DOWN>` remains protocol-compatible, while the device maps it to a user-facing 0%-100% range. Each rotary-encoder detent and each `UP`/`DOWN` command changes volume by 10%, clamps at 0%/100% without wrapping, and OLED volume readouts use percentages only. Volume changes are shown on OLED only; the device no longer speaks the current volume unless the AI is explicitly asked.
- The current implementation decodes UTF-8 and sends SYN6288 in Unicode mode (`type=0x03`), which avoids keeping a GBK lookup table on STM32 while still handling Chinese short sentences.
- The UART parser now counts empty ESP-side line delimiters on USB logs. If the "first line swallowed" issue still appears on hardware, those counters help distinguish "sender prefixed an empty CR/LF" from "STM32 lost actual payload bytes".
- Sensor telemetry currently samples `PA5` potentiometer, `PA4` NTC, `PB14` tracking sensor, `AHT20` on `PB6/PB7` I2C, ultrasonic `PA11/PA10`, and rotary encoder `PA8/PA9/PB15`.
- On late 2026-06-13 the HCSR04 module was connected on `PA11/PA10`; telemetry now enables distance by default. `NET:ULTRASONIC:OFF` is still available if the module is unplugged again.
- DRV8833 follows the kit example: `PA0/TIM2_CH1` and `PA1/TIM2_CH2`. The native buzzer pin is `PB9`; the previous `PA1` buzzer assumption was wrong and explains a silent buzzer test on this soldered board. Firmware defaults to DRV8833-connected mode and keeps both motor inputs LOW on boot. The fan is wired to this DRV8833 port, so fan testing should use `NET:FAN:ON:<1-3>` / `NET:FAN:OFF`, not the old `PB5` relay path.
- `NET:BEEP` now targets the native passive buzzer pin `PB9`. `NET:MUSIC:<SUCCESS|ALERT|SCALE|STARTUP|BIRTHDAY>` plays a short non-blocking melody on the same pin; `NET:MUSIC:STOP` cancels playback. Do not run buzzer or music commands during no-sound or late-night validation.
- `NET:SERVO:<angle>` accepts only numeric angles from `0` to `180` and drives `PB8` with a short non-blocking servo pulse train.
