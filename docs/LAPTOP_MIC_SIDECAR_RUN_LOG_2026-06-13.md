# Laptop Mic Sidecar Run Log - 2026-06-13

## Boundary

These tests validate the laptop microphone sidecar only.

They do not prove that the ESP32S3 onboard microphone path is solved.

`backend/.env` was not read, printed, or modified.

## Environment Observed

Backend health:

```json
{
  "status": "ok",
  "protocol": "smart-desktop-realtime-v1",
  "ai_provider": "dashscope_openai",
  "ai_model": "qwen-plus",
  "cloud_ready": true,
  "device_id": "desktop-agent-001",
  "edge_id": "esp32s3-sense-001"
}
```

Backend diagnostics before the laptop-mic action test showed:

```text
online=true
uart_ok=true
session_connected=true
ack_ok_count=7
ack_err_count=0
pending_action_count=0
```

Laptop microphone device used successfully:

```text
input-device 1
本机麦克风 (适用于数字麦克风的英特尔 智音技术), MME
sample_rate=16000
channels=1
```

## Attempt 1: Manual ASR Without Audible Cue

Command:

```powershell
python tools\laptop_mic_sidecar.py --base-url http://127.0.0.1:8083 --device-id desktop-agent-001 --record-seconds 6 --input-device 1 --source laptop_mic_manual_asr
```

Result:

```text
ok=false
audio peak=228
audio rms=19.4
provider=dashscope_paraformer
text=
error=ASR completed without recognized text.
```

Interpretation:

The script and upload path ran, but the recording was effectively too quiet. This was not a backend proof failure; the user had not been given a precise audible start cue.

Local WAV:

```text
.tmp\laptop_mic_sidecar\20260613-160121-laptop_mic_manual_asr.wav
```

Backend WAV:

```text
D:\HuaweiMoveData\Users\35267\Documents\New project2\backend\data\audio\20260613-080128-9647e0e2c4.wav
```

## Attempt 2: WASAPI Device At 16 kHz

Command used input device `9` at `16000` Hz.

Result:

```text
sounddevice.PortAudioError: Invalid sample rate
```

Interpretation:

WASAPI microphone device `9` advertises a default sample rate of `48000`, so the 16 kHz stream cannot be opened directly there.

## Attempt 3: WDM-KS Mic Array 16 kHz

Command used input device `16` at `16000` Hz.

Result:

```text
audio bytes=0
provider=dashscope_paraformer
error=NO_VALID_AUDIO_ERROR
```

Interpretation:

The device opened but produced no PCM frames in this test. Do not use device `16` for the current sidecar path unless separately fixed.

## Attempt 4: Prompted Manual ASR

Audible cue:

```text
Windows speech prompt -> 5 second wait -> beep -> sidecar recording
```

Command:

```powershell
python tools\laptop_mic_sidecar.py --base-url http://127.0.0.1:8083 --device-id desktop-agent-001 --record-seconds 8 --input-device 1 --sample-rate 16000 --source laptop_mic_manual_asr_prompted
```

Result:

```text
ok=true
audio bytes=255424
duration=7.982s
peak=23335
rms=1778.2
provider=dashscope_paraformer
text=麦克风真实录音测试。
```

Local WAV:

```text
.tmp\laptop_mic_sidecar\20260613-160433-laptop_mic_manual_asr_prompted.wav
```

Backend WAV:

```text
D:\HuaweiMoveData\Users\35267\Documents\New project2\backend\data\audio\20260613-080443-9797bc0d3c.wav
```

Pass:

```text
laptop mic real speech -> WAV -> /api/asr/transcribe -> fresh ASR text
```

## Attempt 5: Prompted Manual ASR With Inject

Audible cue:

```text
Windows speech prompt -> 5 second wait -> beep -> sidecar recording
```

Spoken command:

```text
请把风扇打开到二档
```

Command:

```powershell
python tools\laptop_mic_sidecar.py --base-url http://127.0.0.1:8083 --device-id desktop-agent-001 --record-seconds 8 --input-device 1 --sample-rate 16000 --source laptop_mic_manual_action_prompted --inject --wait-ack-seconds 25
```

ASR result:

```text
provider=dashscope_paraformer
text=请把风扇打开到2档。
```

Created actions:

```text
act_ed286a37e1bc  tts_speak     acked
act_3bb315a0a37c  oled_display  acked
act_696ccc610fd7  fan_control   sent
```

ACK counters:

```text
ack_ok_count_before=7
ack_ok_count_after=9
ack_err_count_after=0
pending_action_count_after=1
last_ack=BT:ACK:act_3bb315a0a37c:OK
```

Local WAV:

```text
.tmp\laptop_mic_sidecar\20260613-160519-laptop_mic_manual_action_prompted.wav
```

Backend WAV:

```text
D:\HuaweiMoveData\Users\35267\Documents\New project2\backend\data\audio\20260613-080527-6380d27e7b.wav
```

Pass:

```text
laptop mic real speech -> ASR -> backend AI/action planning
```

Partial pass:

```text
TTS and OLED actions reached STM32 ACK.
```

Not pass yet:

```text
fan_control action remained sent and did not ACK within the wait window.
```

Do not claim full fan physical ACK closure from this run.

## Follow-Up

1. Keep using input device `1` with `--sample-rate 16000`.
2. Use `--pre-delay 5 --cue-beep` for future manual tests.
3. Re-test the action chain with a command that creates only TTS/OLED if the goal is to prove laptop-mic-to-ACK quickly.
4. Debug `NET:FAN:ON:2` ACK separately before claiming full physical fan closure.
5. KEY2-triggered laptop recording still needs a real serial-port run that captures `BT:BTN:KEY2:SHORT`.

