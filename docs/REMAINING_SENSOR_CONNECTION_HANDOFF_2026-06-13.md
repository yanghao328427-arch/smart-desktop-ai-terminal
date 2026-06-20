# Remaining Sensor Connection Handoff - 2026-06-13

## First Instruction To Paste

```text
请先读取 docs/REMAINING_SENSOR_CONNECTION_HANDOFF_2026-06-13.md，然后在新窗口只安排并实现剩余传感器连接与相关代码验收：声音/KEY2/ASR/WiFi 上传问题还没有解决，先留到白天继续排查；今晚不要继续改 ASR/语音链路。不要读取、打印或修改 backend/.env；保留 /api/asr/recognized、ESP32S3 ASR-only 命令和现有真实语音链路现状。优先从 docs/HARDWARE_WIRING.md 与 firmware/stm32/stm32_executor/stm32_executor.ino 出发，确认 AHT20/OLED I2C、PA5 电位器、PA11/PA10 超声波、旋转编码器/舵机等剩余传感器接线，补齐 STM32 遥测/后端/前端展示代码，并用串口、后端 diagnostics、Web/小程序显示做验收。
```

## Stage Boundary

声音系列问题还没有解决，本 handoff 只是把它从今晚的新窗口里切出去，留到白天继续专项排查：

- ESP32S3 板载麦克风 6 秒 WAV 仍约 `192044` 字节。
- `/api/asr/transcribe`、FunASR、动作规划、ESP32S3 转发、STM32 ACK 主链路有过成功证据，但 KEY2/ASR/WiFi 上传稳定性仍需白天继续实测确认。
- 已尝试为 WiFiClient 大正文随机断开增加真实 WAV 分块上传兜底；这不是最终验收结论，不应写成声音问题已解决。

今晚的新窗口不要继续扩 ASR、录音时长、语音兜底、KEY2 对话链路或 WiFi 上传策略；这些声音问题留到白天单独处理。只有当传感器验收被当前基础链路明确阻塞时，才做最小诊断，不做语音功能改造。

## Goal For The New Window

把剩余传感器和接口做成答辩可验收状态：

```text
STM32 sensors/connectors
-> periodic BT:{...} telemetry
-> ESP32S3 forwards /api/hardware/telemetry
-> backend state.sensors
-> Web console / miniprogram display
-> AI answer can mention current sensor state
```

优先顺序：

1. 确认现有 AHT20 温湿度、PA5 电位器、超声波测距三类数据的真实接线和稳定性。
2. 优先修 `distance_ok=false` 的超声波剩余问题。
3. 再决定是否补旋转编码器 `PA8/PA9/PB15`、舵机 `PB8` 或其他板载接口字段。
4. 代码只补传感器遥测、展示和验收所需内容，不重构声音链路。

## Hard Constraints

- Do not read, print, or modify `backend/.env`.
- Do not remove or bypass `POST /api/asr/recognized`.
- Keep ESP32S3 ASR-only commands:

```text
CFG:MIC:REC:ASRONLY
CFG:MIC:REC:CUE:ASRONLY
```

- Do not use fixed text to pretend the physical voice path works.
- Do not work on ASR/WiFi upload in this sensor window; leave those unresolved voice issues for the daytime voice-debug window unless they directly block sensor validation.
- Keep `docs/HARDWARE_WIRING.md` as the wiring truth source unless a new measured wiring correction is documented.

## Current Wiring Baseline

From `docs/HARDWARE_WIRING.md`:

| Part | Wiring / Pin |
| --- | --- |
| OLED I2C | `SCL=PB6`, `SDA=PB7`, documented 8-bit address `0x7A` -> likely 7-bit `0x3D`; fallback `0x3C` |
| AHT20 | same I2C bus `PB6/PB7`; documented `0x70` likely maps to 7-bit `0x38`, current code uses `0x38` |
| Ultrasonic | `TRIG=PA11`, `ECHO=PA10` |
| Potentiometer | `PA5` |
| RGB | blue `PA6`, green `PA7`, red `PB0` |
| Buzzer | `PB9` |
| Servo | `PB8` |
| Rotary encoder | `A=PA8`, `B=PA9`, button `PB15` |
| KEY2 physical dialogue button | `PB13` |
| Relay output/default | `PB5`; `KEY1` remains `PB12` |

ESP32S3 to STM32 remains:

The ESP32S3 side wiring below is unchanged from the previous scheme. The native STM32 board image only corrects STM32 board/module pins.

| Direction | Wiring |
| --- | --- |
| ESP32S3 -> STM32 commands | ESP32S3 `D5/GPIO6/TX` -> STM32 `PB11/USART3_RX`, `9600 8N1` |
| STM32 -> ESP32S3 ACK/telemetry | STM32 `PB3/software TX` -> ESP32S3 `D7/GPIO44/RX`, `4800 8N1` |
| Debug | STM32 USB `COM7`; ESP32S3 USB `COM8` |

## Current Code Baseline

Relevant files:

```text
firmware/stm32/stm32_executor/stm32_executor.ino
firmware/stm32/README.md
docs/HARDWARE_WIRING.md
docs/PROTOCOL.md
backend/app/ai.py
backend/app/static/console.html
miniprogram/pages/index/index.js
miniprogram/pages/index/index.wxml
```

STM32 current behavior:

