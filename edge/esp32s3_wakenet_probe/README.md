# ESP32S3 WakeNet probe

This is an isolated ESP-IDF probe for the XIAO ESP32S3 Sense PDM microphone and the official WakeNet phrase `你好小鑫`.

It intentionally does not replace the working Arduino bridge firmware. Do not flash it until:

1. `idf.py build` succeeds.
2. The generated model partition contains `wn9_nihaoxiaoxin_tts`.
3. The current stable Arduino and STM32 binaries remain available under `.tmp/rollback-wakenet-baseline-20260625`.

Build:

```powershell
& D:\Espressif\v5.5.3\esp-idf\export.ps1
Set-Location edge\esp32s3_wakenet_probe
idf.py set-target esp32s3
idf.py build
```

The probe only logs `WAKE_DETECTED` and temporarily disables WakeNet. The production integration will add the input arbiter:

- KEY2/PTT has highest priority.
- WakeNet is disabled while KEY2 is held.
- WakeNet is disabled during SYN6288 output.
- After wake detection, STM32 says `我在`; laptop command capture starts after playback plus echo guard.
