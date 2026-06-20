# Laptop Mic Wake Word Handoff - 2026-06-13

## First Instruction To Paste

```text
请先读取 docs/LAPTOP_MIC_WAKEWORD_HANDOFF_2026-06-13.md，然后从“笔记本内置麦克风作为临时语音前端/热词入口”的新思路继续。当前 ESP32S3 声音采集、KEY2 物理闭环、ASR 稳定性和 WiFi 大包上传问题仍然没有解决，不能写成已完成；不要读取、打印或修改 backend/.env；保留 /api/asr/recognized、ESP32S3 ASR-only 命令和现有真实语音链路。先不要改主工程文件，先设计旁路验证方案：笔记本实时监听热词或 KEY2 串口触发后使用内置麦克风录音，再进入现有后端 ASR/AI/action/STM32 ACK 链路。
```

## Purpose

This handoff captures the new fallback/demo direction:

```text
laptop built-in microphone
-> wake word or KEY2 serial trigger
-> laptop records real user speech
-> backend ASR / recognized-text fallback
-> backend AI/action planning
-> ESP32S3 / STM32 actuator path
-> STM32 ACK
```

The goal is to get a reliable human-machine voice interaction path for the defense/demo while keeping the existing embedded voice work intact.

Engineering note: this document records the real technical route as a desktop/laptop voice front-end. Do not mark the ESP32S3 microphone path as solved until it has separate physical evidence.

## Hard Boundaries

- Do not read, print, or modify `backend/.env`.
- Do not delete or weaken the current ESP32S3 microphone / STM32 / backend ASR code.
- Keep `POST /api/asr/recognized` as the browser speech fallback.
- Keep the ESP32S3 ASR-only commands:

```text
CFG:MIC:REC:ASRONLY
CFG:MIC:REC:CUE:ASRONLY
```

- Do not use fixed text as proof of real voice success.
- Do not claim the unresolved ESP32S3 microphone path is complete.
- The main project story remains AI -> physical action -> STM32 ACK, not a local OLED/TTS-only demo.

## Current Situation

The previous hardware-purchase window concluded that the voice issue is not a single clean failure:

- ESP32S3 large WAV upload over WiFi is unstable.
- XIAO ESP32S3 Sense has limited one-shot recording headroom.
- 6-second captures can clip natural Chinese speech.
- Ambient sound, cue sound, or previous speech can leak into ASR.
- The exact physical KEY2 -> recording -> ASR -> action -> ACK proof is still not stable.

However, the downstream path has useful verified progress:

- Backend can accept WAV uploads.
- Local ASR has returned `provider=funasr_local`.
- Injected mic path has reached backend ASR and physical STM32 actions at least once.
- STM32 can emit `BT:BTN:KEY2:SHORT`.
- ESP32S3 firmware maps KEY2 to mic dialogue logic.

Therefore the new idea is to move only the voice capture/front-end responsibility to the laptop during demo work, while preserving the backend and hardware action chain.

## New Architecture Options

### Option A: Laptop Wake Word Front-End

```text
Laptop mic continuously listens
-> wake word detected
-> enter LISTEN state
-> record command speech
-> upload WAV to /api/asr/transcribe
-> backend plans action
-> existing ESP32S3/STM32 path executes
-> ACK returns
```

Recommended wake phrase style:

- Prefer 4-6 Chinese characters.
- Avoid very short names such as only "小智".
- Avoid using an actual action command as the wake word.
- Candidate examples: "你好小智", "小智同学", "开始对话".

Expected quality:

- Much more reliable than ESP32S3 continuous listening.
- Better memory, buffering, and upload stability.
- Still sensitive to classroom noise and echo.

### Option B: KEY2 Triggers Laptop Recording

```text
Physical KEY2 press
-> STM32 emits BT:BTN:KEY2:SHORT
-> laptop-side bridge watches serial
-> laptop records real speech
-> /api/asr/transcribe
-> backend action chain
-> STM32 ACK
```

This keeps KEY2 as the real physical entry point while moving only microphone capture to the laptop. This is the most natural bridge between the old KEY2 goal and the new reliable microphone route.

Potential issue:

- The laptop process and existing serial tools must not fight over the same COM port.
- The bridge should be treated as a sidecar, not a replacement for existing firmware.

### Option C: Browser Speech Fallback

```text
Browser / desktop speech recognition
-> POST /api/asr/recognized
-> backend action chain
-> STM32 ACK
```

This is the fastest fallback and should remain available, but it is less close to the real WAV/ASR path than Option A or B.

## Recommended Direction

Use a two-stage plan:

1. Start with laptop mic recording to `/api/asr/transcribe`.
2. Add either wake word detection or KEY2 serial trigger as the entry condition.

