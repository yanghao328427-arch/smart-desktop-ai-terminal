# KEY2 Dialogue Error Handoff - 2026-06-12

## First Instruction To Paste

```text
请先读取 docs/KEY2_DIALOGUE_ERROR_HANDOFF_2026-06-12.md，然后继续排查 KEY2 物理按键触发真实人机智能对话链路的问题：当前按 KEY2 后 STM32 OLED/RGB 能进入 LISTEN，ESP32S3 能录音，录音结束后进入 THINK，但随后变成 ERROR，没有给出大模型回答或 STM32 物理动作。不要读取、打印或修改 backend/.env；保留现有 /api/asr/recognized 和 ESP32S3 ASR-only 测试命令。
```

## Current Goal

项目主线不是本地硬件表演，而是：

```text
KEY2 / 语音 / RFID / 小程序
-> ESP32S3 / 后端
-> ASR / 大模型理解
-> 后端生成 STM32 NET:* 动作
-> ESP32S3 转发
-> STM32 执行 OLED / RGB / 风扇 / 蜂鸣器 / SYN6288 TTS / 锁 / ACK
-> ACK 回传后台形成闭环
```

也就是“给 AI 装上胳膊和腿”：大模型不只是聊天，而是能控制真实单片机物理输出。

## What Was Changed In This Window

### STM32

File:

- `firmware/stm32/stm32_executor/stm32_executor.ino`

Key changes:

- OLED 从直白状态文字改成程序化 AI 表情动画：
  - LISTEN：眼睛 + 声波
  - THINK：眼睛左右扫动 + 能量条
  - ACTION：动作/执行脉冲
  - ACK：眨眼/确认
  - ERROR：红灯/错误表情
- 新增 UI 状态命令：

```text
NET:UI:LISTEN
NET:UI:THINK
NET:UI:ACTION
NET:UI:ACK
NET:UI:IDLE
NET:UI:ERROR
```

- `KEY2/PB13` 作为真实物理对话入口。
- 按下 KEY2 后 STM32：
  - 本机进入 LISTEN 表情动画
  - 通过返回链路发送：

```text
BT:BTN:KEY2:SHORT
```

- `NET:UI:DEMO` 仍保留为隐藏硬件自检命令，但已经不再绑定到按键，也不是主展示方案。

### ESP32S3

File:

- `edge/esp32s3/main/main.ino`

Key changes:

- ESP32S3 收到：

```text
BT:BTN:KEY2:SHORT
```

后调用现有真实对话链路：

```cpp
captureAndUploadMic(true, "stm32_key2");
```

- 录音/上传/动作阶段向 STM32 发 UI 动画命令：

```text
NET:UI:LISTEN
NET:UI:THINK
NET:UI:ACTION
NET:UI:ERROR
```

- 后端 WebSocket 收到 `stm32/commands` 或 `speak` 时，会先发 `NET:UI:ACTION`，再转发真实 TTS/动作命令。

### Docs

Updated:

- `firmware/stm32/README.md`
- `edge/esp32s3/README.md`
- `docs/PROTOCOL.md`
- `docs/HARDWARE_WIRING.md`

From the Botelvdong STM32 kit package:

```text
KEY1 = PB12
KEY2 = PB13
KEY3 = PB15
```

Current firmware uses `KEY2/PB13`. Later native-board verification corrected the relay output to `PB5`; `PB12` is `KEY1` and should not be treated as the relay/fan pin.

## Flashed / Verified

STM32 compile:

```powershell
arduino-cli compile --fqbn STMicroelectronics:stm32:GenF1:pnum=BLUEPILL_F103C8 --build-path .tmp\build-stm32 firmware\stm32\stm32_executor
```

Result:

```text
Sketch uses 47156 bytes (71%)
Global variables use 3428 bytes (16%)
```

STM32 flash:

```powershell
openocd.exe -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program .tmp/build-stm32/stm32_executor.ino.elf verify reset exit"
```

Result:

```text
** Programming Finished **
** Verified OK **
** Resetting Target **
```

ESP32S3 compile:

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

Result:

