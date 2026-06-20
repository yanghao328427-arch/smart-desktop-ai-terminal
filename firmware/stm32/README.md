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
NET:TTS:hello
NET:TTSHEX:E4BDA0E5A5BD
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

## System event UI and timing logs

The executor keeps a small non-blocking event UI for demo feedback:

- OLED shows the current event, short detail, parse/action/light/ACK timing, and action id or uptime.
- RGB gives an immediate cue for every trigger. ACK OK briefly flashes cyan; ACK ERR flashes red.
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

`KEY2/PB13` from the Botelvdong STM32 learning kit package is the physical conversation button. A short press sends:

```text
BT:BTN:KEY2:SHORT
```

The ESP32S3 bridge uses that event to start the existing mic -> ASR -> backend model -> STM32 action chain. `NET:UI:LISTEN`, `NET:UI:THINK`, `NET:UI:ACTION`, `NET:UI:ACK`, `NET:UI:IDLE`, and `NET:UI:ERROR` drive the OLED/RGB expression animations for that real dialogue flow.

`NET:UI:DEMO` remains a hidden desk-side hardware self-test command only. It is not bound to the button and is not the primary demo story. `KEY2/PB13` is the current firmware button by default. The native board map also provides `KEY1/PB12`; the relay output is `PB5`, not `PB12`.

The sketch now also emits periodic telemetry lines for ESP32S3 to forward:

```text
BT:{"pot_raw":561,"pot_pct":54,"ntc_raw":1017,"ntc_pct":99,"tracking_signal":false,"aht20_ok":true,"temperature_c":26.4,"humidity_pct":62.0,"distance_ok":true,"distance_enabled":true,"distance_cm":31.4,"distance_zone":"near","env_state":"comfortable","interaction_hint":"object_near","rgb_mode":"sensor","rgb_status":"near_object","rgb_reason":"interaction_zone","encoder_delta":0,"encoder_position":0,"encoder_button":false}
```

`NET:TELEMETRY?` can be sent from USB or ESP32S3 to force one immediate snapshot.

RGB status mode is enabled by default after short command/ACK flashes:

- green with a short blue heartbeat: sensors healthy and idle.
- cyan pulse: object in front / interaction zone; cyan/white tick: tracking signal high.
- yellow blink: temperature or humidity needs attention.
- red fast/double blink: object too close or a sensor needs checking.
- blue slow blink: waiting for first telemetry.

`NET:RGB:STATUS?` reports the current `rgb_status` and reason; `NET:RGB:MODE:EVENT` restores legacy event-only RGB animation, and `NET:RGB:MODE:SENSOR` returns to sensor-aware idle lighting.

## Notes before flashing

- This sketch targets STM32duino-style Arduino builds. If the final Keil project is used instead, port the parser and command switch directly.
- Fan control now uses the DRV8833 port from the Botelvdong kit. On the current fan wiring, `PA1/TIM2_CH2` is the PWM drive input and `PA0/TIM2_CH1` is held LOW so the fan spins the useful direction. `NET:FAN:ON:<1-3>` maps to about 85%, 92%, and 100% PWM duty; `NET:FAN:OFF` and `NET:MOTOR:OFF` pull both DRV8833 inputs LOW. `PB5` remains the native relay output pin, but it is not the fan output in this build.
- SYN6288 is reached through `Serial3` TX/PB10. `NET:TTS:` and `NET:TTSHEX:` are both converted into a SYN6288 synthesis frame (`0xFD + len + 0x01 + type + payload + xor`) instead of sending raw text bytes.
- The current implementation decodes UTF-8 and sends SYN6288 in Unicode mode (`type=0x03`), which avoids keeping a GBK lookup table on STM32 while still handling Chinese short sentences.
- The UART parser now counts empty ESP-side line delimiters on USB logs. If the "first line swallowed" issue still appears on hardware, those counters help distinguish "sender prefixed an empty CR/LF" from "STM32 lost actual payload bytes".
- Sensor telemetry currently samples `PA5` potentiometer, `PA4` NTC, `PB14` tracking sensor, `AHT20` on `PB6/PB7` I2C, ultrasonic `PA11/PA10`, and rotary encoder `PA8/PA9/PB15`.
- On late 2026-06-13 the HCSR04 module was connected on `PA11/PA10`; telemetry now enables distance by default. `NET:ULTRASONIC:OFF` is still available if the module is unplugged again.
- DRV8833 follows the kit example: `PA0/TIM2_CH1` and `PA1/TIM2_CH2`. The native buzzer pin is `PB9`; the previous `PA1` buzzer assumption was wrong and explains a silent buzzer test on this soldered board. Firmware defaults to DRV8833-connected mode and keeps both motor inputs LOW on boot. The fan is wired to this DRV8833 port, so fan testing should use `NET:FAN:ON:<1-3>` / `NET:FAN:OFF`, not the old `PB5` relay path.
- `NET:BEEP` now targets the native passive buzzer pin `PB9`. `NET:MUSIC:<SUCCESS|ALERT|SCALE|STARTUP|BIRTHDAY>` plays a short non-blocking melody on the same pin; `NET:MUSIC:STOP` cancels playback. Do not run buzzer or music commands during no-sound or late-night validation.
- `NET:SERVO:<angle>` accepts only numeric angles from `0` to `180` and drives `PB8` with a short non-blocking servo pulse train.
