# ASR Next Window Test Handoff - 2026-06-12

## First Instruction To Paste

```text
请先读取 docs/ASR_NEXT_WINDOW_TEST_HANDOFF_2026-06-12.md，并继续做 ESP32S3 板载麦克风 6 秒长句 ASR 实测；不要读取、打印或修改 backend/.env，保留浏览器语音兜底 /api/asr/recognized。
```

## Current Goal

在保留浏览器语音兜底、且不泄露 `backend/.env` 的前提下，继续解决 ESP32S3 板载麦克风短/中句上传到后端本地 ASR 的识别准确率问题。

本轮已经完成：

- 本地 FunASR 模型完整下载和校验。
- 后端切换到本地 FunASR/Paraformer 可用。
- ESP32S3 板载麦克风录音从 3 秒扩展到 6 秒。
- ESP32S3 6 秒 WAV 上传从大 buffer 改为 WiFiClient 分块上传。
- 增加上传写满、15 秒无进展超时、最多 3 次重试。
- 蜂鸣器和电脑提示音不可靠，测试提示改为 STM32/SYN6288 语音播报。
- 新增 ESP32S3 串口命令 `CFG:MIC:REC:CUE`：板端先说“三。二。一。”，延时后开始录音。

## Important Constraints

- 不要读取、打印、编辑、提交或泄露 `backend/.env`。
- 不要移除浏览器语音兜底接口 `/api/asr/recognized`。
- 不要依赖蜂鸣器或电脑 beep；用户已反馈没有听到。
- 使用 SYN6288 语音模块作为测试预期提示。
- 打开 COM8 会重置 ESP32S3，这是当前硬件现象，测试脚本要等待设备重新在线。

## Current Runtime State

后端：

- 地址：`http://127.0.0.1:8083`
- 已切到本地 Paraformer profile 启动。
- 最新健康检查 OK。
- ESP32S3 在线：`online=true`
- UART 正常：`uart_ok=true`
- WebSocket 会话正常：`session_connected=true`

最新成功实测：

- 音频路径：`D:\HuaweiMoveData\Users\35267\Documents\New project2\backend\data\audio\20260611-184402-ae6028c4f3.wav`
- 音频大小：`192044 bytes`
- ASR provider：`funasr_local`
- ASR error：`null`
- 识别文本：`编译没问题，刷完这一版上传失败。`
- 最终状态：`voice_state=text_bridge`

## Files Changed In This Phase

- `tools/download_modelscope_snapshot.py`
  - 新增 ModelScope 快照下载和校验脚本，支持 `--no-proxy`、`--clean`、`--sha256`。

- `backend/app/asr.py`
  - FunASR `AutoModel` 参数增加 `disable_update=True`，避免启动时联网检查造成卡顿。

- `tools/start_backend_funasr.ps1`
  - 新增 `-Profile paraformer|sensevoice`。
  - 默认 `paraformer`，用于中文长句测试。

- `docs/LOCAL_ASR_FUNASR.md`
  - 记录已验证模型和下载命令。

- `edge/esp32s3/main/main.ino`
  - `MIC_RECORD_SECONDS = 6`
  - `MIC_COUNTDOWN_CUE_DELAY_MS = 1450`
  - 新增 `writeAllToClient(...)`
  - 上传改为 WiFiClient 手写 multipart 分块上传。
  - 上传支持最多 3 次重试。
  - 新增 `captureAndUploadMicAfterCue(...)`
  - 新增串口命令：
    - `CFG:MIC:REC`
    - `CFG:MIC:REC:CUE`
    - `CFG:MIC:REC:CUE:<自定义倒计时文本>`

## Useful Commands

检查后端健康：

```powershell
Invoke-RestMethod http://127.0.0.1:8083/api/health | ConvertTo-Json -Depth 5
```

检查设备状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8083/api/state/desktop-agent-001 | ConvertTo-Json -Depth 8
```

如果 8083 后端不在，启动 Paraformer：

```powershell
.\tools\start_backend_funasr.ps1 -Profile paraformer
```

编译 ESP32S3 固件：

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

刷入 ESP32S3 固件：

```powershell
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

