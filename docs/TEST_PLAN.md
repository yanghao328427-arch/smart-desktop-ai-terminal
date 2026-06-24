# 分层测试计划

## 0. 后端自测

```powershell
cd backend
python -m pytest -q
```

验收：

- WebSocket 能完成 `wake -> text -> assistant -> stm32/commands -> idle`。
- WebSocket 在线时，STM32 ACK 通过 WebSocket 返回并更新 `ack_ok_count`。
- WebSocket 断开后，ESP32S3 恢复 `/api/hardware/commands/{device_id}` 轮询，ACK 自动退回 `/api/hardware/ack`。
- 动作能转换成 `NET:CMD:<id>:NET:*`。
- RFID 在线注册能把真实 RC522 下一次刷卡绑定到 SQLite 用户上下文。
- 课程要求清单存在并覆盖四层架构。

云端对话冒烟测试：

```powershell
cd "D:\HuaweiMoveData\Users\35267\Documents\New project2"
python .\tools\cloud_dialogue_smoke.py --base-url http://127.0.0.1:8083
```

验收：

- 输出 `cloud_ready=true`、`ai_provider=dashscope_openai`、`ai_model=qwen-plus`。
- 三轮对话均有 `reply`，并产生 `tts_speak` / `oled_display` 等动作。
- 输出不包含 DashScope API Key。
- 如果 `cloud_ready=false`，说明后端仍在本地规则兜底；硬件可演示，但答辩时不能宣称已经走真实云端模型。
- 答辩前强制云端验收可追加 `--require-cloud`，此时 `cloud_ready=false` 会返回非零退出码。

## 1. STM32 单板测试

串口调试命令：

```text
NET:UART?
NET:OLED:HELLO
NET:TTS:测试中，请说话
NET:BEEP
NET:FAN:ON:2
NET:FAN:OFF
NET:TELEMETRY?
```

验收：

- OLED 显示正常。
- SYN6288 能播中文短句。
- 命令执行后返回 `BT:ACK:<id>:OK`。
- `NET:TELEMETRY?` 能返回 `BT:{...}` 传感器 JSON。
- 不出现长时间阻塞导致按键或传感器失控。

## 2. ESP32S3 到 STM32 桥接

从 ESP32S3 USB 串口触发：

```text
CFG:UART:PING
CFG:TTS:测试中，请说话
CFG:OLED:LISTEN
```

验收：

- ESP32S3 日志显示发送 `NET:*`。
- STM32 返回 `BT:PONG` 或 `BT:ACK`。
- 后端 heartbeat 中 `uart_ok=true`。

补充传感器验收：

1. 刷录带 telemetry 的 STM32 固件。
2. 等待后端 `/api/state/desktop-agent-001` 刷新。
3. 观察 `sensors` 内是否出现 `pot_raw`、`temperature_c`、`humidity_pct`、`distance_cm/distance_ok`。

验收：

- 至少两类传感器数据进入后端 `sensors`。
- Web 控制台和小程序首页能显示这些实时值。

## 3. RFID 独立测试

流程：

1. RC522 接 ESP32S3。
2. 刷卡读取 UID。
3. 用网页或小程序携带 `CONTROL_TOKEN` 调用 `/api/rfid/enroll/start` 发起在线注册。
4. 刷真实卡后，后端 `/api/rfid/enroll/{enroll_id}` 显示 `completed`，Web 控制台显示用户模式并生成解锁动作。
5. 需要调试时，才用 `/api/rfid/register` 手动绑定 UID。

验收：

- 至少一张卡可稳定读出 UID。
- 未注册卡不会进入任何用户上下文。
- 已注册卡能改变后端上下文，并且不同 UID 对应不同用户会话。

## 4. 文本 AI 闭环

流程：

1. 打开 `/console`。
2. 输入“你是谁”。
3. 输入“打开风扇”。
4. 输入“屏幕显示 专注模式”。

验收：

- 页面显示回复和动作。
- 后端生成 `NET:TTS`、`NET:FAN`、`NET:OLED`。
- STM32 执行后 ACK。

## 5. 语音闭环

当前后端已支持两条语音入口：

1. 浏览器真实语音识别后调用 `/api/asr/recognized`
2. 短音频上传 `/api/asr/transcribe` 作为保底/调试手段

调试保底接口：

```text
POST /api/asr/transcribe
form-data:
  audio=<wav/webm/pcm>
  mock_text=你是谁
  inject=true
```

标准正式测试流程：

1. 在 Chrome / Edge 打开 `/console`，点击“开始语音”。
2. 用户直接说一句真实话语，如“你是谁”“打开风扇”。
3. 立刻查看 `/api/realtime/diagnostics/desktop-agent-001`。
4. 只在浏览器语音不可用时，才退回 `mock_text` 或音频上传保底测试。

记录：

```text
测试时间：
用户实际说的话：
是否听到提示：
ESP32S3 voice_state：
last_audio_bytes：
last_asr_text：
assistant：
stm32_commands：
uart_ok：
last_ack：
```

验收：

- 能区分没录到、ASR 失败、LLM 失败、UART 失败。
- 不再用“没有反馈”这种模糊结论。
- 答辩主线应以“真实语音进入 AI 对话”为准，而不是预设录音回放。
