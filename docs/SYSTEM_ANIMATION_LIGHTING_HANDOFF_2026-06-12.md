# System Animation And Lighting Handoff - 2026-06-12

## First Instruction To Paste

```text
请先读取 docs/SYSTEM_ANIMATION_LIGHTING_HANDOFF_2026-06-12.md，然后为 STM32 显示屏编译一套流畅的系统动画和灯光反馈系统，覆盖所有触发事件的响应时间显示与日志，包括 OLED、RGB/灯光、风扇、蜂鸣器、SYN6288 TTS、RFID/ACK 等；不要继续处理 ASR 长句语音问题，不要读取、打印或修改 backend/.env，保留现有 /api/asr/recognized 和 ESP32S3 ASR-only 测试命令。
```

## Window Boundary

- 当前窗口保留给 ESP32S3 板载麦克风 ASR 长句问题。
- 新窗口只做系统动画、OLED 显示、RGB/灯光反馈、触发事件响应时间展示。
- 不要在新窗口继续调 ASR 录音时长、FunASR、Paraformer、`/api/asr/transcribe` 或 `backend/.env`。

## Current Voice Issue To Leave Alone

ASR 当前阶段已经记录在 `docs/ASR_NEXT_WINDOW_TEST_HANDOFF_2026-06-12.md`：

- 6 秒 ESP32S3 板载麦克风 WAV 上传稳定，单段约 `192044 bytes`。
- `CFG:MIC:REC:CUE:ASRONLY` 可隔离 ASR，不触发后续 Qwen/TTS 回复。
- 6 秒长句仍会截断句尾；有效 WAV 末尾 500ms 仍有明显语音能量。
- 8 秒一次性 WAV buffer 实测失败，串口显示 `[MIC] buffer alloc failed`。
- 已回退并刷入 `MIC_RECORD_SECONDS = 6` 稳定固件。

## Animation And Lighting Goal

为 STM32 侧建立一套展示用的“系统事件动画层”：

- OLED 显示当前事件、动作状态和响应时间。
- RGB/灯光随事件切换，并记录灯光响应耗时。
- 风扇、蜂鸣器、TTS、OLED、锁定/解锁、AI busy/idle、RFID/ACK 等触发事件都有对应视觉反馈。
- USB 日志输出每次事件的响应时间，便于答辩展示。
- ACK 协议保持不变：包装命令仍返回 `BT:ACK:<action_id>:OK/ERR`。
- 动画必须尽量非阻塞，不要拖慢串口解析、传感器上报和 ACK。

## Relevant Files

- `firmware/stm32/stm32_executor/stm32_executor.ino`
  - STM32 命令解析、RGB、蜂鸣器、风扇、SYN6288、OLED stub、ACK。
- `firmware/stm32/README.md`
  - STM32 协议说明。
- `docs/PROTOCOL.md`
  - 后端/ESP32S3/STM32 通信协议。
- `docs/HARDWARE_WIRING.md`
  - 接线基线，不要临时换线。

## Current STM32 Baseline

- RGB pins:
  - red `PB0`
  - green `PA7`
  - blue `PA6`
- buzzer: `PB9` (corrected from the earlier wrong `PA1` assumption)
- relay/default pin: `PB5`; `PB12` is `KEY1`
- OLED / AHT20 I2C bus:
  - `SCL=PB6`
  - `SDA=PB7`
- OLED doc address is `0x7A` as an 8-bit address, likely `0x3D` as 7-bit; common fallback is `0x3C`.
- Current `showOledText(...)` only logs `[OLED] ...` to USB; real display drawing still needs implementation.

## Commands To Preserve

```text
NET:CMD:<action_id>:NET:TTSHEX:<utf8_hex>
NET:CMD:<action_id>:NET:TTS:<text>
NET:CMD:<action_id>:NET:OLED:<text>
NET:CMD:<action_id>:NET:FAN:ON:2
NET:CMD:<action_id>:NET:FAN:OFF
NET:CMD:<action_id>:NET:BEEP
NET:CMD:<action_id>:NET:LOCK:ON
NET:CMD:<action_id>:NET:LOCK:OFF
NET:CMD:<action_id>:NET:AI:BUSY
NET:CMD:<action_id>:NET:AI:IDLE
NET:CMD:<action_id>:NET:AI:OFF
NET:UART?
NET:TELEMETRY?
```

## Suggested Implementation Shape

- Add a small UI event state machine in `stm32_executor.ino`.
- On command receipt, record `eventStartMs = millis()`.
- Execute the hardware action immediately.
- Record separate timings:
  - command parse time
  - action execution time
  - light/RGB response time
  - ACK total time
- Update OLED/RGB animation from `loop()` with a frame interval, not with long delays.
- Keep TTS synthesis frame sending as-is; do not make SYN6288 playback duration block ACK.
- If adding OLED drawing, prefer a small compile-safe SSD1306 I2C implementation or an already installed library only after checking availability.

## Verification Commands

Compile STM32:

```powershell
arduino-cli compile --fqbn STMicroelectronics:stm32:GenF1:pnum=BLUEPILL_F103C8 --build-path .tmp\build-stm32 firmware\stm32\stm32_executor
```

Optional flash if hardware is connected:

```powershell
openocd.exe -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program .tmp/build-stm32/stm32_executor.ino.elf verify reset exit"
```

Useful direct tests after flashing:

```text
NET:OLED:AI READY
NET:AI:BUSY
NET:AI:IDLE
NET:BEEP
NET:FAN:ON:2
NET:FAN:OFF
NET:TTSHEX:E4BDA0E5A5BD
NET:TELEMETRY?
```

## Rollback Note

An earlier partial attempt to add OLED animation constants/state to `firmware/stm32/stm32_executor/stm32_executor.ino` was reverted in the voice-debug window. The STM32 baseline was recompiled successfully after rollback:

```text
Sketch uses 37952 bytes (57%) of program storage space.
Global variables use 2304 bytes (11%) of dynamic memory.
```