手动触发带倒计时录音：

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 10 --line "CFG:MIC:REC:CUE" --monitor --monitor-seconds 70
```

手动触发只做 ASR、不触发后续 AI/TTS 的带倒计时录音：

```powershell
python tools\serial_console.py COM8 --baud 115200 --open-delay 10 --line "CFG:MIC:REC:CUE:ASRONLY" --monitor --monitor-seconds 70
```

如果 `tools\serial_console.py` 不支持 `--line`，用交互方式打开后手动输入：

```text
CFG:MIC:REC:CUE
```

## Recommended Next Test

先做 3 轮固定句实测，每轮都用 `CFG:MIC:REC:CUE`，听到“三。二。一。”最后一个“一”之后立刻说话。

建议测试句：

1. `请把风扇打开到二档，并告诉我现在桌面附近的温度和湿度。`
2. `如果当前湿度超过百分之六十，请提醒我打开除湿模式。`
3. `今天天气怎么样，请结合当前桌面温湿度给我一个简短建议。`

每轮记录：

- 串口是否显示 `[MIC] recording 6 seconds...`
- 串口是否显示 `[MIC] captured 192044 bytes`
- 串口是否显示 `[MIC] POST /api/asr/transcribe -> 200`
- 后端 `last_audio_path`
- 后端 `last_asr_text`
- 是否开头丢字或混入“三二一”

## Timing Tuning

当前倒计时延时：

```cpp
static const uint16_t MIC_COUNTDOWN_CUE_DELAY_MS = 1450;
```

如果识别文本混入“三、二、一”，把延时调大到 `1600`。

如果识别文本开头丢字，把延时调小到 `1300`。

每次调整后：

```powershell
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
arduino-cli upload -p COM8 --fqbn esp32:esp32:XIAO_ESP32S3 edge\esp32s3\main
```

## Known Issues

- 蜂鸣器未工作，不能作为测试提示。
- 电脑提示音未被用户听到，不能作为测试提示。
- SYN6288 语音提示可用，但如果在录音窗口内播报会污染 ASR。
- COM8 打开会重置 ESP32S3，脚本必须等待在线后再发命令。
- 6 秒音频约 `192044 bytes`，上传链路需要分块和重试；不要退回大 buffer multipart。
- 8 秒一次性 WAV buffer 约 `256044 bytes`，当前固件实测 `ps_malloc`/`malloc` 都可能失败，串口显示 `[MIC] buffer alloc failed`；不要只改常量到 8 秒，下一步应考虑流式/分片录音上传。

## 2026-06-12 ASR-Only Retest Notes

本轮新增测试辅助能力：

- `tools/serial_console.py` 新增 `--open-delay`，用于 COM8 打开后等待 ESP32S3 重启完成再发命令。
- `tools/serial_console.py` 新增 `--monitor-seconds`，用于自动结束串口监视。
- ESP32S3 新增：
  - `CFG:MIC:REC:ASRONLY`
  - `CFG:MIC:REC:CUE:ASRONLY`
- ASR-only 命令使用 `/api/asr/transcribe` 的 `inject=false`，只更新 ASR 状态，不触发 Qwen/TTS/STM32 回复；浏览器兜底 `/api/asr/recognized` 保持不变。

6 秒、`CFG:MIC:REC:CUE` 正常注入链路三轮实测：

- 第 1 轮：`20260611-185352-76daa8570a.wav`，`192044 bytes`，识别 `夸张的哥们儿把卡都不给，免上请把风扇打开到二档，并告诉我现在桌面附近的温。`，开头混入非目标语音，句尾截断。
- 第 2 轮：`20260611-185739-99d8534d94.wav`，`192044 bytes`，识别 `如果当前湿度超过百分之六十，请提醒我打开。`，无“三二一”混入，句尾 `除湿模式` 丢失。
- 第 3 轮：`20260611-185905-8dbf9969a8.wav`，`192044 bytes`，识别 `防声音是加到了今天天气怎么样？请集合当前桌面温湿度。`，开头混入非目标语音，句尾截断。

6 秒、`CFG:MIC:REC:CUE:ASRONLY` 复测：

- 有效第 1 轮：`20260611-190247-b51b17bafd.wav`，`192044 bytes`，识别 `请把风扇开到二档，并告诉我现在桌面附近的温度和湿度。`，效果好，未触发新 AI/TTS。
- 无效第 2 轮：`20260611-190436-e82d925892.wav`，`192044 bytes`，识别内容像现场杂音/上一句，不计入固定句结果。
- 有效第 2 轮重跑：`20260611-190636-c69f3b986d.wav`，`192044 bytes`，识别 `如果当前湿超过百分之六十，请提醒我打开除湿。`，无播报污染，句尾 `模式` 丢失。
- 有效第 3 轮：`20260611-190837-b9a334e53d.wav`，`192044 bytes`，识别 `今天天气怎么样？请结合当前桌面温湿度给我一个。`，无播报污染，句尾 `简短建议` 丢失。

对三个 ASR-only 有效 WAV 做 20ms RMS 粗分析：

- 三段都是精确 `6.000s`。
- 三段在最后 `500ms` 仍有明显语音能量，尤其第 2/3 句尾部能量高。
- 初步判断：ASR-only 可解决 AI/TTS 串扰，但 6 秒窗口对当前长句语速仍会截断尾部。

8 秒尝试：

- 把 `MIC_RECORD_SECONDS` 临时改为 `8` 后编译和刷入成功。
- 实测 `CFG:MIC:REC:CUE:ASRONLY` 时串口显示 `[MIC] recording 8 seconds...` 后立即 `[MIC] buffer alloc failed`。
- 已回退并重新刷入 `MIC_RECORD_SECONDS = 6` 的稳定版，设备恢复在线。

建议下一步：

- 保留 6 秒正常链路和 ASR-only 测试命令。
- 如果必须支持当前语速的长句，优先实现流式/分片录音上传，避免一次性分配 8 秒 WAV 大 buffer。
- 也可以先尝试 7 秒常量作为风险较低的过渡实验，但仍可能受堆碎片影响，不如流式方案稳。

## Verification Already Done

- `arduino-cli compile` 通过。
- 固件已刷入 COM8。
- 后端 Paraformer profile 已启动。
- ESP32S3 6 秒录音上传成功。
- 后端 `/api/asr/transcribe` 返回 200。
- 本地 FunASR/Paraformer 成功识别真实 ESP32S3 板载麦克风音频。
- `CFG:MIC:REC:CUE:ASRONLY` 已实测可隔离 ASR，不触发新的 AI/TTS 回复。
- 8 秒一次性 buffer 已实测失败，并已回退到 6 秒稳定固件。