- Periodic telemetry interval is about 4 seconds.
- `buildTelemetryJson()` emits:

```json
{"pot_raw":561,"aht20_ok":true,"temperature_c":26.4,"humidity_pct":62.0,"distance_ok":false}
```

- If ultrasonic succeeds, it also emits `distance_cm`.
- `NET:TELEMETRY?` forces one immediate telemetry snapshot.
- `NET:I2C?` scans the `PB6/PB7` I2C bus and is the fastest way to confirm OLED/AHT20 presence.
- `NET:UI:STATUS?` reports UI/OLED status.

Backend/frontend current behavior:

- `RuntimeStore.telemetry(...)` merges arbitrary sensor keys into `state.sensors`.
- `backend/app/ai.py` already uses `temperature_c`, `humidity_pct`, `distance_cm`, `distance_ok`, and `pot_raw` in sensor-aware replies.
- Web console already displays temperature, humidity, distance, and potentiometer fields.
- Existing progress notes recorded AHT20 and potentiometer reaching backend successfully; ultrasonic code path existed but returned `distance_ok=false`.

## Known Remaining Issues

- Ultrasonic distance is the main unresolved sensor: previous backend state showed `distance_ok=false`.
- Check physical details before changing code:
  - `TRIG=PA11`, `ECHO=PA10` actually connected.
  - Sensor has stable power and common ground.
  - Object is within measurable range and pointed at the sensor.
  - Echo level is safe for STM32 input.
- If wiring is correct and `distance_ok` stays false, add temporary USB-only debug logs around `pulseIn(...)` duration and timeout. Do not spam ESP32S3 telemetry with raw debug noise unless it is needed for diagnosis.
- Rotary encoder and servo are documented but not yet a core demo blocker. Add them after the three primary telemetry fields are stable.

## Recommended First Work Order

1. Inspect `docs/HARDWARE_WIRING.md`, `firmware/stm32/README.md`, and `firmware/stm32/stm32_executor/stm32_executor.ino`.
2. Use STM32 USB `COM7` to run `NET:I2C?`, `NET:UI:STATUS?`, and `NET:TELEMETRY?`.
3. Confirm I2C sees AHT20 at `0x38` and OLED at `0x3D` or `0x3C`.
4. Turn the potentiometer and verify `pot_raw` changes in serial and backend diagnostics.
5. Fix ultrasonic until `distance_ok=true` and `distance_cm` changes when moving an object.
6. If adding encoder:
   - Add debounced A/B state tracking in STM32 loop.
   - Emit concise telemetry fields such as `encoder_delta`, `encoder_position`, `encoder_button`.
   - Add Web/miniprogram display only after serial telemetry is stable.
7. If adding servo:
   - Treat it as an actuator, not a sensor.
   - Implement a safe `NET:SERVO:<angle>` path only after verifying `PB8` hardware and power.

## Useful Commands

Backend checks:

```powershell
curl.exe --noproxy "*" http://127.0.0.1:8083/api/health
curl.exe --noproxy "*" http://127.0.0.1:8083/api/realtime/diagnostics/desktop-agent-001
```

STM32 compile:

```powershell
arduino-cli compile --fqbn STMicroelectronics:stm32:GenF1:pnum=BLUEPILL_F103C8 --build-path .tmp\build-stm32 firmware\stm32\stm32_executor
```

STM32 flash:

```powershell
openocd.exe -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program .tmp/build-stm32/stm32_executor.ino.elf verify reset exit"
```

STM32 serial checks on `COM7`:

```powershell
python tools\serial_console.py COM7 --baud 115200 --line "NET:I2C?" --monitor --monitor-seconds 20
python tools\serial_console.py COM7 --baud 115200 --line "NET:UI:STATUS?" --monitor --monitor-seconds 20
python tools\serial_console.py COM7 --baud 115200 --line "NET:TELEMETRY?" --monitor --monitor-seconds 20
```

ESP32S3 bridge monitor on `COM8`:

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 20 --monitor --monitor-seconds 120
```

Backend tests after code changes:

```powershell
python -m pytest backend\tests -q
```

## Acceptance Criteria

Minimum acceptable sensor phase:

- `pot_raw` changes when the potentiometer is turned.
- `aht20_ok=true`, with plausible `temperature_c` and `humidity_pct`.
- `distance_ok=true` at least for a controlled object placement, with plausible `distance_cm`.
- Backend diagnostics show the same fresh values under `state.sensors`.
- Web console and miniprogram display the values without layout breakage.
- AI replies can mention temperature/humidity/distance/pot values through existing sensor context.
- Existing text -> backend -> STM32 ACK path remains intact, and current voice-related code is not regressed. Do not claim the voice path is finally solved in this sensor handoff.

Optional stretch:

- Add rotary encoder telemetry and display.
- Add safe servo command support with an explicit angle range and no blocking delays.
- Add a short `docs/` verification note with final measured wiring and screenshots/log snippets.

## Do Not Do In The New Window

- Do not continue the ASR/KEY2/WiFi upload work in this sensor window; it is unresolved and reserved for daytime debugging.
- Do not redesign `/api/asr/transcribe` or `/api/asr/recognized`.
- Do not use `/api/asr/recognized` or mock text as a replacement for hardware voice success.
- Do not change `backend/.env`.
- Do not move ESP32S3/STM32 UART pins unless the wiring baseline is deliberately updated and documented.