Preferred order:

```text
Manual laptop recording smoke test
-> laptop mic /api/asr/transcribe test
-> KEY2-triggered laptop recording
-> wake word-triggered laptop recording
-> final demo script
```

The safest defense/demo path is:

```text
KEY2 physical trigger + laptop mic capture + existing backend + existing STM32 ACK
```

The most natural "voice assistant" path is:

```text
laptop wake word + laptop mic capture + existing backend + existing STM32 ACK
```

## Wake Word State Machine

Use a clear state machine to avoid echo loops and false triggers:

```text
IDLE
  continuous wake-word listening

WAKE_DETECTED
  stop wake listening briefly
  show/send NET:UI:LISTEN if available

LISTEN
  record command speech
  stop by VAD silence or max duration

ASR
  upload WAV or recognized text

THINK
  backend plans action

EXECUTE
  ESP32S3/STM32 execute physical command

SPEAKING_OR_FEEDBACK
  pause wake detection while TTS/beep/device feedback may leak into mic

COOLDOWN
  short delay
  return to IDLE
```

Important: wake detection should pause while the system is speaking or beeping, otherwise the laptop mic may capture its own feedback and trigger another round.

## Minimal Validation Plan

Do not modify the main project first. Validate the idea as a sidecar.

### Phase 1: Laptop Mic ASR Smoke Test

Goal:

```text
laptop mic real speech -> /api/asr/transcribe -> fresh ASR text
```

Pass criteria:

- Recognized text must be fresh user speech.
- No fixed text.
- No browser recognized-text fallback unless explicitly testing Option C.
- Backend diagnostics should show non-empty audio and successful ASR.

### Phase 2: Action Chain

Goal:

```text
laptop mic command -> backend AI/action planning -> STM32 action -> ACK
```

Example command:

```text
请把风扇打开到二档
```

Pass criteria:

- Backend emits a physical action command.
- STM32 executes.
- ACK returns as `BT:ACK:<action_id>:OK`.

### Phase 3: KEY2 Trigger Sidecar

Goal:

```text
real KEY2 press -> laptop records -> ASR -> action -> ACK
```

Pass criteria:

- Serial log includes `BT:BTN:KEY2:SHORT`.
- Recording starts only after the physical KEY2 event.
- Final action and ACK are real.

### Phase 4: Wake Word Soak Test

Goal:

```text
10 minutes idle listening + repeated wake/command cycles
```

Pass criteria:

- No more than one false wake in 10 minutes of normal room noise.
- Wake response starts within about 1 second after the phrase.
- At least 8/10 wake attempts enter command recording.
- At least 8/10 command recordings produce usable ASR text.

## Demo Risks

### Ambient Noise

Laptop microphones pick up classroom echo, teacher speech, keyboard noise, and device feedback. Use a wake phrase that is not too short, and keep the laptop close to the speaker.

### Audio Feedback

If the system uses SYN6288, beep, speaker, or laptop audio output, pause wake listening during feedback. Otherwise TTS may be captured as a new command.

### Serial Port Contention

Only one process can usually own the COM port. The new sidecar should not run at the same time as another serial monitor unless the architecture explicitly supports it.

### Demo Honesty In Engineering Records

Keep internal docs and code comments accurate: the laptop is the temporary voice front-end. The ESP32S3 microphone path remains a separate unresolved track.

## What Not To Do

- Do not hard-code a command result to create fake success.
- Do not remove `/api/asr/recognized`.
- Do not remove ESP32S3 ASR-only commands.
- Do not rewrite the backend around the laptop path.
- Do not label browser/PC speech fallback as proof that ESP32S3 onboard mic is stable.
- Do not buy new voice hardware before this laptop-mic route is tested.

## Files Likely Relevant Later

Read only when implementation begins:

```text
tools/serial_console.py
backend/app/main.py
backend/app/asr.py
edge/esp32s3/main/main.ino
docs/VOICE_HARDWARE_PURCHASE_HANDOFF_2026-06-13.md
docs/KEY2_DIALOGUE_ERROR_HANDOFF_2026-06-12.md
docs/KEY2_WIFI_UPLOAD_STABILITY_HANDOFF_2026-06-12.md
```

Do not read `backend/.env`.

## Success Criteria For The Next Window

The next window is successful if it produces one of these:

1. A sidecar design for laptop mic -> ASR -> existing action chain.
2. A KEY2-triggered laptop recording plan that does not modify the main firmware.
3. A wake-word listener plan with state machine, false-wake handling, and feedback suppression.
4. A minimal test script/checklist that can prove real speech -> real action -> real ACK.

It is not successful if it claims ESP32S3 onboard microphone voice interaction is solved without separate physical evidence.
