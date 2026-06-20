# ESP32S3 硬件麦克风 ASR 阶段计划

更新时间：2026-06-11 22:25 +08:00

## 结论

下一阶段推进 ESP32S3 Sense 板载麦克风输入链路，但不替换现有浏览器语音入口。当前答辩稳定入口仍保留：

```text
浏览器 Web Speech API -> /api/asr/recognized -> Qwen -> STM32/SYN6288/OLED/执行器 -> ACK
```

新增硬件语音入口作为增强链路：

```text
ESP32S3 板载麦克风短录音
-> HTTP 上传 WAV/PCM 到 FastAPI
-> 后端 Paraformer ASR
-> 复用 /api/chat 文本闭环
-> Qwen 完整 reply + SYN6288 短 speech
-> ESP32S3 转发 STM32
-> STM32 ACK 回传
```

## 为什么这样做

- 浏览器语音入口已验证，适合作为答辩兜底。
- ESP32S3 麦克风链路能证明系统不是“电脑麦克风演示”，而是具备嵌入式硬件语音入口。
- 先做短录音上传，比一开始做实时流式 ASR 更稳定、可调试、可解释。
- 后端现有 `/api/asr/transcribe` 已有音频上传与 mock 注入结构，适合继续扩展为真实 Paraformer 识别。

## 阶段 1：短录音上传闭环

目标：

- ESP32S3 采集板载麦克风音频，先以 3 秒短录音为主。
- 音频格式优先使用 `16 kHz`、`mono`、`16-bit PCM`，封装为 WAV 后上传。
- ESP32S3 通过 HTTP `POST /api/asr/transcribe` 上传音频。
- 后端保存音频文件，返回音频字节数、识别文本、注入后的 chat 结果和设备状态。

建议触发方式：

```text
先用串口命令或 Web 控制按钮触发录音 3 秒
后续再扩展成按键、唤醒词或 VAD
```

阶段验收：

- 后端 `backend/data/audio/` 能保存 ESP32S3 上传的真实 WAV。
- 后端能区分：
  - 没录到音频
  - 录到了但 ASR 失败
  - ASR 成功但硬件 ACK 未完成
- 成功路径能看到：

```text
last_asr_text=<识别文本>
last_speech=<播报短句>
ack_err_count=0
pending_action_count=0
```

## 阶段 2：真实 Paraformer ASR

目标：

- 将 `ASR_PROVIDER=dashscope_paraformer` 落成真实识别，而不是只依赖 `mock_text`。
- 后端使用本机 `.env` 内的 `DASHSCOPE_API_KEY` / `ASR_WS_URL`，不要把 Key 下发到 ESP32S3、网页、小程序或文档。
- 成功识别后复用现有 `run_text_turn(...)`，不另造一套 AI/动作链路。

后端接口建议：

```text
POST /api/asr/transcribe
form-data:
  device_id=desktop-agent-001
  inject=true
  audio=<wav file>
```

阶段验收：

- 用 ESP32S3 上传真实音频，不带 `mock_text`，后端返回 `ok=true` 和真实识别文本。
- 识别文本进入 Qwen 后，Web/小程序显示完整 `reply`，SYN6288 播报短 `speech`。
- STM32 返回 TTS/OLED/必要动作 ACK。

## 阶段 3：更自然的硬件语音交互

在短录音闭环稳定后再做：

- 按键长按说话。
- VAD 静音检测，自动结束录音。
- 本地唤醒词。
- WebSocket 音频分片或 Paraformer 实时流式 ASR。

这些不作为当前最小可验收目标，避免把答辩稳定链路拖复杂。

## 风险与兜底

- ESP32S3 采音质量、I2S 参数、内存缓冲和 Wi-Fi 上传都可能引入不稳定。
- 现场演示时保留浏览器语音入口作为兜底，不影响已跑通的智能对话主线。
- 如果硬件 ASR 暂时失败，仍可展示：
  - Web 真实语音
  - Qwen 通用大模型回答
  - 传感器状态感知
  - RFID
  - STM32/SYN6288/OLED/风扇 ACK 闭环

## 下一窗口第一条指令

```text
请先读取 docs/NEXT_WINDOW_HANDOFF.md、docs/CURRENT_PROGRESS_HANDOFF.md、docs/ESP32_MIC_ASR_PHASE_PLAN.md、docs/AI_ASR_DECISION.md、docs/PROTOCOL.md、docs/HARDWARE_WIRING.md。当前目标是在保留浏览器语音兜底的前提下，推进 ESP32S3 Sense 板载麦克风短录音上传到后端 /api/asr/transcribe，再接入真实 Paraformer ASR 并复用 Qwen/STM32 ACK 主链路。不要打印、提交、泄露或无必要改动 backend/.env。
```
