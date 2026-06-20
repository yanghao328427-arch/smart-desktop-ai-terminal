# Wake Word Design Handoff

Date: 2026-06-13

## New Window First Instruction

请先读取 `docs/WAKEWORD_DESIGN_HANDOFF_2026-06-13.md` 和 `docs/LAPTOP_MIC_WAKEWORD_HANDOFF_2026-06-13.md`，然后在不读取、打印或修改 `backend/.env` 的前提下，设计并实现“笔记本内置麦克风作为临时唤醒词前端”的功能：唤醒词触发后录音，进入现有 `/api/asr/transcribe -> Qwen -> ESP32S3/STM32 ACK` 链路；开始录音前必须明确提醒我；不要把它写成 ESP32S3 板载麦克风问题已解决。

## Current System State

The current reliable demo path is:

```text
laptop built-in microphone
-> backend /api/asr/transcribe
-> DashScope Paraformer ASR
-> Qwen dialogue/action planning
-> ESP32S3 bridge
-> STM32 executor
-> physical hardware action + ACK
```

This proves the laptop microphone sidecar path only. It does not prove that the ESP32S3 onboard microphone capture or WiFi large audio upload path is fixed.

## Hard Constraints

- Do not read, print, modify, or leak `backend/.env`.
- Preserve `/api/asr/recognized`.
- Preserve ESP32S3 ASR-only test commands.
- Preserve existing real voice and hardware ACK paths.
- Do not claim ESP32S3 onboard mic voice interaction is solved unless separately verified on that hardware path.
- Before any recording starts, clearly warn the user that recording is about to begin.

## Completed In This Phase

### Laptop Mic Sidecar

File:

```text
tools/laptop_mic_sidecar.py
```

Capabilities:

- Records laptop microphone audio with `sounddevice`.
- Uploads WAV to `/api/asr/transcribe`.
- Optional `--inject` continues from ASR text into the existing AI/action/STM32 chain.
- Supports `--cue-beep` and `--pre-delay`; use these for user recording reminders.
- Current working input device during tests: `--input-device 1`.

Known working command shape:

```powershell
python tools\laptop_mic_sidecar.py --base-url http://127.0.0.1:8083 --device-id desktop-agent-001 --trigger manual --record-seconds 5 --pre-delay 3 --cue-beep --sample-rate 16000 --channels 1 --input-device 1 --inject --wait-ack-seconds 20 --source <source_name>
```

### Voice Dialogue And Hardware Commands

Successful voice examples through laptop mic:

```text
ASR text=请把风扇打开到2档。
TTS=acked
OLED=acked
NET:FAN:ON:2=acked
pending_action_count=0
```

```text
ASR text=请关闭风扇。
OLED=acked
NET:FAN:OFF=acked
pending_action_count=0
```

One voice OFF batch had a TTS-only ERR. The physical fan OFF command ACKed and the fan was shut down, so treat that as a SYN6288/TTS side issue, not a fan-control failure.

Status dialogue also worked:

```text
ASR text=现在状态怎么样？
TTS=acked
OLED=acked
pending_action_count=0
```

### DRV8833 Fan Correction

The physical fan is wired to the Botelvdong DRV8833 port, not the `PB5` relay output.

Current STM32 direction:

```text
NET:FAN:ON:<1-3> -> PA1/TIM2_CH2 PWM, PA0/TIM2_CH1 LOW
NET:FAN:OFF      -> PA0 LOW, PA1 LOW
```

This direction was chosen because the first PA0-PWM attempt made the fan spin in reverse.

Direct and backend validations passed:

```text
NET:FAN:ON:2 -> BT:OK / BT:ACK:...:OK
NET:FAN:OFF  -> BT:OK / BT:ACK:...:OK
```

### STM32 Telemetry Quiet Guard

The STM32 firmware now delays periodic long telemetry JSON if ESP command input is active. This fixed a case where long `BT:{...}` telemetry could collide with a following `NET:CMD` and truncate an ESP32S3 -> STM32 command.

Key symbol:

```text
TELEMETRY_ESP_QUIET_MS = 3000
```

