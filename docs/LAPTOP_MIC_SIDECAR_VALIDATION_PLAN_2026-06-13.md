# Laptop Mic Sidecar Validation Plan - 2026-06-13

## Boundary

This is a temporary desktop/laptop voice front-end validation route.

Do not treat this as proof that the ESP32S3 onboard microphone path is solved. The current unresolved items remain:

- ESP32S3 voice capture stability
- KEY2 physical closed loop stability
- ASR stability for embedded recordings
- ESP32S3 WiFi large audio upload stability

Do not read, print, or modify `backend/.env`.

Keep these existing routes intact:

- `POST /api/asr/recognized`
- `POST /api/asr/transcribe`
- ESP32S3 ASR-only commands:

```text
CFG:MIC:REC:ASRONLY
CFG:MIC:REC:CUE:ASRONLY
```

## Sidecar Route

```text
laptop built-in microphone
-> record real WAV
-> POST /api/asr/transcribe
-> optional inject=true
-> backend AI/action planning
-> existing ESP32S3/STM32 actuator path
-> STM32 ACK
```

The sidecar added in this window is:

```text
tools/laptop_mic_sidecar.py
```

It does not change backend, ESP32S3, or STM32 code.

## Install Sidecar Dependencies

Use the same Python environment you normally use for tools, or install only the sidecar dependencies:

```powershell
python -m pip install -r tools\requirements.txt
```

If `sounddevice` cannot find an input device, list devices:

```powershell
python tools\laptop_mic_sidecar.py --list-devices
```

Then pass a device index:

```powershell
python tools\laptop_mic_sidecar.py --input-device 1
```

## Phase 1: Manual Laptop Mic ASR

Goal:

```text
real laptop microphone speech -> WAV -> /api/asr/transcribe -> fresh ASR text
```

Start backend first, for example:

```powershell
.\tools\start_backend_funasr.ps1 -Profile sensevoice
```

Then run:

```powershell
python tools\laptop_mic_sidecar.py --base-url http://127.0.0.1:8083 --record-seconds 6 --pre-delay 5 --cue-beep
```

Speak a fresh sentence during the 6-second window.

Pass criteria:

- Output `asr.ok=true`.
- Output `asr.text` is the fresh sentence or a close ASR result.
- Output `audio.bytes` is non-zero.
- Output `audio.rms` is clearly above silence.
- No fixed text is used.
- `inject` remains false in this phase.

## Phase 2: Manual Laptop Mic To Action Chain

Goal:

```text
real laptop microphone command
-> ASR
-> backend AI/action planning
-> existing ESP32S3/STM32 chain
-> ACK
```

Run:

```powershell
python tools\laptop_mic_sidecar.py --base-url http://127.0.0.1:8083 --record-seconds 6 --pre-delay 5 --cue-beep --inject
```

Suggested command:

```text
请把风扇打开到二档
```

Pass criteria:

- Output `asr.text` is fresh real speech.
- Output `actions.created` contains backend-created action ids.
- Existing ESP32S3 bridge receives the commands and forwards them to STM32.
- Output `actions.last_ack.line` eventually looks like:

```text
BT:ACK:<action_id>:OK
```

If `pending_action_count_after` stays above zero, the ASR/backend side may have worked, but the ESP32S3/STM32 command/ACK side was not connected or did not finish.

## Phase 3: KEY2-Triggered Laptop Recording

Goal:

```text
real KEY2 press -> sidecar sees BT:BTN:KEY2:SHORT -> laptop records -> ASR -> optional action/ACK
```

Run with the STM32/bridge serial port that emits `BT:BTN:KEY2:SHORT`:

```powershell
python tools\laptop_mic_sidecar.py --trigger key2 --port COM8 --base-url http://127.0.0.1:8083 --record-seconds 6 --cue-beep
```

For the full action chain:

```powershell
python tools\laptop_mic_sidecar.py --trigger key2 --port COM8 --base-url http://127.0.0.1:8083 --record-seconds 6 --cue-beep --inject
```

Pass criteria:

- Serial output includes the real line:

```text
BT:BTN:KEY2:SHORT
```

- Recording starts only after that line.
- ASR text is fresh speech.
- With `--inject`, backend creates actions and STM32 ACK returns.

Risk:

Only one process can usually own a COM port. Close other serial monitors if the sidecar cannot open the port.

## Phase 4: Wake Word Sidecar

