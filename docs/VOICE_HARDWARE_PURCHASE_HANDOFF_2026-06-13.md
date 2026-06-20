# Voice Hardware Purchase Handoff - 2026-06-13

## First Instruction To Paste

```text
请先读取 docs/VOICE_HARDWARE_PURCHASE_HANDOFF_2026-06-13.md，然后从“是否购入新硬件解决人机语音沟通问题”的角度继续：当前声音/KEY2/ASR/WiFi 上传问题还没有解决，不能写成已完成；不要读取、打印或修改 backend/.env；保留 /api/asr/recognized、ESP32S3 ASR-only 命令和现有真实语音链路。请先基于文档里的进度、失败点和边界，区分是麦克风采集、WiFi 大包上传、KEY2 触发闭环还是整体语音前端硬件不合适，再给出可采购硬件路线、最小验证方案和不改动现有主链路的接入计划。
```

## Scope

This handoff is for a new window focused on hardware purchase and replacement strategy for the human-machine voice conversation path.

The voice problem is not solved. It is intentionally separated from tonight's sensor work and should be handled as a focused daytime debugging / hardware decision track.

Do not treat `/api/asr/recognized`, fixed text, or a desk-side demo command as proof that KEY2 physical voice interaction works.

## Current Project Goal

The target experience is still:

```text
Physical KEY2 / real user speech
-> STM32 sends BT:BTN:KEY2:SHORT
-> ESP32S3 records real audio
-> backend ASR recognizes speech
-> backend AI/action planning
-> ESP32S3 forwards NET:* commands
-> STM32 executes OLED/RGB/FAN/BEEP/SYN6288/etc
-> STM32 ACK returns to backend
```

The issue is whether the current XIAO ESP32S3 Sense onboard microphone and WiFi upload path are good enough for that experience, or whether buying a more appropriate voice front-end is the better path.

## Hard Boundaries

- Do not read, print, or modify `backend/.env`.
- Keep `POST /api/asr/recognized` as the browser speech fallback.
- Keep these ESP32S3 ASR-only commands:

```text
CFG:MIC:REC:ASRONLY
CFG:MIC:REC:CUE:ASRONLY
```

- Do not use fixed text to pretend KEY2 voice success.
- Do not remove the current ESP32S3/STM32/ASR code while evaluating hardware.
- Do not buy hardware before deciding which failure it is meant to solve.
- Do not frame the project as a local OLED/TTS demo; the main story remains AI -> physical action -> ACK.

## Verified Progress

Backend and downstream action chain have worked:

- PC-side upload of an existing `192044` byte WAV to `/api/asr/transcribe` worked through loopback and LAN.
- Backend local ASR returned `provider=funasr_local` in successful runs.
- Full injected mic path has succeeded at least once:

```text
CFG:MIC:REC:CUE
[MIC] POST /api/asr/transcribe -> 200
[MIC] ASR OK provider=funasr_local text=...
[STM32 TX] NET:CMD:...:NET:TTSHEX:...
[STM32 TX] NET:CMD:...:NET:OLED:...
[STM32 TX] NET:CMD:...:NET:FAN:ON:2
[STM32 RX] BT:ACK:...:OK
```

KEY2 physical entry has also shown useful partial progress:

- `KEY2/PB13` is the intended physical dialogue button.
- STM32 can emit:

```text
BT:BTN:KEY2:SHORT
```

- ESP32S3 code maps that line to:

```cpp
captureAndUploadMic(true, "stm32_key2");
```

Current firmware/code state:

- ESP32S3 records 6 seconds at 16 kHz / 16-bit mono.
- A normal capture is about `192044` bytes.
- 8-second one-shot capture previously hit `[MIC] buffer alloc failed`.
- `/api/asr/transcribe/chunk` and ESP32S3 chunked fallback now exist locally:
  - part size: `8192` bytes
  - fallback starts only after direct upload attempts fail
  - this is a mitigation, not final proof of solved voice hardware.

## Current Unresolved Problems

### 1. WiFi / TCP Large Body Instability

Known failure:

```text
[MIC] upload attempt 2 failed: audio write failed at 91648/192044 rssi=-61 status=3
[MIC] upload attempt 1 failed: audio write failed at 71680/192044 rssi=-72 status=3
[MIC] upload attempt 2 failed: audio write failed at 45056/192044 rssi=-69 status=3
[MIC] upload attempt 3 failed: audio write failed at 5120/192044 rssi=-68 status=3
```

Interpretation:

- Backend can accept the WAV.
- PC upload works.
- ESP32S3 upload sometimes works and sometimes breaks at random offsets.
- This points to wireless/TCP/body upload fragility on the embedded side, not primarily backend parsing.

### 2. Capture Window / Memory Headroom

Known facts:

- 6 seconds is the current practical one-shot capture window.
- 6 seconds can be too short for natural Chinese sentences.
- 8 seconds failed with buffer allocation.

