# KEY2 WiFi Upload Stability Handoff - 2026-06-12

## First Instruction To Paste

```text
请先读取 docs/KEY2_WIFI_UPLOAD_STABILITY_HANDOFF_2026-06-12.md，然后继续排查 KEY2 物理按键触发真实人机智能对话链路的剩余问题：KEY2 已能触发录音，后端 ASR/动作规划/STM32 执行链路已被验证跑通过，但当前 ESP32S3 上传 192044 字节 WAV 到 /api/asr/transcribe 时会在 WiFiClient 写音频正文中途随机断开，导致 STM32 进入 ERROR。不要读取、打印或修改 backend/.env；保留现有 /api/asr/recognized 和 ESP32S3 ASR-only 测试命令，不要用固定文本或 /api/asr/recognized 假装 KEY2 成功。
```

## Current Goal

继续让真实物理链路稳定闭环：

```text
KEY2 -> STM32 -> ESP32S3 mic recording
-> POST /api/asr/transcribe
-> FunASR local ASR
-> backend AI/action planning
-> ESP32S3 forwards NET:* commands
-> STM32 executes TTS/OLED/FAN/etc
-> ACK back to backend
```

当前不是要做本地固定回复，也不是要绕过真实录音上传。目标是让 KEY2 的真实 192044 字节 WAV 上传稳定通过。

## Hard Constraints

- Do not read, print, or modify `backend/.env`.
- Keep browser fallback endpoint `POST /api/asr/recognized`.
- Keep ESP32S3 ASR-only commands:

```text
CFG:MIC:REC:ASRONLY
CFG:MIC:REC:CUE:ASRONLY
```

- Do not replace KEY2 with a fixed sentence.
- Do not fake success by sending recognized text to `/api/asr/recognized`.
- Do not reintroduce the untested HTTPClient stream fallback as the default upload path.

## Verified Success In This Window

Backend was reachable:

```powershell
curl.exe --noproxy "*" http://192.168.0.39:8083/api/health
```

PC-side upload of an existing 192044-byte WAV to `/api/asr/transcribe` worked through both loopback and LAN address, returning `provider=funasr_local`.

ASR-only with cue succeeded once:

```text
CFG:MIC:REC:CUE:ASRONLY
[MIC] POST /api/asr/transcribe -> 200
[MIC] ASR OK provider=funasr_local text=怎么样啊？你好不好呀？
```

Full injected mic path succeeded once:

```text
CFG:MIC:REC:CUE
[MIC] POST /api/asr/transcribe -> 200
[MIC] ASR OK provider=funasr_local text=一帮，我把风扇打开到二档。
[STM32 TX] NET:CMD:...:NET:TTSHEX:...
[STM32 TX] NET:CMD:...:NET:OLED:FAN ON
[STM32 TX] NET:CMD:...:NET:FAN:ON:2
[STM32 RX] BT:ACK:act_21abc591409c:OK
```

Backend diagnostics after the successful run showed:

```text
last_asr_text = 一帮，我把风扇打开到二档。
last_assistant = 好的，已将风扇调至二档。
last_speech = 风扇已调到二档。
fan action NET:FAN:ON:2 acked
```

This proves the backend ASR, action planning, ESP32S3 command forwarding, STM32 fan action, and ACK loop can work.

## Current Failure

User later pressed KEY2 and said:

```text
今天天气怎么样，帮我打开风扇
```

KEY2 did trigger recording/upload, but upload did not complete. Serial captured:

```text
[MIC] upload attempt 2 failed: audio write failed at 91648/192044 rssi=-61 status=3
```

After that, backend had no new audio file and diagnostics still pointed to the earlier successful audio:

```text
backend/data/audio latest = 20260612-104725-041f2277ae.wav
last_asr_text still = 一帮，我把风扇打开到二档。
```

So the latest KEY2 utterance did not reach backend ASR.

After reverting experimental wait logic and restoring the safer upload behavior, another ASR-only retest still failed at random audio offsets:

```text
[MIC] upload attempt 1 failed: audio write failed at 71680/192044 rssi=-72 status=3
[MIC] upload attempt 2 failed: audio write failed at 45056/192044 rssi=-69 status=3
[MIC] upload attempt 3 failed: audio write failed at 5120/192044 rssi=-68 status=3
[MIC] ASR FAIL transport=bad provider= error=audio write failed at 5120/192044 rssi=-68 status=3
```

This points to ESP32S3 WiFi/TCP large-payload instability, not ASR parsing or backend action planning.

## ESP32S3 Current Flashed State

File:

```text
edge/esp32s3/main/main.ino
```

Important current state:

- `MIC_RECORD_SECONDS = 6`
- WAV size remains about `192044` bytes.
- Upload chunk pacing is back to the version that previously completed the full chain:

```cpp
static const size_t MIC_UPLOAD_CHUNK_SIZE = 512;
static const uint8_t MIC_UPLOAD_INTER_CHUNK_DELAY_MS = 2;
```

- `writeAllToClient(...)` logs exact failure offsets:

```text
audio write failed at <written>/<expected> rssi=<RSSI> status=<WiFi.status>
```

- `WiFi.setSleep(false)` is present.
- `WiFi.setTxPower(WIFI_POWER_19_5dBm)` is present.
- Target SSID scan/BSSID/channel logging is present.
- WebSocket is paused during mic upload and restarted afterward.
- On inject success, ESP32S3 fetches `/api/hardware/commands/<DEVICE_ID>` and forwards returned STM32 commands.
- HTTPClient stream fallback was removed and should stay removed unless the next window deliberately chooses a new upload implementation.

Last compile and upload after reverting the bad wait logic succeeded:

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

## Important Reverted Experiment

An experiment was tried to wait when:

```cpp
client.availableForWrite() == 0
```

It made things worse. Upload failed at the prefix before any bytes were written:

```text
prefix write failed at 0/590
```

This was reverted. Do not re-add that exact wait logic without a more careful Arduino-ESP32 WiFiClient test.

## Backend Current State

Do not inspect `backend/.env`.

Useful checks:

```powershell
curl.exe --noproxy "*" http://127.0.0.1:8083/api/health
curl.exe --noproxy "*" http://127.0.0.1:8083/api/realtime/diagnostics/desktop-agent-001
Get-ChildItem backend\data\audio -File | Sort-Object LastWriteTime -Descending | Select-Object -First 5 LastWriteTime,Length,Name
```

The backend action priority fix is present in `backend/app/ai.py`: greeting replies only short-circuit when there is no action intent. This prevents utterances containing both "你好" and fan intent from being treated as pure greetings.

Relevant logic:

```text
has_action_intent = ...
if not has_action_intent and greeting:
    return greeting
```

## Most Useful Next Tests

Start with ASR-only, not KEY2 full chain:

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 25 --line "CFG:MIC:REC:CUE:ASRONLY" --monitor --monitor-seconds 300
```

Expected success:

```text
[MIC] captured 192044 bytes
[MIC] POST /api/asr/transcribe -> 200
[MIC] ASR OK provider=funasr_local text=...
```

If ASR-only succeeds twice in a row, test full injected mic:

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 25 --line "CFG:MIC:REC:CUE" --monitor --monitor-seconds 360
```

Then test physical KEY2:

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 20 --monitor --monitor-seconds 300
```

Expected KEY2 evidence:

```text
[STM32 RX] BT:BTN:KEY2:SHORT
[BTN] KEY2 -> mic dialogue
[STM32 TX] NET:UI:LISTEN
[MIC] recording 6 seconds...
[STM32 TX] NET:UI:THINK
[MIC] POST /api/asr/transcribe -> 200
[MIC] ASR OK provider=funasr_local text=...
[STM32 TX] NET:CMD:...NET:FAN:ON:...
[STM32 RX] BT:ACK:...:OK
```

## Strong Suspicions

The remaining instability is WiFi/TCP large-body upload from ESP32S3 to backend, not backend recognition.

Evidence:

- PC can upload the same 192044-byte WAV successfully.
- ESP32S3 sometimes uploads successfully, but often fails at random offsets.
- Failure offsets vary widely: `91648`, `71680`, `45056`, `5120`, etc.
- RSSI during failures was often around `-68` to `-78`; previous full success was around `-61` to `-63`.
- Heartbeat/telemetry also intermittently shows `-1` and `-11`.

Physical/network recommendations before major code changes:

- Check XIAO ESP32S3 antenna/U.FL connection.
- Move ESP32S3 closer to router or use a stronger 2.4 GHz AP/phone hotspot.
- Keep RSSI around `-60 dBm` or better during upload if possible.
- Retest ASR-only after each physical/network change.

## Possible Future Code Direction

Only consider after confirming physical WiFi placement cannot solve it:

1. Keep `/api/asr/transcribe` compatible.
2. Add a separate streaming/chunked upload path or smaller audio chunks.
3. Avoid replacing the working browser fallback `/api/asr/recognized`.
4. Avoid changing backend `.env`.
5. Keep ASR-only commands as the primary isolation test.

Do not start by redesigning the whole dialogue path. The dialogue path already worked; the remaining problem is robustly delivering the WAV payload.