## Continued Full Dialogue And Hardware Tests

Backend was restarted after adding TTS speech sanitization. Health after restart:

```text
status=ok
ai_provider=dashscope_openai
ai_model=qwen-plus
cloud_ready=true
connection_count=1
online=true
uart_ok=true
session_connected=true
pending_action_count=0
```

Code change:

```text
backend/app/actions.py
```

TTS short speech now removes fragile symbols before `NET:TTSHEX`, including curly quotes, wave dashes, control characters, and non-BMP emoji. This does not change the full web reply text.

Regression:

```powershell
python -m pytest backend\tests\test_actions_protocol.py backend\tests\test_phase1.py -q
```

Result:

```text
30 passed, 1 warning
```

### Text Dialogue Memory After TTS Sanitization

Turn 1:

```text
你是谁？请用一句话回答。
```

Result:

```text
reply=我是住在你智能桌面上的AI助手，能陪你聊天、查信息，也能帮你控制设备、感知环境～
TTS payload=我是你桌面的AI小助手！
TTS=acked
OLED=acked
pending=0
```

Turn 2:

```text
你还记得我刚才问了什么吗？也请一句话回答。
```

Result:

```text
reply=记得，你刚才问“你是谁？”，我回答了自己是住在智能桌面上的AI助手～
original speech=记得，你刚才问“你是谁？
actual TTS payload=记得，你刚才问你是谁？
TTS=acked
OLED=acked
pending=0
```

This validates multi-turn dialogue memory and the TTS sanitization path.

### Voice Command: Lock

Prompted laptop mic command:

```text
请锁定桌面终端
```

ASR:

```text
provider=dashscope_paraformer
text=请锁定桌面终端。
```

Actions:

```text
TTS 桌面终端已锁定。  failed
OLED LOCKED          sent
LOCK ON              acked
last_ack=BT:ACK:act_16fe31b2d827:OK
```

Interpretation:

The voice -> ASR -> AI/action -> hardware command path reached the physical lock/RGB action ACK. However, TTS failed and OLED did not ACK in that batch, so do not claim every action in this voice batch completed.

### Voice Command: Unlock

Prompted laptop mic command:

```text
请解锁桌面终端
```

ASR:

```text
provider=dashscope_paraformer
text=请解锁桌面终端。
```

Actions:

```text
TTS=acked
OLED=acked
LOCK OFF=acked
last_ack=BT:ACK:act_9e1d2d69d769:OK
```

This is the cleanest successful proof so far:

```text
laptop mic real speech -> ASR -> cloud dialogue/action planning -> ESP32S3/STM32 -> hardware ACK
```

### Fan Commands After Restart

Fan ON:

```text
请把风扇打开到一档。
TTS=acked
OLED=acked
NET:FAN:ON:1=sent
```

Fan OFF:

```text
请关闭风扇。
TTS=acked
OLED=acked
NET:FAN:OFF=acked
last_ack=BT:ACK:act_774877341f39:OK
```

Interpretation:

`NET:FAN:OFF` is proven through ACK. `NET:FAN:ON:<level>` is still not ACKing, even though STM32 firmware has a matching `command.startsWith("NET:FAN:ON")` branch. Treat this as a remaining hardware/UART/relay-power or return-path issue. Do not claim fan ON closure yet.

### Fan Routing Correction: DRV8833 Port

The physical fan is wired to the Botelvdong DRV8833 motor-driver port, not the old `PB5` relay output. The no-ACK `NET:FAN:ON:<level>` result above should therefore be treated as a stale firmware-routing finding, not as proof that the DRV8833 fan hardware failed.

Firmware has been updated so `NET:FAN:ON:<1-3>` drives `PA0/TIM2_CH1` PWM with `PA1/TIM2_CH2` held LOW, matching the kit `PWM_DRV8833` example. `NET:FAN:OFF` now pulls both DRV8833 inputs LOW. Next validation step is to compile/flash the STM32 sketch and repeat a direct `NET:FAN:ON:2` / `NET:FAN:OFF` test before retesting the full voice command.

Follow-up: the first DRV8833 direction made the physical fan spin in reverse. Firmware now drives `PA1/TIM2_CH2` PWM with `PA0/TIM2_CH1` held LOW for `NET:FAN:ON:<1-3>`.

### Direction-Fixed DRV8833 Fan Validation

After the direction correction, direct USB checks returned `BT:OK` for both `NET:FAN:ON:2` and `NET:FAN:OFF`.

Backend text command validation also passed after the telemetry quiet guard:

```text
请把风扇打开到二档。
TTS=acked
OLED=acked
NET:FAN:ON:2=acked

请关闭风扇。
TTS=acked
OLED=acked
NET:FAN:OFF=acked
pending_action_count=0
```

Laptop microphone validation:

```text
ASR text=请把风扇打开到2档。
TTS=acked
OLED=acked
NET:FAN:ON:2=acked
pending_action_count=0

ASR text=请关闭风扇。
TTS=failed
OLED=acked
NET:FAN:OFF=acked
pending_action_count=0
```

Interpretation: the laptop mic -> ASR -> cloud action planner -> ESP32S3 -> STM32 -> DRV8833 fan command path is proven for ON and OFF. The second voice OFF batch had a TTS-only ERR, but the physical fan OFF command ACKed and the fan was shut down.