This means simply increasing `MIC_RECORD_SECONDS` is not a safe solution on the current hardware path.

### 3. Audio Quality / Recognition Quality

Observed ASR behavior has included:

- correct short/medium recognition in some controlled runs,
- clipped sentence endings,
- pickup of room noise or previous speech,
- misrecognition when prompt/cue/ambient audio leaks into the recording.

This may be a microphone placement, acoustic front-end, VAD/cue timing, or capture-window issue.

### 4. Physical KEY2 End-to-End Evidence Is Not Yet Stable

Expected success evidence is:

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

This exact physical KEY2 proof remains the goal.

## Hardware Purchase Decision Axes

Do not start by buying random parts. First decide which weak link is being replaced.

| Weak link | Symptom | Purchase direction |
| --- | --- | --- |
| WiFi upload reliability | audio write fails at random offsets | better 2.4 GHz AP / stronger antenna / move voice capture off ESP32S3 |
| Microphone capture quality | truncation, noise, bad recognition | external mic / mic array / voice front-end board |
| One-shot memory limits | 8-second capture allocation failure | streaming-capable front-end / Linux edge device / board with more PSRAM |
| Full embedded voice assistant hardware | current board feels too small for audio UX | ESP32-S3 voice dev kit or Raspberry Pi + mic HAT |
| Fast demo reliability | need reliable speech input quickly | PC/USB mic or Pi/ReSpeaker handles audio; ESP32S3 keeps actuator bridge |

## Candidate Hardware Routes

### Route A: Improve Current XIAO ESP32S3 Sense Setup

Buy only supporting hardware:

- U.FL / IPEX 2.4 GHz antenna for the current XIAO ESP32S3 Sense.
- Better 2.4 GHz router/AP or a close phone hotspot for the demo bench.
- Optional external I2S/PDM microphone module only if wiring/pin conflicts are manageable.

Pros:

- Cheapest.
- Smallest code change.
- Keeps current architecture.

Cons:

- Does not solve one-shot memory/capture-window limits.
- Does not guarantee ASR quality.
- If the root cause is embedded TCP/audio architecture, it only reduces failure probability.

Best first buy only if RSSI and antenna are still suspect.

### Route B: Replace Voice Front-End With ESP32-S3 Voice Dev Kit

Candidate class:

- Espressif ESP32-S3-BOX-3 or similar ESP32-S3 voice assistant dev kit.

Why it fits:

- Designed as an AI voice development kit.
- Has dual microphones, speaker, display, larger flash/PSRAM, and USB-C debug/programming.
- Still close to the existing ESP32-S3 firmware ecosystem.

Pros:

- More voice-specific than XIAO Sense.
- Keeps embedded front-end story.
- Could become the dedicated voice terminal while current ESP32S3/STM32 bridge remains the actuator path during migration.

Cons:

- Requires porting current UART bridge / mic upload code.
- Still uses WiFi if uploading audio to backend.
- Needs real bench validation before replacing current hardware.

Best when the project wants a polished embedded voice device rather than just a quick workaround.

### Route C: Use Raspberry Pi + ReSpeaker / USB Mic As Audio Front-End

Candidate class:

- Raspberry Pi plus ReSpeaker 2-Mics Pi HAT, or a reliable USB conference microphone.

Why it fits:

- Moves recording, VAD, buffering, and ASR upload away from constrained microcontroller RAM.
- Lets Linux/backend tools handle audio more reliably.
- ESP32S3 can remain the WiFi/STM32 actuator bridge, or the Pi can call backend directly.

Pros:

- Strongest route for reliable speech capture.
- Easier long-form recording and streaming.
- Good fit for local FunASR or backend-triggered recording.

Cons:

- Adds another computer/device.
- Less "all embedded on ESP32S3" as a story.
- Requires designing KEY2 -> backend/Pi recording trigger if physical button must remain the entry point.

Best when reliability matters more than keeping all voice work on the XIAO.

### Route D: Compact Voice Module Such As M5Stack ATOM Echo / Atom Voice

Candidate class:

- M5Stack ATOM Echo / Atom Voice style module.

Why it fits:

- Integrated microphone, speaker, button, RGB, WiFi.
- Small and ready-made for simple voice interaction experiments.

Pros:

- Compact, inexpensive, and fast to prototype.
- Has built-in mic/speaker and button.

Cons:

- Smaller flash/RAM class than ESP32-S3 voice kits.
- Still embedded WiFi.
- May not solve long recording or robust ASR upload by itself.

Best as a quick secondary voice input experiment, not necessarily the final main voice brain.

### Route E: Keep Browser / PC Speech As Explicit Fallback Only

Candidate class:

- PC USB microphone or headset.

Pros:

- Fastest way to prove backend AI/action/STM32 ACK remains valuable.
- Can produce a reliable demo fallback.