```text
Sketch uses 935849 bytes (27%)
Global variables use 46268 bytes (14%)
```

ESP32S3 upload:

```powershell
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

Result:

```text
Hash of data verified.
Leaving...
Hard resetting via RTS pin...
New upload port: COM8 (serial)
```

## Current Observed Problem

User pressed `KEY2`, said “你好”.

Observed behavior:

```text
KEY2 press works
STM32 enters LISTEN animation
ESP32S3 records audio
After recording, STM32 enters THINK animation
Then STM32 enters ERROR
No model answer
No final TTS / physical action response
```

Important inference:

- KEY2 physical button path is working.
- STM32 -> ESP32S3 button event path is working.
- ESP32S3 microphone recording starts.
- Since UI reaches THINK after recording, capture likely completed and ESP32S3 started upload / backend processing.
- ERROR after THINK most likely comes from `captureAndUploadMic(...)` returning failure after `uploadMicWav(...)`, meaning one of:
  - HTTP upload to `/api/asr/transcribe` failed
  - ASR backend returned `ok=false`
  - backend server URL/WiFi unavailable
  - backend did not inject recognized text into dialogue successfully
  - ASR succeeded but response parse did not set `asrOk=true`

Need fresh serial logs to confirm.

## Most Useful Next Debug Commands

Monitor ESP32S3 serial while pressing KEY2:

```powershell
python tools\serial_console.py COM8 --baud 115200 --monitor --monitor-seconds 90
```

Expected useful log lines:

```text
[STM32 RX] BT:BTN:KEY2:SHORT
[BTN] KEY2 -> mic dialogue
[MIC] recording 6 seconds...
[MIC] captured <bytes> bytes
[MIC] POST /api/asr/transcribe -> <http_code>
[MIC] ASR OK provider=... text=...
```

or failure:

```text
[MIC] ASR FAIL transport=... provider=... error=...
```

Check ESP32S3 local config:

```text
CFG:WIFI:SHOW
```

Check STM32 bridge:

```text
CFG:UART:PING
```

Manual mic path without pressing KEY2:

```text
CFG:MIC:REC
```

ASR-only isolation commands that must be preserved:

```text
CFG:MIC:REC:ASRONLY
CFG:MIC:REC:CUE:ASRONLY
```

## Backend Checks For Next Window

Do not read, print, or modify `backend/.env`.

Check whether backend is running and reachable from ESP32S3 LAN:

```powershell
curl http://127.0.0.1:8083/api/health
```

or whichever port is configured in ESP32S3 via `CFG:SERVER:`.

Useful backend endpoints:

```text
GET /api/health
GET /api/realtime/status
GET /api/realtime/diagnostics/desktop-agent-001
POST /api/asr/transcribe
POST /api/asr/recognized
```

`/api/asr/recognized` must remain as browser speech fallback and should not be removed.

## Likely Next Fix Direction

Do not start with UI changes. The UI already reflects the real failure.

Start by capturing the ESP32S3 serial log for one KEY2 attempt and identify the exact failure point:

1. If `[MIC] WiFi/server not ready`:
   - Fix ESP32S3 `CFG:SERVER:http://<backend-lan-ip>:8083`
   - Confirm WiFi connection.

2. If `[MIC] POST /api/asr/transcribe -> -1`:
   - ESP32S3 cannot reach backend.
   - Check backend host/port/firewall/LAN IP.

3. If HTTP code is non-2xx:
   - Inspect backend ASR endpoint logs.

4. If ASR returns empty/error:
   - Continue ASR endpoint diagnosis, but preserve ASR-only commands.

5. If ASR OK but no model answer/action:
   - Inspect backend inject/dialogue path after `/api/asr/transcribe inject=true`.

## Do Not Do

- Do not continue with local `NET:UI:DEMO` as the main story.
- Do not make KEY2 speak a fixed sentence.
- Do not remove `/api/asr/recognized`.
- Do not remove ESP32S3 ASR-only commands.
- Do not read, print, or modify `backend/.env`.
- Do not frame the project as a simple OLED/TTS demo. The point is AI -> backend -> physical action closed loop.
