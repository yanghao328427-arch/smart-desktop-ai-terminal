# Passive Buzzer Music Design

Date: 2026-06-13

## Goal

Add short musical feedback on the passive buzzer without blocking the STM32 executor loop.

## Hardware Assumption

- Buzzer pin: `PB9`
- Buzzer type: passive, so firmware must generate square-wave frequencies with `tone()`.
- This is not audio playback; it is note-frequency playback.

## Protocol

```text
NET:MUSIC:SUCCESS
NET:MUSIC:ALERT
NET:MUSIC:SCALE
NET:MUSIC:STARTUP
NET:MUSIC:BIRTHDAY
NET:MUSIC:STOP
NET:MUSIC:LIST?
```

Wrapped production form:

```text
NET:CMD:<action_id>:NET:MUSIC:SUCCESS
```

ACK behavior is unchanged:

```text
BT:ACK:<action_id>:OK
BT:ACK:<action_id>:ERR
```

## Runtime Design

The STM32 firmware stores each melody as a compact array of `{frequency, duration_ms}` notes. The player keeps only the active melody pointer, note index, and note start time. `loop()` calls `updateMusicPlayer()` to advance the next note when the current note duration plus a small gap has elapsed.

This avoids blocking serial parsing, OLED updates, telemetry, fan control, and ACK return while the melody is playing.

## Backend Action

New action type:

```json
{"type":"buzzer_music","payload":{"preset":"birthday"}}
```

The backend maps unknown presets to `SUCCESS` and accepts these presets:

```text
success, alert, scale, startup, birthday, stop
```

Natural-language local fallback recognizes phrases such as:

```text
播放音乐
播放生日歌
播放胜利音
停止音乐
```

## Validation

Minimum checks:

```powershell
arduino-cli compile --fqbn STMicroelectronics:stm32:GenF1:pnum=BLUEPILL_F103C8 --build-path .tmp\build-stm32 firmware\stm32\stm32_executor
python -m pytest backend\tests\test_actions_protocol.py backend\tests\test_phase1.py -q
python tools\serial_console.py COM7 --baud 115200 --line "NET:MUSIC:SCALE" --monitor --monitor-seconds 5
python tools\serial_console.py COM7 --baud 115200 --line "NET:MUSIC:STOP" --monitor --monitor-seconds 3
```