Cons:

- This does not prove KEY2 physical embedded voice success.
- Must be labeled honestly as browser/PC speech fallback through `/api/asr/recognized`.

Best as a backup demo channel, not as the answer to the KEY2 embedded problem.

## Recommended Purchase Strategy

Preferred order:

1. Buy or test a stronger antenna/AP first if it is cheap and quick, because the current failure logs include RSSI-sensitive WiFi write failures.
2. If the goal is still an embedded voice terminal, evaluate ESP32-S3-BOX-3 or another ESP32-S3 voice kit as the next main voice front-end.
3. If the deadline requires reliable real speech more than embedded purity, move audio capture to Raspberry Pi + ReSpeaker or PC/USB mic while preserving STM32 physical action output.
4. Treat M5Stack ATOM Echo / Atom Voice as a compact experiment, not the safest replacement for the whole pipeline.

Do not buy multiple voice boards before writing a one-page comparison with:

- capture duration,
- microphone count/type,
- speaker need,
- WiFi/USB path,
- available RAM/PSRAM,
- integration cost with current backend,
- whether KEY2 can still trigger the recording.

## Minimum Validation Plan For Any New Hardware

For every candidate board/module:

1. Record a 6-10 second WAV locally.
2. Upload the WAV from PC to `/api/asr/transcribe`.
3. Upload or stream from the candidate hardware to `/api/asr/transcribe`.
4. Confirm backend diagnostics:

```text
last_audio_bytes > 0
last_asr_ok=true
last_asr_provider=funasr_local
last_asr_text=<fresh user speech>
```

5. Trigger a real action command:

```text
请把风扇打开到二档
```

6. Confirm STM32 ACK:

```text
BT:ACK:<action_id>:OK
```

Only after those steps should the project call the new voice hardware viable.

## Useful Current Commands

Do not inspect `backend/.env`.

Backend:

```powershell
curl.exe --noproxy "*" http://127.0.0.1:8083/api/health
curl.exe --noproxy "*" http://127.0.0.1:8083/api/realtime/diagnostics/desktop-agent-001
```

ASR-only isolation:

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 25 --line "CFG:MIC:REC:CUE:ASRONLY" --monitor --monitor-seconds 300
python tools\serial_console.py COM8 --baud 115200 --open-delay 25 --line "CFG:MIC:REC:ASRONLY" --monitor --monitor-seconds 300
```

Full injected mic path:

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 25 --line "CFG:MIC:REC:CUE" --monitor --monitor-seconds 360
```

Physical KEY2 monitor:

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 20 --monitor --monitor-seconds 300
```

Current firmware compile checks:

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
python -m pytest backend\tests\test_asr_local.py backend\tests\test_phase1.py -q
```

## Files To Read First

```text
docs/KEY2_DIALOGUE_ERROR_HANDOFF_2026-06-12.md
docs/KEY2_WIFI_UPLOAD_STABILITY_HANDOFF_2026-06-12.md
docs/ASR_NEXT_WINDOW_TEST_HANDOFF_2026-06-12.md
docs/LOCAL_ASR_FUNASR.md
edge/esp32s3/main/main.ino
backend/app/main.py
backend/app/asr.py
```

Do not read `backend/.env`.

## External Hardware References Checked

Use these as starting points only; verify local price, availability, and shipping before purchase.

- Seeed XIAO ESP32S3 Sense official wiki: digital microphone, 8MB PSRAM/flash, 2.4 GHz WiFi, U.FL antenna support.
  - https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/
  - https://wiki.seeedstudio.com/xiao_esp32s3_wifi_usage/
- Espressif ESP32-S3-BOX-3 component page: ESP32-S3 voice dev kit with dual microphone, speaker, display, 16MB flash and 16MB PSRAM.
  - https://components.espressif.com/components/espressif/esp-box-3/versions/3.0.0~1
- Seeed ReSpeaker 2-Mics Pi HAT wiki: Raspberry Pi-compatible dual-mic board with WM8960 codec, user button, audio output, and 48 kHz max sample rate.
  - https://wiki.seeedstudio.com/ReSpeaker_2_Mics_Pi_HAT/
- M5Stack Atom Voice / Echo docs: compact ESP32-based module with integrated mic, speaker, RGB LED, button, and WiFi.
  - https://docs.m5stack.com/en/atom/atomecho

## Success Criteria For The Purchase Window

The new window is successful when it produces one of these:

1. A short, justified buy/no-buy decision for current hardware plus antenna/AP only.
2. A selected replacement voice front-end with wiring/integration plan.
3. A clear fallback route using PC/Pi audio that is honestly labeled as fallback, not KEY2 embedded voice success.
4. A minimal experiment checklist that can be run immediately after the hardware arrives.

It is not successful if it merely says "buy a better mic" without tying the part to a specific failure mode.