Do not fake wake-word success with fixed text.

Implemented sidecar:

```text
tools/laptop_wakeword_sidecar.py
```

Route:

```text
short laptop-mic wake windows
-> POST /api/asr/transcribe with inject=false
-> wake phrase match
-> explicit recording warning + cue/pre-delay
-> laptop-mic command WAV
-> POST /api/asr/transcribe with inject=true by default
-> backend AI/action planning
-> existing ESP32S3/STM32 command and ACK chain
-> cooldown
-> resume wake listener
```

Default wake phrases:

```text
灵宝灵宝
你好灵宝
在吗灵宝
```

One-cycle demo command:

```powershell
python tools\laptop_wakeword_sidecar.py --base-url http://127.0.0.1:8083 --device-id desktop-agent-001 --input-device 1 --sample-rate 16000 --channels 1 --wake-window-seconds 2.5 --record-seconds 5 --pre-delay 3 --once --wait-ack-seconds 20
```

ASR-only wake-command check, without entering Qwen/action/ACK:

```powershell
python tools\laptop_wakeword_sidecar.py --base-url http://127.0.0.1:8083 --input-device 1 --once --no-inject
```

The script prints a privacy warning before wake listening begins. It also prints a second explicit warning before command recording starts after the wake phrase. The command summary includes this reminder:

```text
This sidecar proves the laptop microphone temporary wake-word front-end only; it does not prove the ESP32S3 onboard microphone path.
```

Additional candidate wake phrases:

- 你好小智
- 小智同学
- 开始对话

State machine:

```text
IDLE
WAKE_DETECTED
LISTEN
ASR
THINK
EXECUTE
SPEAKING_OR_FEEDBACK
COOLDOWN
IDLE
```

Important rule:

Pause wake detection during TTS, beeps, and visible feedback. Otherwise the laptop microphone may hear the device or speaker and trigger another loop.

Soak criteria before demo use:

- 10 minutes idle listening.
- No more than one false wake in normal room noise.
- At least 8/10 wake attempts enter recording.
- At least 8/10 command recordings produce useful ASR text.

## Evidence To Save

For each real pass, save:

- sidecar JSON output
- backend console or diagnostics screenshot
- serial log showing `BT:BTN:KEY2:SHORT` for KEY2 tests
- serial or backend diagnostics showing `BT:ACK:<action_id>:OK` for action-chain tests
- the local WAV path printed under `audio.path`

These prove the laptop-mic sidecar route only. Keep ESP32S3 onboard microphone progress recorded separately.

## Phase 5: Open-And-Listen Realtime Listener

Implemented executable:

```text
dist/laptop_realtime_listener.exe
```

Fallback double-click launcher:

```text
tools/start_laptop_realtime_listener.cmd
```

Behavior:

```text
open executable
-> silent laptop-mic voice activity listening
-> user speaks one utterance
-> save real WAV
-> POST /api/asr/transcribe with inject=false
-> drop the result if it matches the previous device feedback speech
-> inject non-echo ASR text into Qwen
-> existing ESP32S3/STM32 ACK chain
-> wait for backend pending actions to clear
-> hold a dynamic feedback guard based on TTS text length
-> cooldown
-> return to listening for the next turn
```

The listener does not play cue beeps or app sounds. Its console dashboard shows script status, backend cloud status, device/ACK status, current microphone RMS, last ASR text, last ACK, and the latest WAV path.

Lighting and latency:

- `LISTENING` / `RECORDING` sends `NET:UI:LISTEN`; STM32 shows blue.
- Qwen/action/output/feedback guard sends `NET:UI:OUTPUT`; STM32 shows green.
- The console prints `last timing` and each turn summary includes `timing_ms` with capture, ASR, Qwen injection, ACK wait, and total-to-ACK timing.
- Default recording stop is now faster: start after about 160 ms above threshold, stop after about 600 ms silence, hard stop at 7 seconds.

It cannot do true speaker identification from the laptop microphone alone. Instead, it avoids self-triggering by using backend action/ACK logs plus a text echo filter:

- Do not listen while `pending_action_count` is above 0.
- After ACKs, stay in `FEEDBACK_GUARD` for an estimated TTS playback window.
- If the next ASR text is too similar to the previous device feedback speech, show `ECHO_IGNORED` and do not inject it into Qwen.

This is still the laptop microphone temporary front-end only. It does not prove the ESP32S3 onboard microphone capture path is fixed.