### Passive Buzzer Music

Added passive buzzer melody playback on `PB9`.

Protocol:

```text
NET:MUSIC:SUCCESS
NET:MUSIC:ALERT
NET:MUSIC:SCALE
NET:MUSIC:STARTUP
NET:MUSIC:BIRTHDAY
NET:MUSIC:STOP
NET:MUSIC:LIST?
```

Backend action:

```json
{"type":"buzzer_music","payload":{"preset":"birthday"}}
```

Direct hardware validation:

```text
NET:MUSIC:LIST?    -> BT:MUSIC:LIST:SUCCESS,ALERT,SCALE,STARTUP,BIRTHDAY + BT:OK
NET:MUSIC:SUCCESS  -> BT:OK
NET:MUSIC:STOP     -> BT:OK
```

Design doc:

```text
docs/BUZZER_MUSIC_DESIGN_2026-06-13.md
```

## Current Runtime Baseline

Backend:

```text
http://127.0.0.1:8083
cloud_ready=true
ai_provider=dashscope_openai
ai_model=qwen-plus
```

Serial ports observed:

```text
STM32 USB debug: COM7
ESP32S3 USB debug: COM8
```

Latest clean post-restart diagnostics after buzzer work:

```text
online=true
uart_ok=true
session_connected=true
state=idle
pending_action_count=0
```

## Verification Already Run

Backend tests:

```powershell
python -m pytest backend\tests\test_actions_protocol.py backend\tests\test_phase1.py -q
```

Result:

```text
32 passed, 1 warning
```

STM32 compile:

```powershell
arduino-cli compile --fqbn STMicroelectronics:stm32:GenF1:pnum=BLUEPILL_F103C8 --build-path .tmp\build-stm32 firmware\stm32\stm32_executor
```

Result:

```text
Sketch uses 55404 bytes (84%) of program storage space.
Global variables use 3556 bytes (17%) of dynamic memory.
```

STM32 flash:

```powershell
openocd.exe -f interface/stlink.cfg -f target/stm32f1x.cfg -c "program .tmp/build-stm32/stm32_executor.ino.elf verify reset exit"
```

Result:

```text
** Verified OK **
```

## Wake Word Design Goal

Design a laptop-side temporary wake-word front-end.

Target behavior:

```text
continuous laptop mic listener
-> wake phrase detected
-> tell user recording is starting
-> short command recording
-> /api/asr/transcribe
-> existing inject path
-> Qwen action planning
-> ESP32S3/STM32 hardware ACK
```

Recommended first wake phrase:

```text
小智小智
```

Fallback trigger:

```text
KEY2 serial event -> laptop mic recording
```

## Suggested Implementation Approach

Start conservative:

1. Keep `tools/laptop_mic_sidecar.py` as the recording/upload primitive.
2. Add a new laptop-side script instead of modifying backend first, for example:

```text
tools/laptop_wakeword_sidecar.py
```

3. For v1, use short rolling recordings plus ASR wake phrase detection, or a lightweight local keyword strategy if a reliable dependency already exists.
4. After wake detection, play cue/print warning, wait a short pre-delay, then record the user command and call the existing sidecar upload/inject flow.
5. Ensure every recording start prints a clear message and preferably plays a cue beep.

Avoid in v1:

- Hotword model training.
- Replacing the existing backend ASR path.
- Claiming embedded wake word on ESP32S3.
- Long-running audio loops that cannot be stopped cleanly.

## Acceptance Criteria For The Next Window

Minimum useful success:

```text
Say wake phrase near laptop
-> script detects wake
-> user is warned recording will begin
-> user says a command
-> ASR text is shown
-> backend creates actions
-> STM32 ACK returns
-> pending_action_count returns to 0
```

A stronger demo:

```text
小智小智
请把风扇打开到二档
-> NET:FAN:ON:2 ACK

小智小智
请关闭风扇
-> NET:FAN:OFF ACK
```

Remember: this is a laptop wake-word front-end for demo reliability. The ESP32S3 onboard mic path remains a separate unresolved embedded-audio task.
